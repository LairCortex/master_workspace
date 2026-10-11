"""The dataset file storage of the D&D module (add-dnd-module-foundation,
task 3.1; design Д4).

One dataset is one shelf of three files under ``~/.nri_manager/datasets/``
(the path constant lives in ``app.infrastructure.paths`` — the one source):

* ``<dataset_id>.json`` — the dataset document, byte-identical to what the
  library accepted (SRD export or imported homebrew);
* ``<dataset_id>.meta.json`` — the sidecar: source (``srd``/``homebrew``),
  import date, sha256 of the document, the validator's last error count;
* ``<dataset_id>.spells.txt`` (official sets only) — the SRD spell-slug list
  the spell checks read; optional, absence just skips those checks (design Д5).

The catalogue directory is created on the storage's FIRST access, never on
import. Every write goes through a tmp file + ``os.replace`` in the same
directory, so a reader never sees a half-written file and a crash leaves the
previous bytes intact (design Goals: «либо набор оказался в хранилище
целым, либо хранилище не менялось»). Confirmation-before-replace and the
SRD protection are SERVICE-level rules (the library service owns them); this
layer only persists, validates the id grammar before touching a path, and
reads tolerantly: a damaged sidecar degrades to «homebrew, unchecked», a
damaged document keeps its shelf in the list under the file name.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app.dd.domain.dataset import (
    DatasetMeta,
    DatasetSource,
    StoredDataset,
    dataset_title_from_document,
    is_valid_dataset_id,
)
from app.infrastructure import paths

_LOGGER = logging.getLogger(__name__)

#: File-name suffixes of one shelf (design Д4). The meta suffix ENDS WITH the
#: document suffix, so listing must skip it explicitly.
DATASET_SUFFIX = ".json"
DATASET_META_SUFFIX = ".meta.json"
DATASET_SPELLS_SUFFIX = ".spells.txt"


class DatasetStorage:
    """The file shelf of the global dataset library (one instance per app)."""

    def __init__(self, root: Path | None = None) -> None:
        # The default is resolved at CONSTRUCTION from the paths module
        # attribute, so a test (or a future override) that rebinds
        # ``paths.DATASETS_DIR`` before building the storage owns the shelf.
        self._root = Path(root) if root is not None else paths.DATASETS_DIR

    @property
    def root(self) -> Path:
        return self._root

    def _ensure_root(self) -> None:
        """The catalogue is created on first access (spec «Каталог хранилища
        SHALL создаваться при первом обращении»)."""
        self._root.mkdir(parents=True, exist_ok=True)

    def document_path(self, dataset_id: str) -> Path:
        """``<dataset_id>.json`` under the root, after id validation — the
        ONLY place a storage path is built, so an id can never steer it
        outside the catalogue."""
        if not is_valid_dataset_id(dataset_id):
            raise ValueError(f"dataset id {dataset_id!r} is not a safe file name")
        return self._root / f"{dataset_id}{DATASET_SUFFIX}"

    def meta_path(self, dataset_id: str) -> Path:
        self.document_path(dataset_id)  # validates the id first
        return self._root / f"{dataset_id}{DATASET_META_SUFFIX}"

    def spells_path(self, dataset_id: str) -> Path:
        self.document_path(dataset_id)  # validates the id first
        return self._root / f"{dataset_id}{DATASET_SPELLS_SUFFIX}"

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """tmp + rename inside the target directory (design Д4). On any
        failure the tmp is removed and the previous target bytes stay."""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        try:
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    # ── write ────────────────────────────────────────────────────────────────

    def save(self, dataset_id: str, content: str, meta: DatasetMeta) -> None:
        """Persist the pair for ``dataset_id``, overwriting any previous
        shelf (the confirm/SRD-protection rules live in the service). The
        document is replaced first, the sidecar after it: a torn write can
        only leave a fresh document with a stale sidecar, which the tolerant
        reader still lists."""
        document = self.document_path(dataset_id)
        self._ensure_root()
        self._atomic_write(document, content)
        self._atomic_write(
            self.meta_path(dataset_id),
            json.dumps(
                {
                    "source": meta.source.value,
                    "imported_at": meta.imported_at,
                    "sha256": meta.sha256,
                    "check_errors": meta.check_errors,
                },
                ensure_ascii=False,
            ),
        )

    def save_spell_slugs(self, dataset_id: str, slugs: tuple[str, ...]) -> None:
        """Persist the SRD spell-slug list beside its official set (design Д5:
        the lists download WITH the SRD; absence only skips the slug check)."""
        self._ensure_root()
        self._atomic_write(
            self.spells_path(dataset_id), "\n".join(slugs) + "\n" if slugs else ""
        )

    def set_check_errors(self, dataset_id: str, errors: int) -> None:
        """Re-write the sidecar with the validator's fresh error count
        (spec: the list shows «число ошибок последней проверки»). A missing
        shelf raises through the id-validation path — callers run this only
        for listed datasets."""
        existing = self.load_meta(dataset_id)
        if existing is None:
            raise KeyError(f"dataset {dataset_id!r} is not in the storage")
        self._atomic_write(
            self.meta_path(dataset_id),
            json.dumps(
                {
                    "source": existing.source.value,
                    "imported_at": existing.imported_at,
                    "sha256": existing.sha256,
                    "check_errors": errors,
                },
                ensure_ascii=False,
            ),
        )

    # ── read ─────────────────────────────────────────────────────────────────

    def load_content(self, dataset_id: str) -> str | None:
        """The stored document text, ``None`` when the shelf is absent."""
        document = self.document_path(dataset_id)
        return document.read_text(encoding="utf-8") if document.is_file() else None

    def load_meta(self, dataset_id: str) -> DatasetMeta | None:
        """The sidecar as data, ``None`` when absent; damaged text degrades
        to the tolerant defaults (see :func:`_read_meta`)."""
        meta_path = self.meta_path(dataset_id)
        if not meta_path.is_file():
            return None
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _LOGGER.warning("Ignoring damaged dataset sidecar %s", meta_path)
            raw = None
        return _read_meta(raw)

    def load_spell_slugs(self, dataset_id: str) -> tuple[str, ...] | None:
        """The slug list, ``None`` when the file never arrived (the slug
        checks then skip silently — design Д5)."""
        spells = self.spells_path(dataset_id)
        if not spells.is_file():
            return None
        return tuple(line.strip() for line in spells.read_text(encoding="utf-8").splitlines() if line.strip())

    def list_datasets(self) -> list[StoredDataset]:
        """Every shelf, ordered by id — titles from the documents themselves
        (spec «опознаваемый по идентификатору и заголовку из самого файла»),
        sources and counts from the sidecars. A shelf whose document does not
        parse still appears under its file name; the meta files never list as
        datasets of their own."""
        self._ensure_root()
        entries: list[StoredDataset] = []
        for document in sorted(self._root.glob(f"*{DATASET_SUFFIX}")):
            if document.name.endswith(DATASET_META_SUFFIX):
                continue
            dataset_id = document.name[: -len(DATASET_SUFFIX)]
            entries.append(
                StoredDataset(
                    dataset_id=dataset_id,
                    title=_read_title(document),
                    meta=self.load_meta(dataset_id) or DatasetMeta(
                        source=DatasetSource.HOMEBREW, imported_at="", sha256=""
                    ),
                )
            )
        return entries


def _read_meta(raw: object) -> DatasetMeta:
    """One sidecar as data, forgiving (design Д4 leaves the pair formats to
    this layer; a crash between the two atomic writes or a hand-edit must
    degrade, never vanish): an unknown/absent source reads as homebrew, an
    off-type check count as «not checked», dates as the empty string."""
    if not isinstance(raw, dict):
        return DatasetMeta(source=DatasetSource.HOMEBREW, imported_at="", sha256="")
    source_raw = raw.get("source")
    try:
        source = DatasetSource(source_raw)
    except ValueError:
        source = DatasetSource.HOMEBREW
    imported_at = raw.get("imported_at")
    sha256 = raw.get("sha256")
    check_errors = raw.get("check_errors")
    return DatasetMeta(
        source=source,
        imported_at=imported_at if isinstance(imported_at, str) else "",
        sha256=sha256 if isinstance(sha256, str) else "",
        check_errors=check_errors
        if isinstance(check_errors, int) and not isinstance(check_errors, bool)
        else None,
    )


def _read_title(document: Path) -> str:
    """The document's own text ``title``; a file that does not parse or has
    no title keeps its shelf listed under the file-name id. The reading rule
    itself is the domain's — the list and the import name titles alike."""
    dataset_id = document.name[: -len(DATASET_SUFFIX)]
    try:
        data = json.loads(document.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dataset_id
    return dataset_title_from_document(data, dataset_id)
