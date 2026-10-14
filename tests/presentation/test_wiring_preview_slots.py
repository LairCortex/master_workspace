"""NRI-0025 (tasks 5.1/5.2) — unit guards of the connector's slot model.

The screen-level transitions (pin splits the column, the fourth pin dies on
the live card's own pin, restart restores) are e2e
(tests/ui/test_e2e_preview_pins.py); this file pins the connector's private
model half that the island cannot produce by clicks — the silent rejections
and the storage discipline:

* restore drops pairs that do not resolve (unknown type, vanished row)
  silently and NEVER rewrites storage (design Д3: the next explicit
  pin/unpin persists the clean list);
* without a storage face (the unit-built connectors' default, the same
  documented defaulting as the «now» pair) the pin model still moves and
  only persistence is off;
* a pin request rides the live pair only (a stale press is a silent no-op),
  an already-pinned pair is never seated a second time, the fourth pin is
  rejected in the model exactly as the island rejects it on screen, and an
  unpin of a pair that is not pinned changes nothing.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.presentation.modules.protocol import ExternalCardSource
from app.presentation.viewmodels.entity_preview_view_model import MAX_PINNED_CARDS
from app.presentation.wiring import ApplicationWiring


class _Entity:
    def __init__(self, entity_id: int, name: str = "Банн") -> None:
        self.id = entity_id
        self.name = name


class _EntityService:
    def __init__(self, rows: dict[int, _Entity]) -> None:
        self.rows = rows

    async def get_entity(self, entity_id: int):
        return self.rows.get(entity_id)


class _Event(_Entity):
    """Event duck: same id/name face the slot cache and the frame recorder
    read; the real ``EventModel`` adds the relation lists the card renders."""


class _EventService:
    """Event-service duck with the one door the preview loader uses."""

    def __init__(self, rows: dict[int, _Event]) -> None:
        self.rows = rows

    async def get_event(self, event_id: int):
        return self.rows.get(event_id)


class _PinsService:
    """Storage spy with the real service's get/save face."""

    def __init__(self, saved: list[tuple[str, int]] | None = None) -> None:
        self.saved = list(saved or [])
        self.saves: list[list[tuple[str, int]]] = []

    async def get_pins(self):
        return list(self.saved)

    async def save_pins(self, pins) -> None:
        self.saves.append(list(pins))


class _Frames(list):
    """Records the frames the facade is handed as (type, id) pairs."""

    def show_slots(self, pins, live, mirror=None) -> None:
        self.mirrors = getattr(self, "mirrors", []) + [mirror]
        self.append(
            (
                [(t, entity.id) for t, entity in pins],
                None if live is None else (live[0], live[1].id),
            )
        )


class _DetailPanel:
    """Middle-column facade duck: records the transition's sync request. In
    the real wiring that request makes the panel echo ``entitySelected``
    back onto the selection bus (the ``connect``-time lambda); the echo's
    frame discipline is exercised by calling ``_show_in_preview`` again."""

    def __init__(self) -> None:
        self.selects: list[tuple[str, int]] = []

    def select_entity(self, entity_type: str, entity_id: int) -> None:
        self.selects.append((entity_type, entity_id))


def _make_wiring(
    pins_service: _PinsService | None = None,
    rows: dict[int, _Entity] | None = None,
    event_rows: dict[int, _Event] | None = None,
) -> ApplicationWiring:
    """The connector with exactly what the preview-slot paths touch — the
    same duck construction the sheet-stack wiring tests use. ``event_rows``
    stands for the composition root's real event service (None keeps the
    unit-built connector's event-less posture)."""
    entity_service = _EntityService(rows or {})
    app = SimpleNamespace(
        _image_store=None,
        _get_entity_service=lambda entity_type: (
            entity_service if entity_type == "character" else None
        ),
    )
    return ApplicationWiring(
        app,
        SimpleNamespace(
            entity_preview=_Frames(),
            detail_panel=_DetailPanel(),
        ),
        None, None, None, None,
        _EventService(event_rows) if event_rows is not None else None,
        SimpleNamespace(lock=asyncio.Lock()),
        preview_pins_service=pins_service,
    )


