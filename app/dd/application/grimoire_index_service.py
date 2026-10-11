"""What the game's connected grimoires declare (add-dnd-game-face, tasks 4.3
and 6.1; design Д5/Д8; spec dnd-grimoire-import «Слаги гримуаров расширяют
словарь валидатора», spec dnd-reference-records «Хоумбрю-заклинание читается
полностью»).

The grimoire half of the read cache design Д5 describes: the file stays the
truth, this service is the door every consumer reads through instead of the
disk. Two doors grew through the slices:

* the async :meth:`spell_slugs` — the dataset validator's spell dictionary
  (task 4.3: «не-SRD-заклинание, объявленное в датасете и присутствующее в
  подключённом гримуаре, SHALL NOT помечаться как слаг вне SRD»);
* since task 6.1 the whole-record snapshot (:meth:`snapshot` /
  :meth:`snapshot_now`) — slug → :class:`GrimoireSpell` per grimoire, the
  name+description the reference source assembles into spell cards, search
  rows and mention candidates. The SYNC door mirrors :class:`
  DatasetIndexService`'s for the same reason: the protocol's card/mention
  calls carry no event loop, and the pin restore warms the cache first
  (protocol ``warm``) so the sync door is honest at game open.

Tolerance is the dataset index's, and for the same reason: a file that
vanished, bytes that do not parse, or a document with no spells contribute
nothing — the voice of a broken grimoire is its owner's import report, not
this reader's. An empty connection list is the empty answer at zero cost.

The cache is the digest discipline design Д5 prescribes: before every async
read the service re-hashes the stored bytes (grimoire exports are small —
the design's «полных переразборов не боятся») and reparses only the files
whose digest moved, an on-disk edit between two reads included.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.domain.grimoire import GrimoireSpell, parse_grimoire
from app.dd.infrastructure.grimoire_storage import GrimoireStorage


@dataclass(frozen=True)
class GrimoireIndexSnapshot:
    """One immutable read of the whole shelf: connected grimoires in list
    order (only those whose bytes parsed into a document), their storage
    titles (the card's origin label) and the per-grimoire slug → spell maps
    (file order first-wins on a duplicate slug — the import report voices
    the duplicate, this reader keeps one honest entry)."""

    ids: tuple[str, ...]
    titles: Mapping[str, str]
    spells: Mapping[str, Mapping[str, GrimoireSpell]]

    def spell(self, grimoire_id: str, slug: str) -> GrimoireSpell | None:
        """One spell addressed by its pair (``источник/запись`` grammar,
        design Д4); ``None`` when the grimoire is not connected, unreadable,
        or declares no such slug."""
        return self.spells.get(grimoire_id, {}).get(slug)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_grimoire_spells(content: str) -> dict[str, GrimoireSpell]:
    """The spell dictionary of one grimoire file: slug → spell, file order,
    first entry wins on a duplicate slug. The parse verdict is not this
    reader's business — an unparseable file (or a document whose entries
    name no slugs) simply answers the empty map."""
    parsed: dict[str, GrimoireSpell] = {}
    for spell in parse_grimoire(content).spells:
        if spell.slug and spell.slug not in parsed:
            parsed[spell.slug] = spell
    return parsed


class GrimoireIndexService:
    """The per-game read cache over the connected grimoire files.

    Stateless besides the cache: the connection list and the files stay the
    truth; every async read reconciles the cache with them first (design Д5)
    and answers from the resulting snapshot, while :meth:`snapshot_now` is
    the SYNC door the protocol's non-async calls read (the dataset index's
    posture, one sentence from its class docstring applies verbatim)."""

    def __init__(
        self, connections: GrimoireConnectionsService, storage: GrimoireStorage
    ) -> None:
        self._connections = connections
        self._storage = storage
        # grimoire id → (digest, slug → spell) for every file read whole.
        self._cache: dict[str, tuple[str, Mapping[str, GrimoireSpell]]] = {}
        self._snapshot: GrimoireIndexSnapshot = GrimoireIndexSnapshot(
            ids=(), titles={}, spells={}
        )

    # ── reads (the surfaces' door) ───────────────────────────────────────────

    async def snapshot(self) -> GrimoireIndexSnapshot:
        """Reconcile with the connection list and the files, answer the
        fresh snapshot."""
        await self._reconcile()
        return self._snapshot

    def snapshot_now(self) -> GrimoireIndexSnapshot:
        """The last snapshot WITHOUT reconciling — the sync door the
        protocol's non-async calls read."""
        return self._snapshot

    async def spell_slugs(self) -> tuple[str, ...]:
        """Every connected grimoire's spell slugs — connection order first,
        file order inside each file, duplicates collapsed (the dictionary
        only asks «is this slug known?»)."""
        snap = await self.snapshot()
        slugs: list[str] = []
        for grimoire_id in snap.ids:
            for slug in snap.spells.get(grimoire_id, {}):
                if slug not in slugs:
                    slugs.append(slug)
        return tuple(slugs)

    # ── reconciliation (the design Д5 digest discipline) ─────────────────────

    async def _reconcile(self) -> None:
        """Bring the cache to the connection list and the files' current
        bytes, then rebuild the snapshot. A disconnected grimoire and a file
        that vanished drop out; a digest that moved (including an edit
        outside the app between two reads) reparses just that file."""
        live = await self._connections.connections()
        live_set = set(live)
        for grimoire_id in list(self._cache):
            if grimoire_id not in live_set:
                del self._cache[grimoire_id]
        if not live:
            # The laziness of task 4.3 (spec «пустой список связей — пустой
            # ответ без обращения к диску»): without a single connection the
            # answer is empty by definition — neither the files nor the
            # shelf directory are touched, a game that never connected a
            # grimoire keeps its home directory exactly as it found it.
            self._snapshot = GrimoireIndexSnapshot(ids=(), titles={}, spells={})
            return
        for grimoire_id in live:
            try:
                content = self._storage.load_content(grimoire_id)
            except ValueError:
                # A stored id that is not a safe file name (corrupted
                # settings row) names no file by construction — the
                # vanished-grimoire posture, never a raised error at the
                # reader (protocol warm: the source answers with silence).
                content = None
            if content is None:
                self._cache.pop(grimoire_id, None)
                continue
            digest = _digest(content)
            cached = self._cache.get(grimoire_id)
            if cached is not None and cached[0] == digest:
                continue
            self._cache[grimoire_id] = (digest, parse_grimoire_spells(content))
        titles = {
            status.grimoire_id: status.title
            for status in await self._connections.statuses()
            if status.present
        }
        self._snapshot = GrimoireIndexSnapshot(
            ids=tuple(grimoire_id for grimoire_id in live if grimoire_id in self._cache),
            titles=titles,
            spells={
                grimoire_id: self._cache[grimoire_id][1]
                for grimoire_id in live
                if grimoire_id in self._cache
            },
        )
