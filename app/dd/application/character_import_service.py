"""The character-import flow (add-dnd-game-face task 9.3; design Д7;
spec dnd-character-import).

One decision tree, one home (the dataset importer's posture): the caller
hands the file text and an optional target, the service answers with a
frozen outcome — never re-deciding the check/write/confirm order at a usage
site.

The tree:

1. the full check runs FIRST (:class:`CharacterValidatorService`) — a report
   with errors answers BLOCKED and no write ever happened (structural, not
   a cleanup);
2. the target is always the user's explicit action (spec «Точки входа
   явные, сопоставления по имени нет»): no character id means CREATE, a
   character id without confirmation answers NEEDS_CONFIRMATION and touches
   nothing — the person, their fields and their file-snapshot all stay as
   they stood (spec scenario «Перезапись требует подтверждения»);
3. a clean document lays out completely: the name, the avatar (a data-URI
   image through the kernel's single ingest door; any other avatar text
   becomes a visible «Аватар» block), the five reference triples resolved
   through the connected-dataset index — snapshot name from the record when
   the set answers, snapshot name from the FILE when it does not (Д7) — the
   level, the structural render and every text block of the document;
4. one ``GameSessionUoW.transaction()`` finishes the write (coding
   principle 3): entity row (create or in-place update), then the module's
   ext row with the triples, the level, the RAW FILE VERBATIM and the named
   blocks (structural first; a document block of the same name merges into
   the same block below the render — nothing silently lost). Spell links
   and the LSS sheet id are not derived from the file and stay untouched.

The raw snapshot is also the way back out: :meth:`save_raw_document` writes
the stored bytes verbatim (spec scenario «Файл можно забрать обратно») —
never a reassembly from our fields (spec: the file stays the source of
truth).
"""
from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.dd.application.character_validator_service import CharacterValidatorService
from app.dd.domain.character import LINK_SLOTS, ReferenceLink, empty_ext
from app.dd.domain.character_checks import CODE_CHAR_AVATAR
from app.dd.domain.character_editor import editor_doc_to_text
from app.dd.domain.character_render import structural_blocks
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.dd.infrastructure.db.dd_models import encode_text_blocks
from app.dd.infrastructure.repositories.dd_character_repository import (
    DdCharacterRepository,
)
from app.domain.entity_registry import EntityType
from app.infrastructure.db.uow import GameSessionUoW

if TYPE_CHECKING:
    from app.dd.application.dataset_index_service import DatasetIndexService
    from app.application.services.entity_service import EntityService
    from app.infrastructure.images.store import ImageStore

#: The envelope key of each reference slot (Д7 «info.charClass.id и т.п.» —
# only «class» disagrees with the slot name).
_INFO_KEYS: dict[str, str] = {
    "race": "race",
    "subrace": "subrace",
    "class": "charClass",
    "subclass": "subclass",
    "background": "background",
}

#: The block name an avatar that is not a storable image keeps its text under.
BLOCK_AVATAR = "Аватар"

#: The confirmation question of the overwrite flow (spec scenario
#: «Перезапись требует подтверждения» — the master must read that the whole
#: face, the file-snapshot included, is replaced).
OVERWRITE_CONFIRM_BODY = (
    "Перезаписать персонажа из файла LSS? Поля, карточка D&D, текстовые "
    "блоки и сохранённый файл-снимок будут заменены содержимым файла."
)


class CharacterImportStatus(Enum):
    """The four answers of one import request."""

    #: A new character row grew from the file.
    CREATED = "created"
    #: An existing character was replaced after confirmation.
    OVERWRITTEN = "overwritten"
    #: A replacement was requested without confirmation yet — nothing was
    #: touched; the screen asks, then re-requests with ``confirmed=True``.
    NEEDS_CONFIRMATION = "needs_confirmation"
    #: The report's errors refused the document; nothing was written.
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CharacterImportOutcome:
    """One import answer: the branch, the character behind it (when one was
    written), the Russian sentence for the screen and the check report the
    screen lists (warnings accompany every success)."""

    status: CharacterImportStatus
    character_id: int | None = None
    name: str = ""
    message: str = ""
    report: ValidationReport | None = None