# ── task 5.2: restore (design Д3) ────────────────────────────────────────────


async def test_restore_loads_only_resolvable_pairs_and_never_rewrites():
    service = _PinsService([("character", 1), ("character", 99), ("ghost", 1)])
    wiring = _make_wiring(service, rows={1: _Entity(1)})

    await wiring.restore_preview_pins()

    # The vanished row and the unknown type dropped silently, order kept;
    # storage stays byte-identical — no background repair write (Д3).
    # (The dropped unknown key used to be ``("event", 1)``: since the
    # dd-card-redesign audit fix an event resolves through the connector's
    # event service — pinned by the two tests below.)
    assert wiring._preview_pins == [("character", 1)]
    assert service.saves == []
    # The frame for the restored column: pins with the loaded row, no live.
    assert list(wiring._window.entity_preview) == [([("character", 1)], None)]


async def test_restore_seats_event_pairs_through_the_event_loader():
    # dd-card-redesign audit fix (spec preview-pins «числовой — для сущностей
    # ядра» + entity-preview «Событие показывает встречу»): a stored event
    # pin is a resolvable kernel pair — it restores like any entity.
    service = _PinsService([("event", 5), ("event", 9)])
    wiring = _make_wiring(service, event_rows={5: _Event(5, "Полоса")})

    await wiring.restore_preview_pins()

    assert wiring._preview_pins == [("event", 5)]
    assert service.saves == []
    assert list(wiring._window.entity_preview) == [([("event", 5)], None)]


async def test_restore_drops_event_pair_without_the_event_service():
    # The unit-built connector's event-less posture stays honest: a pair the
    # connector cannot load is a silent drop, the same vanished-row rule —
    # storage is still never rewritten behind the user's back.
    service = _PinsService([("event", 5)])
    wiring = _make_wiring(service)

    await wiring.restore_preview_pins()

    assert wiring._preview_pins == []
    assert service.saves == []
    assert list(wiring._window.entity_preview) == [([], None)]


async def test_restore_without_the_storage_face_is_a_no_op():
    wiring = _make_wiring()

    await wiring.restore_preview_pins()

    assert wiring._preview_pins == []
    assert list(wiring._window.entity_preview) == []


# ── task 5.1: the pin channel's silent rejections (design Д3/Д4) ─────────────


async def test_pin_and_unpin_persist_when_the_face_exists():
    service = _PinsService()
    wiring = _make_wiring(service, rows={1: _Entity(1)})
    wiring._preview_live = ("character", 1)
    wiring._preview_rows[("character", 1)] = _Entity(1)

    await wiring._on_preview_pin_toggled("character", 1, False)

    # Pin seats the live pair, frees the live area, saves once, pushes one
    # frame in which the card stands pinned over the empty live slot.
    assert wiring._preview_pins == [("character", 1)]
    assert wiring._preview_live is None
    assert service.saves == [[("character", 1)]]
    assert list(wiring._window.entity_preview) == [([("character", 1)], None)]

    await wiring._on_preview_pin_toggled("character", 1, True)

    assert wiring._preview_pins == []
    assert service.saves == [[("character", 1)], []]
    assert list(wiring._window.entity_preview)[-1] == ([], None)


async def test_pin_model_works_without_the_storage_face():
    wiring = _make_wiring()
    row = _Entity(1)
    wiring._preview_live = ("character", 1)
    wiring._preview_rows[("character", 1)] = row

    await wiring._on_preview_pin_toggled("character", 1, False)

    # No service, no persistence — but the model moved and the frame went.
    assert wiring._preview_pins == [("character", 1)]
    assert wiring._preview_live is None
    assert list(wiring._window.entity_preview) == [([("character", 1)], None)]


async def test_pin_press_on_a_pair_that_is_not_live_is_ignored():
    wiring = _make_wiring()
    wiring._preview_live = ("character", 2)

    await wiring._on_preview_pin_toggled("character", 1, False)

    # A press whose pair stopped being the live card between press and
    # answer changes neither model nor screen.
    assert wiring._preview_pins == []
    assert wiring._preview_live == ("character", 2)
    assert list(wiring._window.entity_preview) == []


