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
