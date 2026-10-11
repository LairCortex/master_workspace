"""The grimoire file storage of the D&D module (add-dnd-game-face, task 4.2;
design Д8; spec dnd-grimoire-import «файл хранится в глобальном хранилище
приложения под своим идентификатором»).

One grimoire is ONE file under ``~/.nri_manager/grimoires/`` (the location
constant lives in ``app.infrastructure.paths`` — the one source):

* ``<grimoire_id>.json`` — the Foundry spell document, byte-identical to what
  the import accepted (the module never edits a grimoire).

Unlike the dataset shelf there is no sidecar and no SRD half of the library: a
grimoire is always the master's own file, nothing is downloaded and nothing is
checked on a schedule, so the bytes ARE the record (design Д8 names only the
document file). The file-name grammar is the module's single safe-id rule
(:func:`app.dd.domain.dataset.is_valid_dataset_id` — the one place that
knowledge lives), validated here before any path is built, so an id from a
foreign document can never steer a write outside the shelf.

The mechanics are the dataset shelf's, copied on purpose: the directory is
created on the storage's FIRST access, every write is a tmp file +
``os.replace`` inside the same directory (a reader never sees half a file, a
crash leaves the previous bytes), and reading is tolerant — a document that no
longer parses still lists, under its file name, because the list is the
master's proof that their file is still there (spec «Отключил — файл жив»).
Confirmation-before-replace is a SERVICE rule (the import service owns it);
this layer only persists, answers presence and reads.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.dd.domain.dataset import is_valid_dataset_id
from app.dd.domain.grimoire import grimoire_title_from_document
from app.infrastructure import paths

_LOGGER = logging.getLogger(__name__)

#: File-name suffix of one grimoire shelf.
GRIMOIRES_SUFFIX = ".json"


@dataclass(frozen=True)
class StoredGrimoire:
    """One shelf of the global grimoire library: the id the game connects to
    and the title read from the file itself (the file name once it does not
    parse or names nothing)."""

    grimoire_id: str
    title: str


class GrimoireStorage:
    """The file shelf of the global grimoire library (one instance per app)."""

    def __init__(self, root: Path | None = None) -> None:
        # Resolved at CONSTRUCTION from the paths module attribute, so a test
        # (or a future override) that rebinds ``paths.GRIMOIRES_DIR`` before
        # building the storage owns the shelf — the DatasetStorage posture.
        self._root = Path(root) if root is not None else paths.GRIMOIRES_DIR

    @property
    def root(self) -> Path:
        return self._root

    def _ensure_root(self) -> None:
        """The shelf is created on first access, never on import."""
        self._root.mkdir(parents=True, exist_ok=True)

    def document_path(self, grimoire_id: str) -> Path:
        """``<grimoire_id>.json`` under the root, after id validation — the
        ONLY place a storage path is built."""
        if not is_valid_dataset_id(grimoire_id):
            raise ValueError(f"grimoire id {grimoire_id!r} is not a safe file name")
        return self._root / f"{grimoire_id}{GRIMOIRES_SUFFIX}"

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """tmp + rename inside the target directory; on any failure the tmp is
        removed and the previous target bytes stay."""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        try:
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    # ── write ────────────────────────────────────────────────────────────────

    def save(self, grimoire_id: str, content: str) -> None:
        """Persist the bytes for ``grimoire_id``, overwriting any previous
        shelf (the confirmation rule is the import service's)."""
        document = self.document_path(grimoire_id)
        self._ensure_root()
        self._atomic_write(document, content)

    # ── read ─────────────────────────────────────────────────────────────────

    def exists(self, grimoire_id: str) -> bool:
        """Whether the shelf still holds the file (spec: a disconnected
        grimoire stays connectable, a vanished one is only ever marked)."""
        return self.document_path(grimoire_id).is_file()

    def load_content(self, grimoire_id: str) -> str | None:
        """The stored document text, ``None`` when the shelf is absent."""
        document = self.document_path(grimoire_id)
        return document.read_text(encoding="utf-8") if document.is_file() else None

    def list_grimoires(self) -> list[StoredGrimoire]:
        """Every shelf, ordered by id — titles from the documents themselves,
        a file that no longer parses still lists under its file name (the
        tolerant posture of :meth:`…dataset_storage.DatasetStorage.list_datasets`)."""
        self._ensure_root()
        entries: list[StoredGrimoire] = []
        for document in sorted(self._root.glob(f"*{GRIMOIRES_SUFFIX}")):
            grimoire_id = document.name[: -len(GRIMOIRES_SUFFIX)]
            entries.append(
                StoredGrimoire(
                    grimoire_id=grimoire_id,
                    title=_read_title(document, grimoire_id),
                )
            )
        return entries


def _read_title(document: Path, grimoire_id: str) -> str:
    """The file's own caption for the list; unreadable bytes and a document
    naming nothing keep the shelf listed under the file-name id."""
    try:
        data = json.loads(document.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        _LOGGER.warning("Grimoire %s is unreadable for the list: %s", document, exc)
        return grimoire_id
    return grimoire_title_from_document(data, grimoire_id)