async def test_already_pinned_pair_is_never_seated_a_second_time():
    service = _PinsService()
    wiring = _make_wiring(service, rows={1: _Entity(1)})
    pair = ("character", 1)
    wiring._preview_pins = [pair]
    wiring._preview_rows[pair] = _Entity(1)
    # The duplicate situation of the spec: the SAME pair lives under the pin.
    wiring._preview_live = pair

    await wiring._on_preview_pin_toggled("character", 1, False)

    assert wiring._preview_pins == [pair]
    assert wiring._preview_live == pair
    assert service.saves == []
    assert list(wiring._window.entity_preview) == []


async def test_fourth_pin_is_rejected_in_the_model():
    service = _PinsService()
    rows = {i: _Entity(i) for i in range(1, 5)}
    wiring = _make_wiring(service, rows=rows)
    wiring._preview_pins = [("character", i) for i in range(1, MAX_PINNED_CARDS + 1)]
    for i in range(1, MAX_PINNED_CARDS + 1):
        wiring._preview_rows[("character", i)] = rows[i]
    wiring._preview_live = ("character", MAX_PINNED_CARDS + 1)
    wiring._preview_rows[("character", MAX_PINNED_CARDS + 1)] = rows[MAX_PINNED_CARDS + 1]

    await wiring._on_preview_pin_toggled("character", MAX_PINNED_CARDS + 1, False)

    # The island cannot even press this pin (its state word is the capacity
    # one); should a stale frame ever answer a press, the model refuses too:
    # no seat, no save, no frame.
    assert len(wiring._preview_pins) == MAX_PINNED_CARDS
    assert wiring._preview_live == ("character", MAX_PINNED_CARDS + 1)
    assert service.saves == []
    assert list(wiring._window.entity_preview) == []


async def test_unpin_of_a_pair_that_is_not_pinned_changes_nothing():
    service = _PinsService()
    wiring = _make_wiring(service)
    wiring._preview_live = ("character", 2)
    wiring._preview_rows[("character", 2)] = _Entity(2)

    await wiring._on_preview_pin_toggled("character", 1, True)

    assert wiring._preview_pins == []
    assert wiring._preview_live == ("character", 2)
    assert service.saves == []
    assert list(wiring._window.entity_preview) == []


# ── 2026-10-03 drift diagnosis: a transition presents exactly ONE frame ─────


async def test_a_transition_pushes_one_frame_even_with_the_panel_echo():
    # The scroll-drift investigation asked how many frames a mention/relation
    # transition shows the island: an intermediate second push would be a
    # second delegate teardown/refill, costing a restoring pane its accuracy.
    # The answer pinned here: exactly one.
    wiring = _make_wiring(rows={2: _Entity(2)})

    await wiring._on_preview_entity_requested("character", 2)

    # The live pair seats with its loaded row and ONE frame goes out...
    assert list(wiring._window.entity_preview) == [([], ("character", 2))]
    # ...then the middle-column sync is requested;
    assert wiring._window.detail_panel.selects == [("character", 2)]
    # and the ``entitySelected`` echo that sync runs back into the connector
    # is the already-live early return: no reload, no second frame (the
    # echo-swallow posture of ``_show_in_preview``).
    assert await wiring._show_in_preview("character", 2) is True
    assert list(wiring._window.entity_preview) == [([], ("character", 2))]


# ── add-dnd-game-face task 3.4: the external live seat ──────────────────────


class _ExtFrames(list):
    """The same frame recorder, lenient to an external row (protocol Д3
    cards carry a string source_id on the pair, no int id on the record)."""

    def show_slots(self, pins, live, mirror=None) -> None:
        self.mirrors = getattr(self, "mirrors", []) + [mirror]

        def label(record):
            # kernel rows stamp with their int id, protocol cards with name
            return getattr(record, "id", None) or getattr(record, "name", None)

        self.append(
            (
                [(t, label(e)) for t, e in pins],
                None if live is None else (live[0], label(live[1])),
            )
        )


_UNSET = object()


