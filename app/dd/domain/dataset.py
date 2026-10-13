"""The module's dataset domain (add-dnd-module-foundation, task 3.1; design Д4).

Pure data, no Qt, no I/O, no network: what a stored dataset IS (its source,
its sidecar record, the storage list entry), the dataset-identifier rule the
file name must obey, and the frozen outcome contracts the library service
answers with. The file pair itself (``<id>.json`` + ``<id>.meta.json``) is
the infrastructure's business; this module only names what the pair carries.

The dataset identifier is the LSS reference namespace (``srd-2014:Darkvision``
-style prefixes): the storage file name is DERIVED from it, so the character
set is validated before any path is built — a file name is never trusted to
a foreign document (design Д4: «имя файла выводится из id файла после
валидации формата имени»).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

#: The ids the official SRD export files carry in their own ``id`` field
#: (the LSS reference prefixes every LSS document uses); the library's
#: auto-download, its document-id gate and the union of the downloaded
#: spell-slug lists key off them.
SRD_2014_DATASET_ID = "srd-2014"
SRD_2024_DATASET_ID = "srd-2024"

#: The one dataset-id grammar the storage accepts as a file name: lowercase
#: ASCII alphanumeric plus ``.``, ``-`` and ``_``, starting and ending with a
#: non-dot character, at most 64 characters. The first/last rule alone kills
#: ``""``, ``.``, ``..``, hidden-dot names and trailing separators; a dot in
#: the middle (``my-pack.v2``) is legal. Path separators can never occur.
_DATASET_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")


def is_valid_dataset_id(dataset_id: str) -> bool:
    """True when ``dataset_id`` may become a storage file name (design Д4).

    The rule is deliberately stricter than the filesystem: the id arrives
    from an imported document and is the ONLY thing the file name is built
    from, so anything that could steer the path elsewhere (separators, ``..``)
    or look like a sibling file (leading/trailing dot) is refused outright.
    """
    return len(dataset_id) <= 64 and _DATASET_ID_RE.match(dataset_id) is not None


class DatasetSource(str, Enum):
    """Where a stored dataset came from (design Д4 sidecar field).

    ``SRD`` marks the official Long Story Short exports the library
    auto-downloads — they are protected from import overwrite; ``HOMEBREW``
    is everything the master imported.
    """

    SRD = "srd"
    HOMEBREW = "homebrew"


@dataclass(frozen=True)
class DatasetMeta:
    """The sidecar record of one stored dataset (design Д4).

    ``source`` is the protection flag (SRD files never take an overwrite);
    ``imported_at`` is the ISO date of the write; ``sha256`` fingerprints the
    exact bytes stored; ``check_errors`` is the validator's error count from
    the last check — ``None`` while the file has never been checked.
    """

    source: DatasetSource
    imported_at: str
    sha256: str
    check_errors: int | None = None


@dataclass(frozen=True)
class StoredDataset:
    """One storage-shelf entry for the module's screens (spec «Список
    хранилища … доступен экрану модуля без сети»): the id the game lists
    connect to, the title read from the dataset file itself, and the sidecar.
    """

    dataset_id: str
    title: str
    meta: DatasetMeta


# ── outcome contracts of the library operations (tasks 3.1/3.3) ─────────────


class StoreStatus(Enum):
    """The five answers a store request can get (task 3.1 check «замена с
    подтверждением на уровне сервиса, защита SRD»)."""

    SAVED = "saved"
    REPLACED = "replaced"
    #: The id already lies in the storage as a homebrew file and the caller
    #: did not yet bring the user's confirmation (spec: «заменять только
    #: после подтверждения»).
    NEEDS_CONFIRMATION = "needs_confirmation"
    #: The id belongs to a protected official SRD file — no confirmation buys
    #: an overwrite (spec «SRD защищён от перезаписи»).
    SRD_PROTECTED = "srd_protected"
    #: The document is not a readable JSON object or carries no text ``id``.
    INVALID_CONTENT = "invalid_content"


@dataclass(frozen=True)
class StoreOutcome:
    """Result of one store request: status, the id read from the document
    (``None`` when the document itself was unreadable), and the Russian
    sentence for the user (empty on a clean save/replace)."""

    status: StoreStatus
    dataset_id: str | None
    title: str
    message: str = ""

    @property
    def stored(self) -> bool:
        """The storage now holds exactly the submitted content."""
        return self.status in (StoreStatus.SAVED, StoreStatus.REPLACED)


class DownloadStatus(Enum):
    """Per-dataset answers of the official-datasets bootstrap (task 3.3)."""

    DOWNLOADED = "downloaded"
    #: The file already lay in the storage — no request was made for it
    #: (spec «Повторный запуск не качает», «не перезаписывать без запроса»).
    ALREADY_PRESENT = "already_present"
    #: The fetch or the fetched content failed; ``message`` carries the
    #: Russian reason, the storage stayed as it was for this id.
    FAILED = "failed"


@dataclass(frozen=True)
class OfficialDatasetOutcome:
    """One row of the bootstrap report (id, human caption, status, reason)."""

    dataset_id: str
    caption: str
    status: DownloadStatus
    message: str = ""


@dataclass(frozen=True)
class OfficialDatasetsResult:
    """The whole official-datasets run: per-dataset rows plus the Russian
    summary the façade prints. ``ok`` is False when any row failed — a row
    that was already present is success, not a failure."""

    items: "tuple[OfficialDatasetOutcome, ...]"

    @property
    def ok(self) -> bool:
        return all(item.status is not DownloadStatus.FAILED for item in self.items)

    @property
    def all_present(self) -> bool:
        """Nothing happened and nothing failed — the routine repeat state
        the façade keeps silent (the game open needs no box for «already
        there»)."""
        return all(item.status is DownloadStatus.ALREADY_PRESENT for item in self.items)

    @property
    def summary(self) -> str:
        """The Russian sentence for the user — success names what is now in
        the storage, failure names each failed set with its reason."""
        failed = [item for item in self.items if item.status is DownloadStatus.FAILED]
        if failed:
            parts = "; ".join(f"{item.caption}: {item.message}" for item in failed)
            return f"Не удалось загрузить официальные наборы SRD. {parts}."
        loaded = [item.caption for item in self.items if item.status is DownloadStatus.DOWNLOADED]
        if loaded:
            return (
                "Официальные наборы SRD загружены в хранилище: "
                + ", ".join(loaded)
                + "."
            )
        return "Официальные наборы SRD уже в хранилище — сеть не требовалась."


def dataset_title_from_document(data: object, fallback: str) -> str:
    """The title printed for a document: its own text ``name`` — the field
    the LSS artefact files and the wizard-dataset example actually carry —
    else the legacy ``title``, else the fallback (the id / caption). Reading
    is forgiving on purpose — the title only labels screens; whether the file
    is importable at all is the validator's decision (group 4), not the
    reader's."""
    if isinstance(data, dict):
        for key in ("name", "title"):
            title = data.get(key)
            if isinstance(title, str) and title.strip():
                return title.strip()
    return fallback
