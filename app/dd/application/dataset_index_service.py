"""The in-memory index of the game's connected datasets (add-dnd-game-face,
task 3.1; design Д5).

The dataset file stays the truth; this service is the read cache every
surface (search, reference sheet, the later mention/pin paths) consults
instead of the disk. The shape is the design's: a per-section map keyed by
the pair ``(dataset_id, entry_id)`` — the pair is the entity identity forever
(spec «шесть справочных типов с парным идентификатором»), so same-slug
records from two connected sets sit side by side, never merged.

Invalidation is the file's own content hash: before every read the service
re-hash the stored bytes (files are far below a megabyte — the design's
«полных переразборов не боятся») and reparses only the datasets whose digest
moved, including a file edited outside the app between two reads (task 3.1's
«правка файла на лету»). An empty connection list is the empty index at zero
cost; a dataset whose bytes no longer parse (or vanished from the storage)
indexes as no records — the validator's report, not the index's, is where a
broken file gets its voice.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.domain.lss_checks import SECTIONS
from app.dd.infrastructure.dataset_storage import DatasetStorage


@dataclass(frozen=True)
class DatasetEntry:
    """One indexed record: its pair identity, the display name read from the
    record (``label``, the id as the honest fallback) and the parsed record
    body for whatever a surface assembles from it."""

    dataset_id: str
    entry_id: str
    name: str
    record: Mapping[str, Any]


@dataclass(frozen=True)
class _DatasetParse:
    """The cached parse of one dataset file: the digest the cache was built
    from plus the section → entries split (entry order is the file's own)."""

    digest: str
    sections: Mapping[str, tuple[DatasetEntry, ...]]


@dataclass(frozen=True)
class IndexSnapshot:
    """One immutable read of the whole index: connected sets in list order
    (only those whose bytes parsed), their storage titles (the origin label),
    the per-section per-dataset entries and the spell-slug lists. Everything
    a surface assembles — async or not — reads through this value, so one
    frame of search results cannot straddle two reconciliations."""

    ids: tuple[str, ...]
    titles: Mapping[str, str]
    sections: Mapping[str, Mapping[str, tuple[DatasetEntry, ...]]]
    slugs: Mapping[str, tuple[str, ...]]

    def entries(self, section: str, dataset_id: str) -> tuple[DatasetEntry, ...]:
        """The set's records of one section (empty when either is absent)."""
        return self.sections.get(section, {}).get(dataset_id, ())

    def entry(
        self, section: str, dataset_id: str, entry_id: str
    ) -> DatasetEntry | None:
        """One record addressed by its pair; ``None`` when the set is not
        connected (or unreadable), the section or the id absent."""
        for known in self.entries(section, dataset_id):
            if known.entry_id == entry_id:
                return known
        return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_dataset(
    content: str, dataset_id: str
) -> dict[str, tuple[DatasetEntry, ...]]:
    """Split one dataset file's text into per-section entries.

    Tolerant by contract: bytes that do not parse as a JSON object index as
    nothing (the file's owner — the validator — explains it to the master);
    a section that is not a list, an entry that is not an object and an
    entry without a usable string id are skipped one by one, the healthy
    records of the same file still index."""
    empty = {section: () for section in SECTIONS}
    try:
        document = json.loads(content)
    except json.JSONDecodeError:
        return empty
    if not isinstance(document, dict):
        return empty
    parsed: dict[str, tuple[DatasetEntry, ...]] = {}
    for section in SECTIONS:
        raw = document.get(section)
        entries: list[DatasetEntry] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                entry_id = item.get("id")
                if not isinstance(entry_id, str) or not entry_id:
                    continue
                label = item.get("label")
                entries.append(
                    DatasetEntry(
                        dataset_id=dataset_id,
                        entry_id=entry_id,
                        name=label if isinstance(label, str) and label else entry_id,
                        record=item,
                    )
                )
        parsed[section] = tuple(entries)
    return parsed


class DatasetIndexService:
    """The per-game read cache over the connected datasets.

    Stateless besides the cache: the connection list and the files stay the
    truth, every async read starts by reconciling the cache with them
    (design Д5) and answers from the resulting :class:`IndexSnapshot`. The
    protocol's SYNC doors (``card_source``, ``resolve_mention`` — the kernel
    calls them without a loop) read :meth:`snapshot_now` — the last snapshot
    built; every flow that can click (search rows, later reference-sheet
    rows) is preceded by an async read, so the snapshot is fresh where the
    clicks come from, and a never-reconciled index honestly answers empty.

    The cache is process-local and keyed per dataset id — two games sharing
    the global library share files, never entries."""

    def __init__(
        self,
        connections: DatasetConnectionsService,
        storage: DatasetStorage,
    ) -> None:
        self._connections = connections
        self._storage = storage
        self._cache: dict[str, _DatasetParse] = {}
        self._slug_cache: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._snapshot: IndexSnapshot = IndexSnapshot(
            ids=(), titles={}, sections={}, slugs={}
        )

    # ── reads (the surfaces' door) ────────────────────────────────────────────

    async def snapshot(self) -> IndexSnapshot:
        """Reconcile with the connection list and the files, answer the
        fresh snapshot."""
        await self._reconcile()
        return self._snapshot

    def snapshot_now(self) -> IndexSnapshot:
        """The last snapshot WITHOUT reconciling — the sync door the
        protocol's non-async calls read (docstring of the class)."""
        return self._snapshot

    async def entries(self, section: str) -> tuple[DatasetEntry, ...]:
        """Every connected set's records of one section, connection order
        first and file order inside each set (deterministic, spec-friendly:
        the two same-slug records are two rows, each naming its set)."""
        snap = await self.snapshot()
        merged: list[DatasetEntry] = []
        for dataset_id in snap.ids:
            merged.extend(snap.sections.get(section, {}).get(dataset_id, ()))
        return tuple(merged)

    async def spell_slugs(self) -> tuple[tuple[str, str], ...]:
        """``(dataset_id, slug)`` pairs of every connected set that carries
        a public spell-slug list (the SRD sets the library downloaded one
        with; task 3.2 spells: slug+set is the key, the two editions are two
        entities)."""
        snap = await self.snapshot()
        return tuple(
            (dataset_id, slug)
            for dataset_id in snap.ids
            for slug in snap.slugs.get(dataset_id, ())
        )

    # ── reconciliation (the design Д5 digest discipline) ─────────────────────

    async def _reconcile(self) -> None:
        """Bring the cache to the connection list and the files' current
        bytes, then rebuild the snapshot. A set the game disconnected, a
        document that vanished, and a slug file that disappeared all drop
        out; a digest that moved (including an on-disk edit between two
        reads) reparses just that file."""
        live = await self._connections.connections()
        live_set = set(live)
        for dataset_id in list(self._cache):
            if dataset_id not in live_set:
                del self._cache[dataset_id]
        for dataset_id in live:
            try:
                content = self._storage.load_content(dataset_id)
            except ValueError:
                # A stored connection id that is not a safe file name (a
                # hand-edited or corrupted settings row): the id names no
                # file by construction — the vanished-set posture, never a
                # raised error at the reader (protocol warm: «failures are
                # the source's own silence»).
                content = None
            if content is None:
                self._cache.pop(dataset_id, None)
                continue
            digest = _digest(content)
            cached = self._cache.get(dataset_id)
            if cached is not None and cached.digest == digest:
                continue
            self._cache[dataset_id] = _DatasetParse(
                digest=digest, sections=parse_dataset(content, dataset_id)
            )
        for dataset_id in list(self._slug_cache):
            if dataset_id not in live_set:
                del self._slug_cache[dataset_id]
        for dataset_id in live:
            try:
                text = self._storage.load_spell_slugs(dataset_id)
            except ValueError:
                # same id-corruption posture as the document read above
                text = None
            if text is None:
                self._slug_cache.pop(dataset_id, None)
                continue
            digest = _digest("\n".join(text))
            cached = self._slug_cache.get(dataset_id)
            if cached is None or cached[0] != digest:
                self._slug_cache[dataset_id] = (digest, tuple(text))
        titles = {
            status.dataset_id: status.title
            for status in await self._connections.statuses()
            if status.present
        }
        parsed_ids = tuple(dataset_id for dataset_id in live if dataset_id in self._cache)
        sections: dict[str, dict[str, tuple[DatasetEntry, ...]]] = {}
        for section in SECTIONS:
            per_dataset = {
                dataset_id: self._cache[dataset_id].sections[section]
                for dataset_id in parsed_ids
                if self._cache[dataset_id].sections.get(section)
            }
            if per_dataset:
                sections[section] = per_dataset
        self._snapshot = IndexSnapshot(
            ids=parsed_ids,
            titles=titles,
            sections=sections,
            slugs={
                dataset_id: self._slug_cache[dataset_id][1]
                for dataset_id in live
                if dataset_id in self._slug_cache
            },
        )
