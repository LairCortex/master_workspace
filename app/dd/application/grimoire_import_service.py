"""The grimoire import flow (add-dnd-game-face, task 4.2; design Д8;
spec dnd-grimoire-import «Гримуарный файл проходит проверку с отчётом и
ложится в глобальное хранилище»).

One decision tree, one home — the same shape the dataset import flow has, so
the master meets one posture for both halves of the module's global library:

* the bytes first pass the DOMAIN check (:func:`app.dd.domain.grimoire.
  parse_grimoire` — Foundry has no public spell schema, design Д8);
* errors refuse the import entirely and the storage is never reached, so the
  spec's «в хранилище ничего не добавилось» is structural, not a cleanup;
* warnings let the import through and travel with it for display (the same
  error/warning threshold the datasets keep);
* the identifier is the file's own (``id``/``_id``/``slug`` of the document) in
  the shelf's lower spelling, and is validated against the safe-file-name
  grammar before the storage is asked; a document naming nothing earns a
  content-addressed id, deterministic for the same bytes and therefore
  re-importable as a replacement of its own shelf;
* an id whose shelf already exists is replaced ONLY on the caller's
  confirmation (spec scenario «Замена подтверждается») — without it the old
  bytes are untouched; renaming the document simply means a new id, so a
  rename never silently overwrites another master's file;
* a fresh id is saved at once.

There is no SRD half to protect here: the grimoire library holds nothing but
the masters' own files, so the dataset flow's SRD branch has no counterpart.

Qt-free, network-free: the caller (a screen, or a test) picks the file, shows
the report, and re-requests with ``confirmed=True`` after the master's yes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Sequence

from app.dd.domain.dataset import is_valid_dataset_id
from app.dd.domain.grimoire import parse_grimoire
from app.dd.domain.validation_report import ValidationReport

if TYPE_CHECKING:
    from app.dd.infrastructure.grimoire_storage import GrimoireStorage

#: Prefix of the content-addressed id a document naming no own identifier
#: earns; the hex half is grammar-safe by construction, so the fallback can
#: never produce an unusable file name.
ANONYMOUS_GRIMOIRES_PREFIX = "grimoire-"
#: Hex characters of the content fingerprint in that id (12 of 64: collision-
#: free at the scale of a master's library, short enough to read in a list).
_ANONYMOUS_FINGERPRINT_CHARS = 12


class GrimoireImportStatus(Enum):
    """The three answers of one grimoire import request."""

    #: The file lies in the storage (fresh save or confirmed replacement);
    #: ``report`` may still carry the warnings the screen must list.
    STORED = "stored"
    #: The id already has a shelf and no confirmation arrived yet — the screen
    #: asks, then re-requests with ``confirmed=True`` (spec «Замена
    #: подтверждается»).
    NEEDS_CONFIRMATION = "needs_confirmation"
    #: Nothing was stored: the parser's errors (unreadable bytes, a structure
    #: outside the format, an empty spell list) or an id that cannot become a
    #: file name.
    BLOCKED = "blocked"


@dataclass(frozen=True)
class GrimoireImportOutcome:
    """One import answer: the branch, the id and title the file carries, the
    number of spells read, the Russian sentence for the screen and the check
    report (``None`` only when nothing was checked at all — never today)."""

    status: GrimoireImportStatus
    grimoire_id: str | None = None
    title: str = ""
    spell_count: int = 0
    message: str = ""
    report: ValidationReport | None = None
    replaced: bool = False


class GrimoireImportService:
    """Check-then-shelve one Foundry spell file over the global shelf."""

    def __init__(self, storage: "GrimoireStorage") -> None:
        self._storage = storage

    def import_grimoire(
        self,
        content: str,
        *,
        confirmed: bool = False,
        srd_slugs: Sequence[str] | None = None,
    ) -> GrimoireImportOutcome:
        """Check-then-shelve one document text (module docstring for rules).

        ``srd_slugs`` is the public SRD spell-slug list the caller already
        holds (the same union the dataset validator reads); with it the report
        flags the grimoire's SRD crossings, without it that one check is
        skipped — the LSS posture of the dataset validator. A confirmation
        re-request re-checks the very bytes it brings, so the flow never
        shelves unchecked content."""
        parse = parse_grimoire(content, srd_slugs)
        report = parse.report
        if not report.import_allowed:
            return GrimoireImportOutcome(
                status=GrimoireImportStatus.BLOCKED,
                grimoire_id=parse.document_id,
                title=parse.title,
                spell_count=len(parse.spells),
                report=report,
            )
        grimoire_id = _shelf_id(parse.document_id, content)
        if not is_valid_dataset_id(grimoire_id):
            return GrimoireImportOutcome(
                status=GrimoireImportStatus.BLOCKED,
                grimoire_id=grimoire_id,
                title=parse.title,
                spell_count=len(parse.spells),
                report=report,
                message=(
                    f"Идентификатор «{grimoire_id}» не может именем файла — "
                    "гримуар не сохранён."
                ),
            )
        title = parse.title or grimoire_id
        existing = self._storage.exists(grimoire_id)
        if existing and not confirmed:
            return GrimoireImportOutcome(
                status=GrimoireImportStatus.NEEDS_CONFIRMATION,
                grimoire_id=grimoire_id,
                title=title,
                spell_count=len(parse.spells),
                report=report,
                message=(
                    f"Гримуар «{title}» уже в хранилище — заменить его можно "
                    "только с вашим подтверждением."
                ),
            )
        self._storage.save(grimoire_id, content)
        return GrimoireImportOutcome(
            status=GrimoireImportStatus.STORED,
            grimoire_id=grimoire_id,
            title=title,
            spell_count=len(parse.spells),
            report=report,
            replaced=existing,
        )


def _shelf_id(document_id: str | None, content: str) -> str:
    """The storage name for one imported document.

    A Foundry document names itself with a 16-character base62 ``_id``
    (``Kn3v7dQm1xT0aBcD``) while the shelf grammar (the dataset storage's own,
    reused here: design Д8 keeps both halves of the library on one shelf
    discipline) knows lowercase only — so the candidate is read in its lower
    spelling, which is the SAME identity, just legal as a file name. The
    collapse is case-only and therefore deterministic: the same file re-imports
    as the replacement of its own shelf (the spec's confirmation flow guards
    the one collision case two ids differing only in case would open). A name
    the grammar still refuses (Cyrillic, spaces, separators) is NOT quietly
    replaced by a hash — the caller reports it and the master renames the
    document. A document naming nothing at all earns the content-addressed id.
    """
    if document_id is None:
        return _anonymous_id(content)
    candidate = document_id.strip().lower()
    return candidate if is_valid_dataset_id(candidate) else document_id


def _anonymous_id(content: str) -> str:
    """The content-addressed identity of a spell document that names none:
    the same bytes always earn the same id (a re-import is therefore a
    replacement with confirmation, never a silent twin), while a real edit
    opens a new shelf instead of silently overwriting another file."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{ANONYMOUS_GRIMOIRES_PREFIX}{digest[:_ANONYMOUS_FINGERPRINT_CHARS]}"