def _ExtCard(name="Везучесть"):
    """The protocol's frozen card record, as a source hands it (task 6.1:
    the seat stamps it with ``replace``, so the real dataclass — not a duck —
    is what every external path must survive)."""
    return ExternalCardSource(name=name, origin="SRD 5.1")


class _ExtSource:
    """Duck of ExternalEntitySource with exactly what the live seat, the
    mention door and the restore's warm-up read."""

    def __init__(
        self, key="dd_feat", card=None, visible=True, resolve=_UNSET, log=None
    ) -> None:
        self.type_descriptors = [SimpleNamespace(key=key)]
        self.visible = visible
        self._card = card
        self._resolve = card if resolve is _UNSET else resolve
        self._log = log
        self.card_calls: list[tuple[str, str]] = []
        self.resolve_calls: list[tuple[str, str]] = []
        self.warm_calls = 0

    async def warm(self):
        self.warm_calls += 1
        if self._log is not None:
            self._log.append("warm")

    def card_source(self, key, source_id):
        self.card_calls.append((key, source_id))
        if self._log is not None:
            self._log.append("card")
        return self._card

    def resolve_mention(self, key, source_id):
        self.resolve_calls.append((key, source_id))
        return self._resolve


def _make_external_wiring(
    *sources, pins_service: _PinsService | None = None
) -> tuple[ApplicationWiring, _ExtFrames]:
    frames = _ExtFrames()
    app = SimpleNamespace(_image_store=None, _get_entity_service=lambda et: None)
    wiring = ApplicationWiring(
        app,
        SimpleNamespace(entity_preview=frames, detail_panel=_DetailPanel()),
        None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
        external_sources=sources,
        preview_pins_service=pins_service,
    )
    return wiring, frames


async def test_external_seat_fills_the_live_area_and_next_pair_evicts():
    """Spec global-search «клик по внешней строке… (только предпросмотр)»:
    the source's card record is seated as live and reaches the frame; the
    detail panel is NOT touched (no entity, no event); the replaced external
    pair leaves the row cache (the kernel eviction rule, verbatim); re-click
    of the live pair answers True pushing NOTHING (kernel no-op rule)."""
    first, second = _ExtCard("Везучесть"), _ExtCard("Бдительность")
    source = _ExtSource(card=first)
    wiring, frames = _make_external_wiring(source)

    assert await wiring._show_external_in_preview("dd_feat", "srd/lucky") is True
    assert wiring._preview_live == ("dd_feat", "srd/lucky")
    seated = wiring._preview_rows[("dd_feat", "srd/lucky")]
    # task 6.1: the cache row is the source's record STAMPED with its pair id
    assert seated.name == first.name and seated.source_id == "srd/lucky"
    pins, live = frames[-1]
    assert pins == [] and live == ("dd_feat", "Везучесть")

    source._card = second
    assert await wiring._show_external_in_preview("dd_feat", "srd/alert") is True
    assert ("dd_feat", "srd/lucky") not in wiring._preview_rows
    assert len(frames) == 2

    before = len(frames)
    assert await wiring._show_external_in_preview("dd_feat", "srd/alert") is True
    assert len(frames) == before
    assert source.card_calls == [("dd_feat", "srd/lucky"), ("dd_feat", "srd/alert")]


async def test_external_seat_misses_move_nothing():
    """Every miss posture answers False pushing no frame: a key no source
    provides, an invisible source (the reference toggle off — never even
    asked for a card), and a record the visible source cannot assemble."""
    invisible = _ExtSource(key="dd_feat", card=_ExtCard(), visible=False)
    provider = _ExtSource(key="dd_feat", card=None)
    wiring, frames = _make_external_wiring(invisible, provider)

    assert await wiring._show_external_in_preview("dd_spell", "srd/x") is False
    assert await wiring._show_external_in_preview("dd_feat", "srd/lucky") is False
    assert invisible.card_calls == []
    assert wiring._preview_live is None
    wiring._preview_rows.clear()
    assert list(frames) == []


