"""The file-import and re-check flow of the dataset library (task 5.1;
design Д6/Д7; spec dnd-dataset-library «Импорт пользовательского датасета
файлом», dnd-dataset-validator «Порог импорта»).

One decision tree, one home: the sheet (and any future caller) hands the
service the document text and learns the branch to show — never re-deciding
the order of license/validation/store rules at a usage site. The rules,
in the spec's order:

* the file first passes the FULL validator — licence, shape and the
  cross-field LSS list. Link resolution runs over every dataset the game
  connects to (spec: «по всем подключённым наборам хранилища, а не только
  по проверяемому файлу»), a same-id shelf is excluded from the corpus (it
  IS the document being checked, in its old bytes). The spell-slug
  dictionary the slug check reads is the SRD lists PLUS the slugs of every
  grimoire the game connects to (add-dnd-game-face task 4.3, spec
  «Слаги гримуаров расширяют словарь валидатора»);
* errors refuse the import entirely — no shelf was written when this returns
  (the store is reached only past the threshold);
* warnings let the import through, the report accompanies it for display;
* the store rules (id grammar, SRD protection, replace-only-after-
  confirmation) are the library service's (:meth:`DatasetLibraryService
  .store_dataset`) — this flow passes the confirmation flag through and
  relays the branch;
* after a successful save the sidecar takes the fresh error count, so the
  list's «число ошибок последней проверки» is true for imported shelves too
  (:meth:`DatasetStorage.set_check_errors` is the storage's own stamp).

The re-check runs the same validator over a shelf already in storage (source
taken from the sidecar: an official set is checked with official-class spell
lists, design Д7) and stamps the outcome into the sidecar. Qt-free, network-
free: the corpus reads are files and one settings row through the injected
connections service; the caller supplies the session lock by running the
coroutine through it (the sheet starts these on ``run_locked``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from app.dd.domain.dataset import (
    SRD_2014_DATASET_ID,
    SRD_2024_DATASET_ID,
    DatasetSource,
    StoreStatus,
)
from app.dd.domain.lss_checks import ConnectedDataset
from app.dd.domain.validation_report import ValidationReport

if TYPE_CHECKING:
    from app.dd.application.dataset_connections_service import (
        DatasetConnectionsService,
    )
    from app.dd.application.dataset_library_service import DatasetLibraryService
    from app.dd.application.dataset_validator_service import DatasetValidatorService
    from app.dd.application.grimoire_index_service import GrimoireIndexService
    from app.dd.infrastructure.dataset_storage import DatasetStorage


class DatasetImportStatus(Enum):
    """The three answers of one import request."""

    #: The document lies in the storage (fresh save or confirmed replacement);
    #: ``report`` may still carry warnings the screen must list (spec
    #: scenario «Импорт с предупреждениями»).
    STORED = "stored"
    #: The id already sits in the storage as a homebrew shelf and no
    #: confirmation arrived yet — the screen asks, then re-requests with
    #: ``confirmed=True`` (spec: «заменять только после подтверждения»).
    NEEDS_CONFIRMATION = "needs_confirmation"
    #: Nothing was stored: the validator's errors, the SRD protection or an
    #: unshelv-able document. ``report`` carries the check findings when the
    #: validator refused; ``message`` carries the store's Russian sentence
    #: when the shelf rules refused.
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DatasetImportOutcome:
    """One import answer: the branch, the check report (when one ran), the
    id/title read from the document and the Russian sentence for the screen."""

    status: DatasetImportStatus
    dataset_id: str | None = None
    title: str = ""
    message: str = ""
    report: ValidationReport | None = None
    replaced: bool = False


class DatasetImportService:
    """Import-with-validation and re-check over the injected collaborators."""

    def __init__(
        self,
        library: "DatasetLibraryService",
        connections: "DatasetConnectionsService",
        validator: "DatasetValidatorService",
        storage: "DatasetStorage",
        grimoires: "GrimoireIndexService | None" = None,
    ) -> None:
        self._library = library
        self._connections = connections
        self._validator = validator
        self._storage = storage
        # The grimoire half of the spell-slug dictionary (task 4.3, spec
        # «Слаги гримуаров расширяют словарь валидатора»): a slug the game
        # loaded from its own spell file is as known as one the SRD lists
        # carry. Composed without it (a partial stack, a unit test) the
        # dictionary is exactly the SRD lists of the pre-grimoire flow.
        self._grimoires = grimoires

    # ── import (task 5.1) ─────────────────────────────────────────────────────

    async def import_dataset(
        self, content: str, *, confirmed: bool = False
    ) -> DatasetImportOutcome:
        """Check-then-shelve one document text (module docstring for rules).

        The validation ALWAYS precedes any store call, so the spec's «хранилище
        не меняется» on errors is structural, not a cleanup: nothing below the
        threshold ever reaches the storage. A NEEDS_CONFIRMATION request that
        comes back ``confirmed=True`` re-checks the same bytes — the check is
        deterministic, the honest cost of never shelving unchecked content."""
        own_id = _document_id(content)
        report = self._validator.validate(
            content,
            connected=await self._corpus(exclude_id=own_id),
            spell_slugs=await self._slug_dictionary(),
        )
        if not report.import_allowed:
            # Licence absence, shape or cross-field errors — the report IS
            # the refusal text; the storage has not been touched.
            return DatasetImportOutcome(
                status=DatasetImportStatus.BLOCKED,
                dataset_id=own_id,
                report=report,
            )
        store = self._library.store_dataset(content, allow_replace=confirmed)
        if store.status is StoreStatus.NEEDS_CONFIRMATION:
            return DatasetImportOutcome(
                status=DatasetImportStatus.NEEDS_CONFIRMATION,
                dataset_id=store.dataset_id,
                title=store.title,
                message=store.message,
                report=report,
            )
        if not store.stored:
            # SRD_PROTECTED or INVALID_CONTENT (e.g. an id the schema lets
            # through but the file-name grammar refuses) — Russian sentence
            # from the shelf rules, storage byte-identical.
            return DatasetImportOutcome(
                status=DatasetImportStatus.BLOCKED,
                dataset_id=store.dataset_id,
                title=store.title,
                message=store.message,
                report=report,
            )
        # Shelved: the sidecar learns the fresh error count (zero below the
        # threshold — the warnings stay visible only in the shown report).
        self._storage.set_check_errors(store.dataset_id or "", len(report.errors))
        return DatasetImportOutcome(
            status=DatasetImportStatus.STORED,
            dataset_id=store.dataset_id,
            title=store.title,
            report=report,
            replaced=store.status is StoreStatus.REPLACED,
        )

    # ── re-check (task 5.2 «кнопки … повторной проверки») ─────────────────────

    async def recheck(self, dataset_id: str) -> ValidationReport | None:
        """Validate one stored shelf and stamp its sidecar; ``None`` when
        the shelf left the storage between the list click and this moment —
        the screen then says so and never writes a sidecar for a ghost."""
        content = self._storage.load_content(dataset_id)
        if content is None:
            return None
        meta = self._storage.load_meta(dataset_id)
        report = self._validator.validate(
            content,
            connected=await self._corpus(exclude_id=dataset_id),
            spell_slugs=await self._slug_dictionary(),
            # An official set is checked with its own classes covering the
            # spell lists, the way the LSS built-in database does (group 4's
            # source semantics); a shelf without a readable sidecar checks
            # as homebrew (the storage's own tolerant default).
            source=meta.source if meta is not None else DatasetSource.HOMEBREW,
        )
        if meta is not None:
            # The stamp re-writes the sidecar and needs its other fields.
            # A bare document without one (a torn save's legacy: the storage
            # writes the document first) is still LISTED — the list is
            # document-driven with a placeholder sidecar — but has nothing
            # to stamp: it checks honestly and simply carries no stamp,
            # instead of raising through the storage's ghost guard.
            self._storage.set_check_errors(dataset_id, len(report.errors))
        return report

    # ── shared reading doors (add-dnd-lss-generation task 7.1) ───────────────

    async def validation_corpus(
        self, exclude_id: str | None = None
    ) -> tuple[ConnectedDataset, ...]:
        """The game's connected shelves, parsed for link resolution — the
        SAME corpus this service checks imports with, offered as a public
        door so the generation round validates against exactly the corpus
        the acceptance door will use (one knowledge, one place)."""
        return await self._corpus(exclude_id=exclude_id)

    async def slug_dictionary(self) -> tuple[str, ...] | None:
        """The full known spell-slug dictionary (SRD lists plus the game's
        connected grimoires) — the same answer the import check gives, for
        the generation round and its preview (task 7.1)."""
        return await self._slug_dictionary()

    # ── shared reading helpers ────────────────────────────────────────────────

    async def _corpus(
        self, exclude_id: str | None = None
    ) -> tuple[ConnectedDataset, ...]:
        """The game's connected shelves, parsed for link resolution. A
        missing document, unreadable JSON or a non-object root contributes
        nothing (the links then simply resolve without that set — the
        validator's own corpus tolerates absent neighbours); ``exclude_id``
        drops the very shelf the checked document IS."""
        corpus: list[ConnectedDataset] = []
        for dataset_id in await self._connections.connections():
            if dataset_id == exclude_id:
                continue
            content = self._storage.load_content(dataset_id)
            if content is None:
                continue
            try:
                document = json.loads(content)
            except json.JSONDecodeError:
                continue
            if not isinstance(document, dict):
                continue
            meta = self._storage.load_meta(dataset_id)
            corpus.append(
                ConnectedDataset(
                    dataset_id=dataset_id,
                    source=(
                        meta.source
                        if meta is not None
                        else DatasetSource.HOMEBREW
                    ),
                    document=document,
                )
            )
        return tuple(corpus)

    def _spell_slugs(self) -> tuple[str, ...] | None:
        """The union of the downloaded SRD spell-slug lists (design Д5);
        ``None`` when neither list arrived — exactly the slug check skips
        then, as the LSS documentation prescribes."""
        union: set[str] = set()
        for srd_id in (SRD_2014_DATASET_ID, SRD_2024_DATASET_ID):
            stored = self._library.get_spell_slugs(srd_id)
            if stored:
                union.update(stored)
        return tuple(sorted(union)) if union else None

    async def _slug_dictionary(self) -> tuple[str, ...] | None:
        """The full «known spell slug» dictionary of the check: the SRD lists
        PLUS the slugs every grimoire connected to THIS game declares (task
        4.3, spec scenario «Объявленное и загруженное — легально»). Absent
        lists and absent grimoires (or a module composed without the grimoire
        half) keep the SRD-only answer, ``None`` included — the slug check
        skips exactly when nothing is known."""
        srd = self._spell_slugs()
        if self._grimoires is None:
            return srd
        loaded = await self._grimoires.spell_slugs()
        if not loaded:
            return srd
        if srd is None:
            return tuple(sorted(loaded))
        return tuple(sorted(set(srd) | set(loaded)))


def _document_id(content: str) -> str | None:
    """The document's own id for corpus exclusion, read forgivingly — a file
    that does not parse or names no text id excludes nothing and gets its
    verdict from the validator's INVALID_JSON error instead."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        dataset_id = data.get("id")
        if isinstance(dataset_id, str):
            return dataset_id
    return None
