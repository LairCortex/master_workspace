"""ImageStore — single ingest/GC pipeline for file-based image storage.

See design D4 (ingest), D6 (GC), D7 (startup scan). One instance is bound to
one game's ``images/`` directory and its ``AsyncSession`` (DI in
``Application.start()``); ``EntityCardDialog`` and ``XlsxImportService`` are
both clients of ``store()`` — no other code writes to ``images/`` directly.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImageReader
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import CharacterModel, ImageModel, LocationModel, OrganizationModel
from app.infrastructure.images.paths import PREVIEW_SUFFIX, original_path, preview_path
from app.infrastructure.images.preview import generate_preview

logger = logging.getLogger("app.images.store")

# Models whose image_id references ImageModel — used by refcount/GC to scan
# every possible referrer (design D3: refcount = COUNT(*) across 3 tables).
_REFERRING_MODELS = (OrganizationModel, CharacterModel, LocationModel)


class ImageStore:
    def __init__(self, session: AsyncSession, image_dir: Path | str) -> None:
        self._session = session
        self._image_dir = Path(image_dir)

    # ── Ingest ────────────────────────────────────────────────────────────

    async def store(self, data: bytes) -> int:
        """Validate, dedup and persist an image; return its ``images.id``.

        Raises ``ValueError`` if ``data`` cannot be decoded as an image.
        """
        img, ext = self._decode(data)
        sha = hashlib.sha256(data).hexdigest()

        row = await self._get_by_sha(sha)
        if row is not None and self._files_present(row.sha256, row.ext):
            return row.id  # dedup-hit: no write

        orig_path = original_path(self._image_dir, sha, ext)
        prev_path = preview_path(self._image_dir, sha)
        self._atomic_write(orig_path, data)
        self._atomic_write(prev_path, generate_preview(data))

        if row is not None:
            # Row existed but files were missing (startup-gc self-heals this
            # normally); files are now regenerated for the existing row.
            return row.id

        new_row = ImageModel(
            sha256=sha, ext=ext, width=img.width(), height=img.height(), size_bytes=len(data),
        )
        self._session.add(new_row)
        try:
            await self._session.flush()
        except IntegrityError:
            # Race: another store() for the same content won the insert.
            await self._session.rollback()
            existing = await self._get_by_sha(sha)
            if existing is None:
                raise
            return existing.id
        return new_row.id

    def _decode(self, data: bytes):
        """Decode + detect real format. Returns (QImage, ext)."""
        # QBuffer(QByteArray) does not take ownership of the byte array — the
        # QByteArray must be kept alive (a named local, not an inline temp)
        # for the whole time the buffer is read from.
        byte_array = QByteArray(data)
        buf = QBuffer(byte_array)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buf)
        img = reader.read()
        if img.isNull():
            raise ValueError("Cannot decode image data")
        fmt = bytes(reader.format()).decode("ascii", errors="ignore").lower()
        return img, fmt or "png"

    async def _get_by_sha(self, sha256: str) -> ImageModel | None:
        result = await self._session.execute(select(ImageModel).where(ImageModel.sha256 == sha256))
        return result.scalars().first()

    def _files_present(self, sha256: str, ext: str) -> bool:
        return (
            original_path(self._image_dir, sha256, ext).exists()
            and preview_path(self._image_dir, sha256).exists()
        )

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        tmp.write_bytes(data)
        tmp.rename(path)

    # ── Path resolution for display ─────────────────────────────────────

    async def original_file_path(self, image_id: int) -> Path | None:
        row = await self._session.get(ImageModel, image_id)
        if row is None:
            return None
        return original_path(self._image_dir, row.sha256, row.ext)

    async def preview_file_path(self, image_id: int) -> Path | None:
        row = await self._session.get(ImageModel, image_id)
        if row is None:
            return None
        return preview_path(self._image_dir, row.sha256)

    # ── Refcount / GC (design D6) ────────────────────────────────────────

    async def refcount(self, image_id: int) -> int:
        """Count how many entities across organizations/characters/locations
        reference ``image_id`` (design D3: one COUNT, not per-table checks)."""
        total = 0
        for model in _REFERRING_MODELS:
            result = await self._session.execute(
                select(func.count()).select_from(model).where(model.image_id == image_id)
            )
            total += result.scalar() or 0
        return total

    async def gc_after_commit(self, *old_image_ids: int | None) -> None:
        """Best-effort cleanup of images no longer referenced by anyone.

        Must run after the caller has already committed the ref mutation
        (design D6): a failed unlink here only logs — it must never affect
        the user operation that already succeeded.
        """
        any_removed = False
        for image_id in old_image_ids:
            if not image_id:
                continue
            if await self.refcount(image_id) > 0:
                continue
            row = await self._session.get(ImageModel, image_id)
            if row is None:
                continue
            ok_orig = self._safe_unlink(original_path(self._image_dir, row.sha256, row.ext))
            ok_prev = self._safe_unlink(preview_path(self._image_dir, row.sha256))
            if not (ok_orig and ok_prev):
                # Leave row + leftover files: next startup_gc will pick this
                # up as an "unreferenced row" and retry the unlink.
                continue
            await self._session.delete(row)
            any_removed = True
        if any_removed:
            await self._session.commit()

    async def startup_gc(self) -> None:
        """Restore the storage invariant (design D7) when a game is opened.

        Runs a bounded, no-decode scan: orphan files without a row are
        deleted; rows without an original are dropped (references nulled);
        rows with an original but no preview get the preview regenerated;
        rows with no references left are dropped along with their files.
        """
        self._cleanup_tmp_files()
        disk_hashes = self._scan_disk_hashes()

        result = await self._session.execute(select(ImageModel))
        rows = list(result.scalars().all())
        known_hashes = {row.sha256 for row in rows}

        for sha, paths in disk_hashes.items():
            if sha not in known_hashes:
                for p in paths:
                    self._safe_unlink(p)

        for row in rows:
            orig = original_path(self._image_dir, row.sha256, row.ext)
            prev = preview_path(self._image_dir, row.sha256)

            if not orig.exists():
                await self._null_references(row.id)
                await self._session.delete(row)
                continue

            if not prev.exists():
                try:
                    self._atomic_write(prev, generate_preview(orig.read_bytes()))
                except (OSError, ValueError) as exc:
                    logger.error("Failed to regenerate preview for image %s: %s", row.id, exc)

            if await self.refcount(row.id) == 0:
                self._safe_unlink(orig)
                self._safe_unlink(prev)
                await self._session.delete(row)

        await self._session.commit()

    async def _null_references(self, image_id: int) -> None:
        for model in _REFERRING_MODELS:
            await self._session.execute(
                update(model).where(model.image_id == image_id).values(image_id=None)
            )

    def _cleanup_tmp_files(self) -> None:
        if not self._image_dir.exists():
            return
        for p in self._image_dir.rglob("*.tmp-*"):
            self._safe_unlink(p)

    def _scan_disk_hashes(self) -> dict[str, list[Path]]:
        """Map hash -> all files on disk named after it (original + preview)."""
        found: dict[str, list[Path]] = {}
        if not self._image_dir.exists():
            return found
        for p in self._image_dir.rglob("*"):
            if not p.is_file():
                continue
            name = p.name
            sha = name[: -len(PREVIEW_SUFFIX)] if name.endswith(PREVIEW_SUFFIX) else p.stem
            found.setdefault(sha, []).append(p)
        return found

    def _safe_unlink(self, path: Path) -> bool:
        """Unlink ``path`` if present; log and report failure, never raise."""
        if not path.exists():
            return True
        try:
            path.unlink()
            return True
        except OSError as exc:
            logger.error("Failed to unlink %s: %s", path, exc)
            return False