async def test_external_seat_survives_a_kernel_live_pair_eviction():
    """One live pointer serves both kinds: a kernel selection replaces an
    external live pair (cache entry evicted with it), and the external card
    record — not any wrapper — is what the frame carries."""
    card = _ExtCard()
    source = _ExtSource(card=card)
    wiring, frames = _make_external_wiring(source)
    await wiring._show_external_in_preview("dd_feat", "srd/lucky")

    service_rows = {5: _Entity(5)}
    wiring._app = SimpleNamespace(
        _image_store=None,
        _get_entity_service=lambda et: _EntityService(service_rows),
    )
    assert await wiring._show_in_preview("character", 5) is True
    assert wiring._preview_live == ("character", 5)
    assert ("dd_feat", "srd/lucky") not in wiring._preview_rows
    pins, live = frames[-1]
    assert live == ("character", 5)


# ── add-dnd-game-face task 5.2: the activated external chip ─────────────────


async def test_open_external_mention_seats_the_resolved_record():
    """Spec mentions «Активация внешнего чипа»: resolve_mention is the door;
    a resolved record takes the live seat (read-only — the edit dialog is
    opened for NOTHING from this path, the seat itself was pinned in 3.4),
    and the composite string id reaches the source whole."""
    card = _ExtCard()
    source = _ExtSource(card=card)
    wiring, frames = _make_external_wiring(source)

    assert await wiring.open_external_mention("dd_feat", "srd51/Darkvision") is True
    assert source.resolve_calls == [("dd_feat", "srd51/Darkvision")]
    assert wiring._preview_live == ("dd_feat", "srd51/Darkvision")
    pins, live = frames[-1]
    assert pins == [] and live == ("dd_feat", "Везучесть")


async def test_open_external_mention_misses_report_to_the_caller():
    """False — and NOTHING moves — for every unavailable posture: a key no
    source provides, a hidden source (its set switched off — the chip
    «доживает до отключения датасета» and is not even consulted), and a
    record the visible source cannot reassemble (resolve answers None even
    though the same object would answer a card). The caller owns the one
    «Упоминание не найдено» channel; the connector just refuses."""
    invisible = _ExtSource(card=_ExtCard(), visible=False)
    vanished = _ExtSource(key="dd_feat", card=_ExtCard(), resolve=None)
    wiring, frames = _make_external_wiring(invisible, vanished)

    assert await wiring.open_external_mention("dd_spell", "srd/x") is False
    assert await wiring.open_external_mention("dd_feat", "srd51/Darkvision") is False
    assert invisible.resolve_calls == []
    assert vanished.resolve_calls == [("dd_feat", "srd51/Darkvision")]
    assert wiring._preview_live is None
    assert list(frames) == []


# ── add-dnd-game-face tasks 6.1/6.2: stamped seats, warm-up, string pins ─────


async def test_show_external_card_is_the_public_door():
    """Task 6.3's door for the module's reference sheet: the same seat, the
    same miss posture — True once the live area shows the pair (a repeated
    click is the no-op True), False leaves everything where it was."""
    source = _ExtSource(card=_ExtCard("Огненные руки"))
    wiring, frames = _make_external_wiring(source)

    assert await wiring.show_external_card("dd_feat", "srd/hands") is True
    assert wiring._preview_live == ("dd_feat", "srd/hands")
    before = len(frames)
    assert await wiring.show_external_card("dd_feat", "srd/hands") is True
    assert len(frames) == before
    assert await wiring.show_external_card("dd_spell", "srd/x") is False
    assert wiring._preview_live == ("dd_feat", "srd/hands")


async def test_restore_warms_sources_before_reading_the_sync_door():
    """Task 6.2, design Д5: the pin restore calls the SYNC card door before
    any surface performed an async read, so every source is warmed FIRST —
    the protocol orders warm→card, and a restored external pin seats the
    source's record stamped with its pair id (6.1's rule, same as a click)."""
    log: list[str] = []
    source = _ExtSource(card=_ExtCard("Везучесть"), log=log)
    pins = _PinsService([("dd_feat", "srd/lucky")])
    wiring, frames = _make_external_wiring(source, pins_service=pins)

    await wiring.restore_preview_pins()

    assert log == ["warm", "card"]
    assert source.warm_calls == 1
    assert wiring._preview_pins == [("dd_feat", "srd/lucky")]
    restored = wiring._preview_rows[("dd_feat", "srd/lucky")]
    assert restored.name == "Везучесть" and restored.source_id == "srd/lucky"
    stored_pins, live = frames[-1]
    assert stored_pins == [("dd_feat", "Везучесть")] and live is None
    assert pins.saves == []  # restore never rewrites storage (design Д3)


