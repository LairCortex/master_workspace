"""The module's encounter source (add-dnd-game-face task 11.1; spec
dnd-encounters).

A third tab-contributing source beside the character-tab one, this one
attached to the kernel EVENT card: it declares no registry types and no
records — its whole contribution is the «Встреча» tab every event card grows
while the module is attached, and the ladder marks of the encounter-carrying
events (design Д9, spec «Пометка встречи на лестнице»).

The same module-lifetime gate as the character tabs (façade's duck door
``set_attached``, spec entity-card-tabs «Таб модуля живёт с модулем»): while
the module is off its tab is gone «без следа» and its marks are hidden data,
the storage rows untouched (spec scenario «Без модуля таба нет»).

The kernel is a KERNEL entity here — its numeric row id projected to the
protocol's string is this source's whole use of the pair grammar:
``card_tabs`` answers only for ``target.key == "event"``, and an id that is
not a whole raises — the host's tolerant door journals and skips the tab.

The marks live in a cache because ``event_marks`` is the protocol's SYNC door
(the timeline core reads it while re-modelling rows on the UI thread): the
cache is refreshed by ``warm`` at game open (protocol task 6.2 — the ladder
feeds before any search ran), by ``search``/async reads, and reconciled
in-place by the tab's own save through the duck ``apply_saved``.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.domain.entity_registry import EntityType

if TYPE_CHECKING:
    from app.dd.application.dd_encounter_service import DdEncounterService
    from app.dd.application.monster_service import DdMonsterService
    from app.domain.entity_registry import ExternalTypeDescriptor
    from app.presentation.modules.protocol import CardTabSpec, CardTabTarget

#: The tab key is a FOREVER literal (the host keys its widget dict by it);
#: the caption is the spec's (design-задача 1.1, docs/qa/2026-10-10 §1).
ENCOUNTER_TAB_KEY = "dnd.encounter"
ENCOUNTER_TAB_TITLE = "Встреча"

#: The mark token the timeline delegate paints as the accent ring around the
#: type square (design-задача 1.1 §4). A plain data token, not a caption:
#: the ladder only ever compares it, the Russian word never lives here twice.
ENCOUNTER_MARK = "encounter"


class DndEncounterSource:
    """The «Встреча» tab of every event card + the ladder's encounter marks."""

    def __init__(
        self,
        *,
        encounter_service: "DdEncounterService",
        monster_service: "DdMonsterService",
    ) -> None:
        self._encounters = encounter_service
        # The picker's door: the tab offers bestiary monsters through the
        # SAME service the bestiary screens use (one knowledge, one place).
        self._monsters = monster_service
        # Dark until the façade attaches it (the character-tab source's
        # posture); before the first attach a composed source is honestly
        # tab-less and mark-less.
        self._attached = False
        # event ids whose overlay carries at least one composition row —
        # refreshed by warm(), reconciled by apply_saved().
        self._encountered: set[int] = set()

    # ── the module-lifecycle door ────────────────────────────────────────────

    def set_attached(self, attached: bool) -> None:
        """The façade's propagation of attach/detach (duck protocol among
        the module's own classes — DndModule._set_sources_attached)."""
        self._attached = bool(attached)

    # ── the kernel protocol ──────────────────────────────────────────────────

    @property
    def type_descriptors(self) -> tuple["ExternalTypeDescriptor", ...]:
        """No types: the event is the kernel's, the overlay is not an entity
        (spec «не отдельная сущность») — nothing to register."""
        return ()

    @property
    def visible(self) -> bool:
        """The module's attach state (the host and the timeline both gate on
        it; the tolerant surfaces that forgot the check still get honest
        empties from every door below)."""
        return self._attached

    async def warm(self) -> None:
        """Refresh the marks cache (protocol task 6.2): the ladder feeds
        BEFORE any surface performs an async read, so the event ids with an
        overlay are brought current here. A failure is this source's own
        silence — the protocol's warm never raises at the composition; the
        ladder simply paints no rings this time."""
        if not self._attached:
            return
        try:
            self._encountered = set(await self._encounters.encountered_event_ids())
        except Exception:  # noqa: BLE001 — warm fails as silence (protocol)
            logging.getLogger(__name__).warning(
                "dd encounter: прогрев пометок не удался — лестница без колец",
                exc_info=True,
            )

    async def search(self, query: str) -> tuple:
        return ()

    def card_source(self, key: str, source_id: str):
        return None

    async def mention_candidates(self, query: str) -> tuple:
        return ()

    def resolve_mention(self, key: str, source_id: str):
        return None

    def card_tabs(self, target: "CardTabTarget") -> "tuple[CardTabSpec, ...]":
        """The «Встреча» tab, for an event only, and only while the module
        lives (spec dnd-encounters «При недоступном модуле таб SHALL
        отсутствовать без следа»)."""
        from app.presentation.modules.protocol import CardTabSpec

        if not self._attached or target.key != EntityType.EVENT.value:
            return ()
        return (
            CardTabSpec(ENCOUNTER_TAB_KEY, ENCOUNTER_TAB_TITLE, self._build_tab),
        )

    def event_marks(self, event_ids: Sequence[int]) -> dict[int, str]:
        """The ladder marks from the cache — while the module is attached
        (spec «при выключенном модуле … пометки быть НЕ SHALL»); events
        without an overlay are absent, exactly as the protocol says."""
        if not self._attached:
            return {}
        return {
            event_id: ENCOUNTER_MARK
            for event_id in event_ids
            if event_id in self._encountered
        }

    # ── the tab factory (protocol CardTabSpec.factory: (wiring, id)) ─────────

    def _event_id(self, source_id: str) -> int:
        """The kernel row id behind the protocol string; a non-whole id
        raises — the host catches, journals and skips the tab (a foreign
        target could only be a composition bug; guessing an id is not on the
        table)."""
        return int(source_id)

    def _build_tab(self, wiring: object, source_id: str):
        from app.dd.presentation.character_tab_source import _require_run_locked
        from app.dd.presentation.dd_encounter_frame import DndEncounterTabFrame

        return DndEncounterTabFrame(
            event_id=self._event_id(source_id),
            encounter_service=self._encounters,
            monster_service=self._monsters,
            source=self,
            run_locked=_require_run_locked(wiring),
        )

    # ── marks-cache reconciliation (module-internal duck door) ────────────────

    def apply_saved(self, event_id: int, has_encounter: bool) -> None:
        """The tab's save tells the cache what the write just did, so the
        ladder repaints the mark from the truth of the storage without a
        second read (the connector reloads the timeline right after the
        save — the fresh cache is what makes that reload answer correctly)."""
        if has_encounter:
            self._encountered.add(event_id)
        else:
            self._encountered.discard(event_id)
