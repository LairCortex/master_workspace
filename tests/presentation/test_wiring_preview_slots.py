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

    def show_slots(self, pins, live) -> None:
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
) -> ApplicationWiring:
    """The connector with exactly what the preview-slot paths touch — the
    same duck construction the sheet-stack wiring tests use."""
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
        None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
        preview_pins_service=pins_service,
    )


# ── task 5.2: restore (design Д3) ────────────────────────────────────────────


async def test_restore_loads_only_resolvable_pairs_and_never_rewrites():
    service = _PinsService([("character", 1), ("character", 99), ("event", 1)])
    wiring = _make_wiring(service, rows={1: _Entity(1)})

    await wiring.restore_preview_pins()

    # The vanished row and the unknown type dropped silently, order kept;
    # storage stays byte-identical — no background repair write (Д3).
    assert wiring._preview_pins == [("character", 1)]
    assert service.saves == []
    # The frame for the restored column: pins with the loaded row, no live.
    assert list(wiring._window.entity_preview) == [([("character", 1)], None)]


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

    def show_slots(self, pins, live) -> None:
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