async def test_restore_drops_unresolvable_external_pairs_silently():
    """Spec «Отключённый источник тихо убирает закрепление»: an invisible
    source is not even consulted for a card, a key no source provides and a
    record the provider cannot assemble drop out the same way; every source
    was still warmed (the warm-up is unconditional), storage is untouched."""
    off = _ExtSource(card=_ExtCard())  # visible=False? no — separate below
    off.visible = False
    empty = _ExtSource(key="dd_feat", card=None)
    pins = _PinsService(
        [("dd_feat", "srd/lucky"), ("dd_spell", "srd/x")]
    )
    wiring, frames = _make_external_wiring(off, empty, pins_service=pins)

    await wiring.restore_preview_pins()

    assert off.card_calls == []  # hidden source never asked
    assert pins.saves == []
    assert wiring._preview_pins == []
    stored_pins, live = frames[-1]
    assert stored_pins == [] and live is None


# ── dd-card-redesign task 7.1: the module mirror bridge ──────────────────────


from app.presentation.modules.protocol import ModuleBlockFrame, ModuleSection  # noqa: E402


def _section(title: str) -> ModuleSection:
    return ModuleSection(title=title, lines=("строка",))


class _MirrorSource:
    """A duck external source whose preview doors answer; records every ask
    so the tests can watch the id projection and the tolerance posture."""

    def __init__(
        self,
        *,
        key: str = "character",
        sections=(),
        awaitable: bool = False,
        hidden: tuple[str, ...] = (),
        raise_sections: bool = False,
        visible: bool = True,
    ) -> None:
        self.key = key
        self.sections = tuple(sections)
        self.awaitable = awaitable
        self.hidden = hidden
        self.raise_sections = raise_sections
        self._visible = visible
        self.asks: list[tuple[str, str]] = []

    async def warm(self) -> None:
        """Protocol task 6.2: nothing to warm here."""

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def type_descriptors(self):
        return ()

    def module_blocks(self, target) -> ModuleBlockFrame:
        return ModuleBlockFrame(hidden_fields=self.hidden)

    def module_sections(self, key: str, source_id: str):
        self.asks.append((key, source_id))
        if self.raise_sections:
            raise RuntimeError("диск отказал")
        if key != self.key:
            return ()
        if self.awaitable:

            async def answer():
                return self.sections

            return answer()
        return self.sections


class _DoorlessSource:
    """A source that never learned the preview doors (the reference source's
    shape): NEITHER attribute exists, the bridge must getattr past it
    without a word."""

    @property
    def visible(self) -> bool:
        return True

    @property
    def type_descriptors(self):
        return ()

    async def warm(self) -> None:
        return None


def _make_mirror_wiring(sources, rows=None, pins_service=None) -> ApplicationWiring:
    wiring = _make_wiring(pins_service, rows or {1: _Entity(1), 2: _Entity(2)})
    wiring.set_external_sources(sources)
    return wiring


async def test_live_seat_reads_mirror_and_frames_it_onto_the_pair():
    """Task 7.1 (design Д5): the new live seat reads the mirror through the
    doors — the id projected to the protocol string, hidden fields merged
    from the card's blocks door — and the pushed frame carries it keyed by
    the kernel pair the slot identity speaks."""
    source = _MirrorSource(sections=(_section("Происхождение"),), hidden=("characteristics",))
    wiring = _make_mirror_wiring([source], rows={1: _Entity(1)})

    assert await wiring._show_in_preview("character", 1) is True

    assert source.asks == [("character", "1")]
    assert wiring._preview_mirror == {
        ("character", 1): ((_section("Происхождение"),), ("characteristics",))
    }
    assert wiring._window.entity_preview.mirrors[-1] == {
        ("character", 1): ((_section("Происхождение"),), ("characteristics",))
    }