class CharacterImportService:
    """Check → lay out → one transaction; both entry points share this door."""

    def __init__(
        self,
        *,
        uow: GameSessionUoW,
        entity_services: Callable[[], Mapping[str, "EntityService"]],
        image_store: "ImageStore | None" = None,
        dataset_index: "DatasetIndexService | None" = None,
        validator: CharacterValidatorService | None = None,
        now: Callable[[], date] = date.today,
    ) -> None:
        self._uow = uow
        # The catalog door is lazy on purpose: the composition builds this
        # service before the kernel's entity catalog exists (main.py's start
        # order); at import time the door answers the live catalog.
        self._entity_services = entity_services
        self._images = image_store
        self._index = dataset_index
        self._validator = validator if validator is not None else CharacterValidatorService()
        self._now = now

    # ── the flow ─────────────────────────────────────────────────────────────

    async def import_character(
        self, content: str, *, character_id: int | None = None, confirmed: bool = False
    ) -> CharacterImportOutcome:
        """Import one character-export text (module docstring for the tree)."""
        report, data = self._validator.validate(content)
        if not report.import_allowed or data is None:
            return CharacterImportOutcome(
                status=CharacterImportStatus.BLOCKED, report=report
            )
        if character_id is not None and not confirmed:
            # Spec scenario «Перезапись требует подтверждения»: the answer
            # arrives BEFORE any write; the person and the snapshot stayed.
            return CharacterImportOutcome(
                status=CharacterImportStatus.NEEDS_CONFIRMATION,
                character_id=character_id,
                message=OVERWRITE_CONFIRM_BODY,
                report=report,
            )
        issues = list(report.issues)
        name = str(data.get("name") or "").strip()
        image_id, avatar_issues, avatar_block = await self._avatar(data.get("avatar"))
        issues.extend(avatar_issues)
        blocks, block_issues = self._text_blocks(data)
        issues.extend(block_issues)
        if avatar_block is not None:
            blocks = self._merge_block(blocks, BLOCK_AVATAR, avatar_block)
        links, level = await self._face(data)
        report = ValidationReport.of(issues)
        async with self._uow.transaction():
            written_id = await self._write(
                character_id=character_id,
                name=name,
                image_id=image_id,
                links=links,
                level=level,
                content=content,
                blocks=blocks,
            )
        if character_id is None:
            return CharacterImportOutcome(
                status=CharacterImportStatus.CREATED,
                character_id=written_id,
                name=name,
                message=f"Персонаж «{name}» создан из файла LSS.",
                report=report,
            )
        return CharacterImportOutcome(
            status=CharacterImportStatus.OVERWRITTEN,
            character_id=written_id,
            name=name,
            message=f"Персонаж «{name}» перезаписан из файла LSS.",
            report=report,
        )

    async def save_raw_document(self, character_id: int, path: str) -> bool:
        """Write the stored raw snapshot to disk byte-for-byte (spec scenario
        «Файл можно забрать обратно»); ``False`` when the character never
        imported a file. A plain read + one file write — no transaction."""
        row = await DdCharacterRepository(self._uow.session).get_ext(character_id)
        if row is None or not row.raw_document:
            return False
        Path(path).write_bytes(row.raw_document.encode("utf-8"))
        return True

    # ── layout (Qt-free, storage-free halves) ────────────────────────────────

    async def _avatar(
        self, raw: object
    ) -> tuple[int | None, list[CheckIssue], str | None]:
        """The avatar half: a data-URI image goes through the kernel's single
        ingest door (dedup, files, row); any other text is content the reader
        must still see, so it keeps a «Аватар» block; a data-URI that is not
        an image warns and keeps its fact in the raw snapshot (never a silent
        loss, never a refusal of the whole character)."""
        if not isinstance(raw, str) or not raw.strip():
            return None, [], None
        text = raw.strip()
        if text.startswith("data:") and ";base64," in text:
            if self._images is None:
                return (
                    None,
                    [
                        CheckIssue(
                            code=CODE_CHAR_AVATAR,
                            severity=Severity.WARNING,
                            path="data.avatar",
                            message="изображение аватара не сохранено: хранилище "
                            "изображений недоступно; файл-снимок сохранил его",
                        )
                    ],
                    None,
                )
            try:
                payload = text.split(";base64,", 1)[1]
                data = base64.b64decode(payload, validate=True)
                image_id = await self._images.store(data)
            except (binascii.Error, ValueError):
                return (
                    None,
                    [
                        CheckIssue(
                            code=CODE_CHAR_AVATAR,
                            severity=Severity.WARNING,
                            path="data.avatar",
                            message="аватар не является читаемым изображением; "
                            "содержимое сохранено в файле-снимке",
                        )
                    ],
                    None,
                )
            return image_id, [], None
        return None, [], text

    async def _face(self, data: dict[str, Any]) -> tuple[dict[str, ReferenceLink], int | None]:
        """The five triples + the level. A connected record gives its live
        pair and its live name; a disconnected or absent record keeps the
        file's snapshot with an empty source (Д7 — the tab later annotates
        it, the service never re-resolves)."""
        info = data.get("info")
        info = info if isinstance(info, dict) else {}
        snapshot = await self._index.snapshot() if self._index is not None else None
        links: dict[str, ReferenceLink] = {}
        for slot, section, _type_key in LINK_SLOTS:
            ref = info.get(_INFO_KEYS[slot])
            if not isinstance(ref, dict):
                links[slot] = ReferenceLink("", "", "")
                continue
            ref_id = ref.get("id")
            ref_id = str(ref_id) if isinstance(ref_id, str) else ""
            file_name = ref.get("name")
            file_name = str(file_name) if isinstance(file_name, str) else ""
            if snapshot is None or not ref_id:
                links[slot] = ReferenceLink("", ref_id, file_name)
                continue
            found = None
            for dataset_id in snapshot.ids:
                found = snapshot.entry(section, dataset_id, ref_id)
                if found is not None:
                    break
            if found is not None:
                links[slot] = ReferenceLink(dataset_id, ref_id, found.name)
            else:
                links[slot] = ReferenceLink("", ref_id, file_name)
        level = data.get("level")
        if not isinstance(level, int) or isinstance(level, bool):
            level = None
        return links, level

    def _text_blocks(self, data: dict[str, Any]) -> tuple[dict[str, str], list[CheckIssue]]:
        """Structural blocks first (the fixed order of the render), then the
        document's own text blocks in file order; a name clash merges the two
        halves into one block (render above, the author's text below)."""
        blocks: dict[str, str] = {}
        for name, text in structural_blocks(data):
            blocks[name] = text
        issues: list[CheckIssue] = []
        raw_blocks = data.get("blocks")
        if isinstance(raw_blocks, dict):
            for name, value in raw_blocks.items():
                if not isinstance(name, str) or not name:
                    continue
                text, block_issues = editor_doc_to_text(value)
                # Re-anchor the converter's relative paths under the block.
                issues.extend(
                    CheckIssue(
                        code=issue.code,
                        severity=issue.severity,
                        path=f"{name} · {issue.path}",
                        message=issue.message,
                    )
                    for issue in block_issues
                )
                blocks = self._merge_block(blocks, name, text)
        return blocks, issues

    @staticmethod
    def _merge_block(blocks: dict[str, str], name: str, text: str) -> dict[str, str]:
        """A document block named like a structural one joins it below the
        render instead of overwriting it (dict copy — the input stays)."""
        merged = dict(blocks)
        existing = merged.get(name)
        if existing is None:
            merged[name] = text
        else:
            merged[name] = f"{existing}\n\n{text}"
        return merged

    # ── the single transaction finish ────────────────────────────────────────

    async def _write(
        self,
        *,
        character_id: int | None,
        name: str,
        image_id: int | None,
        links: Mapping[str, ReferenceLink],
        level: int | None,
        content: str,
        blocks: Mapping[str, str],
    ) -> int:
        catalog = self._entity_services()
        entity_service = catalog.get(EntityType.CHARACTER.value)
        if entity_service is None:  # a catalog without characters cannot serve
            raise RuntimeError("каталог служб сущностей не знает персонажей")
        repo = DdCharacterRepository(self._uow.session)
        if character_id is None:
            extra: dict[str, Any] = {}
            if image_id is not None:
                extra["image_id"] = image_id
            row = await entity_service.create_entity(
                name=name,
                characteristics="",
                backstory="",
                start_date=self._now(),
                end_date=None,
                **extra,
            )
            character_id = int(row.id)
        else:
            updates: dict[str, Any] = {"name": name}
            if image_id is not None:
                updates["image_id"] = image_id
            await entity_service.update_entity(character_id, **updates)
        ext_row = await repo.get_ext(character_id) or await repo.insert_ext(character_id)
        for slot, _section, _type_key in LINK_SLOTS:
            link = links.get(slot) or empty_ext().links[slot]
            setattr(ext_row, f"{slot}_source_key", link.source_key)
            setattr(ext_row, f"{slot}_ref_id", link.ref_id)
            setattr(ext_row, f"{slot}_snapshot_name", link.snapshot_name)
        ext_row.level = level
        # The file itself — verbatim, the source of truth (spec «Сырой файл
        # хранится всегда и остаётся источником правды»).
        ext_row.raw_document = content
        ext_row.text_blocks = encode_text_blocks(dict(blocks))
        return character_id