async def test_bridge_awaits_an_async_door_and_skips_a_doorless_source():
    """The protocol's task-7.1 posture: an awaitable answer is awaited in
    the same task; a source that implements neither door is passed over
    without a word (the reference source's shape)."""
    async_source = _MirrorSource(
        key="event", sections=(_section("Встреча"),), awaitable=True
    )
    silent = _DoorlessSource()
    wiring = _make_mirror_wiring([async_source, silent])

    await wiring._refresh_preview_mirror(("event", 7))

    assert async_source.asks == [("event", "7")]
    assert wiring._preview_mirror == {("event", 7): ((_section("Встреча"),), ())}


async def test_a_failing_door_is_journalled_silence_not_a_lost_frame():
    """One source's read failure never eats the frame: the bridge journals,
    the pair rides without sections (the kernel render stands)."""
    broken = _MirrorSource(raise_sections=True)
    wiring = _make_mirror_wiring([broken], rows={1: _Entity(1)})

    assert await wiring._show_in_preview("character", 1) is True

    assert wiring._preview_mirror == {}
    assert wiring._window.entity_preview.mirrors[-1] == {}


async def test_invisible_source_does_not_answer():
    source = _MirrorSource(sections=(_section("Характеристики"),))
    source._visible = False
    wiring = _make_mirror_wiring([source])

    await wiring._refresh_preview_mirror(("character", 1))

    assert source.asks == []
    assert wiring._preview_mirror == {}


async def test_push_prunes_the_mirror_to_the_frame():
    """A pair that left the column leaves the mirror too — a later frame can
    never resurrect a stale mirror through the reuse gate."""
    source = _MirrorSource(sections=(_section("Происхождение"),))
    wiring = _make_mirror_wiring([source], rows={1: _Entity(1), 2: _Entity(2)})

    await wiring._show_in_preview("character", 1)
    await wiring._show_in_preview("character", 2)

    assert wiring._preview_mirror == {("character", 2): ((_section("Происхождение"),), ())}
    assert wiring._window.entity_preview.mirrors[-1] == {
        ("character", 2): ((_section("Происхождение"),), ())
    }


async def test_module_leaving_the_composition_empties_the_mirrors():
    """«Без модуля предпросмотр не отличается»: the mirror cache retires with
    the source list it was read from, so the next frame pushes the pair with
    no sections and the card's reuse stamp rebuilds it plain."""
    source = _MirrorSource(sections=(_section("Происхождение"),))
    wiring = _make_mirror_wiring([source], rows={1: _Entity(1)})
    await wiring._show_in_preview("character", 1)
    assert wiring._preview_mirror != {}

    wiring.set_external_sources(())

    assert wiring._preview_mirror == {}


# ── dd-card-redesign audit fix: the event seat of the live area ──────────────
#
# The deadness of ("event", id) used to be pinned as contract (the QA report
# docs/qa/2026-10-13-live-preview-mirror.md Finding 1 named the unreachable
# spec scenario «Событие показывает встречу»). The seat now exists: the pair
# loads through the connector's event service, the «Встреча» mirror reads
# through the same awaitable door the character mirror uses, and an event
# card save repaints the shown pair.


def _make_event_wiring(*, rows=None, event_rows=None, source=None):
    wiring = _make_wiring(
        _PinsService(), rows=rows or {}, event_rows=event_rows or {}
    )
    if source is not None:
        wiring.set_external_sources([source])
    return wiring


async def test_live_seat_seats_an_event_and_reads_its_encounter_mirror():
    """The mention anchor of an event inside preview text arrives as
    ``entity_requested("event", id)`` → this seat: the row loads through the
    event service, the module's awaitable «Встреча» door answers for the
    projected string id, the frame carries the pair and its mirror."""
    encounter = _MirrorSource(
        key="event", sections=(_section("Встреча"),), awaitable=True
    )
    wiring = _make_event_wiring(
        event_rows={7: _Event(7, "Полоса")}, source=encounter
    )

    assert await wiring._show_in_preview("event", 7) is True

    assert encounter.asks == [("event", "7")]
    assert wiring._preview_live == ("event", 7)
    assert wiring._preview_mirror == {("event", 7): ((_section("Встреча"),), ())}
    assert list(wiring._window.entity_preview)[-1] == ([], ("event", 7))
    # The middle column has no event tab, so the facade's sync request for a
    # seated event is its documented no-op (e2e-pinned in the preview
    # lifecycle guard).


async def test_event_reseat_is_a_silent_no_op():
    """«Повторный выбор ничего не делает» rides the event seat verbatim: the
    same live pair reloads nothing and pushes no frame."""
    wiring = _make_event_wiring(event_rows={7: _Event(7, "Полоса")})
    assert await wiring._show_in_preview("event", 7) is True
    frames = len(wiring._window.entity_preview)

    assert await wiring._show_in_preview("event", 7) is True

    assert len(wiring._window.entity_preview) == frames


async def test_vanished_event_keeps_the_live_pair_in_place():
    """The broken-mention posture for events: a pair the event service cannot
    answer seats nothing and pushes no frame."""
    wiring = _make_event_wiring(event_rows={})

    assert await wiring._show_in_preview("event", 99) is False

    assert wiring._preview_live is None
    assert list(wiring._window.entity_preview) == []


async def test_event_save_repaints_only_a_shown_pair():
    """«Обновление показанной сущности … перекрашивать секции» — the event
    twin of the entity-card save repaint: a shown pair reloads its row and
    mirror and pushes the frame; an event shown nowhere moves nothing."""
    source = _MirrorSource(key="event", sections=(_section("Встреча"),))
    wiring = _make_event_wiring(event_rows={7: _Event(7)}, source=source)
    await wiring._show_in_preview("event", 7)
    frames = len(wiring._window.entity_preview)
    saved = _Event(7, "Полоса-2")
    wiring._event_service.rows[7] = saved

    await wiring._repaint_event_in_preview(7)

    assert wiring._preview_rows[("event", 7)] is saved
    assert len(wiring._window.entity_preview) == frames + 1

    # An event shown nowhere: the membership check answers for the save.
    frames = len(wiring._window.entity_preview)
    await wiring._repaint_event_in_preview(11)
    assert len(wiring._window.entity_preview) == frames


async def test_event_save_repaint_is_quiet_when_the_row_vanished():
    """The repaint reads, a vanished row keeps the cached card (the row the
    column paints is never dropped by a repaint attempt)."""
    wiring = _make_event_wiring(event_rows={7: _Event(7)})
    await wiring._show_in_preview("event", 7)
    frames = len(wiring._window.entity_preview)
    wiring._event_service.rows.clear()

    await wiring._repaint_event_in_preview(7)

    assert wiring._preview_rows[("event", 7)] is not None
    assert len(wiring._window.entity_preview) == frames


async def test_restore_refreshes_the_pinned_mirrors():
    pins = _PinsService([("character", 1)])
    source = _MirrorSource(sections=(_section("Происхождение"),))
    wiring = _make_mirror_wiring(
        [source], rows={1: _Entity(1)}, pins_service=pins
    )

    await wiring.restore_preview_pins()

    assert wiring._preview_pins == [("character", 1)]
    assert source.asks == [("character", "1")]
    assert wiring._preview_mirror == {
        ("character", 1): ((_section("Происхождение"),), ())
    }


async def test_refresh_drops_the_pair_when_the_doors_fall_silent():
    """The mirror-less re-read (module switched off while the pair stays
    shown) replaces the entry with nothing — the pop branch of the refresh,
    the card losing its sections on the next frame."""
    source = _MirrorSource(sections=(_section("Происхождение"),))
    wiring = _make_mirror_wiring([source], rows={1: _Entity(1)})
    await wiring._refresh_preview_mirror(("character", 1))
    assert wiring._preview_mirror != {}

    source._visible = False
    await wiring._refresh_preview_mirror(("character", 1))

    assert wiring._preview_mirror == {}
