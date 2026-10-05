"""NRI-0025 task 2.1/2.2 pins — the preview column as a pane LIST.

The unit file pins the per-card composition; this file pins what the split
into ``EntityCardViewModel`` + a list ``EntityPreviewViewModel`` adds and must
NOT change:

* the regression pin «zero pins renders bit-for-bit like before»: the expected
  values were captured from the pre-NRI-0025 ``EntityPreviewViewModel``
  (property-for-property dump of the current single-entity code) and are
  embedded verbatim below — a zero-pins frame must answer them exactly;
* the empty column (``panes`` empty, live area empty, single word title);
* the one «now» subscription repainting EVERY card with ONE ``contentChanged``;
* the pane flags (``pinned``/``slotIndex``/identity pair) and the
  ``liveEmpty`` sign;
* the pane gestures out: ``requestPinToggle`` by pair and the picture request
  carrying its pane — with the facade building the viewer from the entity of
  the pane that raised it (the 4096 slot preserved);
* the facade frames: ``show_slots``/``clear`` (the connector's two feed
  channels since group 5 — the transitional ``show_entity`` bridge left
  with the switch).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.presentation.viewmodels.entity_preview_view_model import (
    PIN_STATE_LIMIT,
    PIN_STATE_UNPIN,
    EntityPreviewViewModel,
)
from app.presentation.views import entity_preview as preview_module
from app.presentation.views.entity_preview import EntityPreviewWidget

# ── fixtures (the same duck payloads the VM unit file uses) ──────────────────


class _NowStub(QObject):
    nowChanged = Signal()

    def __init__(self, coord, is_bc: bool = False) -> None:
        super().__init__()
        self.coord = coord
        self.is_bc = is_bc


def _desc(characteristics: str = "", backstory: str = ""):
    return SimpleNamespace(characteristics=characteristics, backstory=backstory)


def _entity(entity_type: str = "character", **overrides):
    base = dict(
        id=4,
        name="Банн",
        rating=8,
        start_date=date(1200, 1, 1),
        end_date=None,
        start_bc=False,
        end_bc=False,
        description=_desc("Крепкий", "Долгая история"),
        music_url="https://example.com/song",
        image_ref=None,
        items=[],
        locations=[],
        organizations=[],
    )
    if entity_type == "character":
        base["personality"] = "Упрямый"
        base["tasks"] = "Найти брата"
    if entity_type == "organization":
        base["tasks"] = "Собрать войско"
    if entity_type == "location":
        base["tasks"] = "Держать оборону"
    base.update(overrides)
    return SimpleNamespace(**base)


def _linked_character():
    character = _entity()
    character.items = [SimpleNamespace(id=11, name="Кинжал")]
    character.locations = [
        SimpleNamespace(id=12, name="Пещера"),
        SimpleNamespace(id=13, name="Замок"),
    ]
    return character


# The value dump of the PRE-NRI-0025 EntityPreviewViewModel (the single-entity
# code, captured via its public properties before the split — see the task
# message). Keys: the old scalar face plus shownEntityId; the new column must
# answer the same values from its single live pane. THE ONE DOCUMENTED DELTA:
# the band title also carries the entity name since the reader's fix of
# 2026-10-03 (the headline must identify WHICH card of the up-to-four-column
# it is) — every other value stays the verbatim pre-split capture.
_PRE_SPLIT_SNAPSHOT: dict[str, dict] = {
    "empty": {
        "ageText": "",
        "dateText": "",
        "hasEntity": False,
        "imageSource": "",
        "musicUrl": "",
        "nameText": "",
        "ratingText": "",
        "relatedSections": [],
        "sections": [],
        "shownEntityId": None,
        "title": "Карточка",
    },
    "character_with_now": {
        "ageText": "Возраст: 3 года",
        "dateText": "01 Январь 1200 — Бессрочно",
        "hasEntity": True,
        "imageSource": "",
        "musicUrl": "https://example.com/song",
        "nameText": "Банн",
        "ratingText": "Рейтинг: 8/20",
        "relatedSections": [],
        "sections": [
            {"html": "Крепкий", "key": "characteristics", "label": "Характеристики"},
            {"html": "Долгая история", "key": "backstory", "label": "Предыстория"},
            {"html": "Упрямый", "key": "personality", "label": "Личность"},
            {"html": "Найти брата", "key": "tasks", "label": "Задачи"},
        ],
        "shownEntityId": 4,
        "title": "Карточка: Персонаж",
    },
    "character_linked_mentioned": {
        "ageText": "Возраст: 3 года",
        "dateText": "01 Январь 1200 — Бессрочно",
        "hasEntity": True,
        "imageSource": "",
        "musicUrl": "https://example.com/song",
        "nameText": "Банн",
        "ratingText": "Рейтинг: 8/20",
        "relatedSections": [
            {
                "key": "items",
                "label": "Предметы",
                "rows": [{"id": 11, "name": "Кинжал", "type": "item"}],
            },
            {
                "key": "locations",
                "label": "Локации",
                "rows": [
                    {"id": 12, "name": "Пещера", "type": "location"},
                    {"id": 13, "name": "Замок", "type": "location"},
                ],
            },
        ],
        "sections": [
            {"html": "Крепкий", "key": "characteristics", "label": "Характеристики"},
            {
                "html": "Сражались с <a href=\"nri://organization/2\">Волк</a>!",
                "key": "backstory",
                "label": "Предыстория",
            },
            {"html": "Упрямый", "key": "personality", "label": "Личность"},
            {"html": "Найти брата", "key": "tasks", "label": "Задачи"},
        ],
        "shownEntityId": 4,
        "title": "Карточка: Персонаж",
    },
    "item_bc_time": {
        "ageText": "",
        "dateText": "01 Январь 1200 г. до н.э., 09:05 — 07 Июнь 1205",
        "hasEntity": True,
        "imageSource": "",
        "musicUrl": "https://example.com/song",
        "nameText": "Меч",
        "ratingText": "Рейтинг: 8/20",
        "relatedSections": [],
        "sections": [
            {"html": "Крепкий", "key": "characteristics", "label": "Характеристики"},
            {"html": "Долгая история", "key": "backstory", "label": "Предыстория"},
        ],
        "shownEntityId": 4,
        "title": "Карточка: Предмет",
    },
}

# The pane keys the snapshot's scalar half covers (the dict half is compared
# through the same key names).
_SCALAR_MIRROR: tuple[tuple[str, str], ...] = (
    ("title", "title"),
    ("nameText", "name_text"),
    ("ratingText", "rating_text"),
    ("dateText", "date_text"),
    ("ageText", "age_text"),
    ("musicUrl", "music_url"),
    ("imageSource", "image_source"),
    ("sections", "sections"),
    ("relatedSections", "related_sections"),
)


def _snapshot_cases():
    from app.domain.time_of_day import TimeOfDay

    return {
        "empty": (None, None, None),
        "character_with_now": (date(1203, 1, 1), "character", _entity()),
        "character_linked_mentioned": (
            date(1203, 1, 1),
            "character",
            _entity(
                description=_desc("Крепкий", "Сражались с @[Волк](organization:2)!"),
                items=[SimpleNamespace(id=11, name="Кинжал")],
                locations=[
                    SimpleNamespace(id=12, name="Пещера"),
                    SimpleNamespace(id=13, name="Замок"),
                ],
            ),
        ),
        "item_bc_time": (
            None,
            "item",
            _entity(
                "item",
                name="Меч",
                start_bc=True,
                start_time=TimeOfDay(9, 5),
                end_date=date(1205, 6, 7),
            ),
        ),
    }


# ── task 2.1: the regression pin — zero pins renders bit-for-bit like before ─


@pytest.mark.parametrize("case", sorted(_PRE_SPLIT_SNAPSHOT))
def test_zero_pins_the_column_answers_the_pre_split_values(case):
    now_coord, type_key, entity = _snapshot_cases()[case]
    expected = _PRE_SPLIT_SNAPSHOT[case]

    vm = EntityPreviewViewModel(now_vm=None if now_coord is None else _NowStub(now_coord))
    if entity is None:
        vm.clear()
        assert vm.panes == []
        # The pre-split «nothing shown» face: no card, the plain-word empty
        # state — its visible half (the «Карточка» band, the hint) is the
        # zero-pane literal pinned in test_entity_preview_island.py.
        assert bool(vm.liveEmpty) is True
    else:
        vm.show_slots([], (type_key, entity))
        # hasEntity / shownEntityId answer through the list face now: exactly
        # one pane, live-flagged, carrying the old shown pair.
        assert len(vm.panes) == 1
        pane = vm.panes[0]
        assert (pane["pinned"], pane["slotIndex"]) == (False, 0)
        assert pane["entityId"] == expected["shownEntityId"]
        # Every render-ready text of the pre-split single card rides the pane
        # dict value-for-value (this is the shape group 4's QML paints from).
        for pane_key, _card_attr in _SCALAR_MIRROR:
            assert pane[pane_key] == expected[pane_key], pane_key


# ── task 2.1: the empty column ───────────────────────────────────────────────


def test_an_empty_column_is_a_signalled_empty_pane_list():
    vm = EntityPreviewViewModel()
    changed = []
    vm.contentChanged.connect(lambda: changed.append(1))
    assert vm.panes == []
    assert bool(vm.liveEmpty) is True
    # (The fully empty column's «Карточка» band and hint are the island's
    # zero-pane literals — pinned offscreen in test_entity_preview_island.py.)

    vm.clear()  # re-clearing re-announces exactly once (the old posture)
    assert changed == [1]


def test_live_empty_flag_tracks_the_live_half_only():
    vm = EntityPreviewViewModel()
    vm.show_slots([("character", _entity(id=1))], None)
    # Pins without a live entity: the column shows one card, the live area is
    # empty (the hint block under the pins — spec «Пустая живая область без
    # заголовка»).
    assert len(vm.panes) == 1
    assert bool(vm.liveEmpty) is True

    vm.show_slots([("character", _entity(id=1))], ("character", _entity(id=2)))
    assert bool(vm.liveEmpty) is False


# ── task 2.1: the age follows «now» in EVERY card ────────────────────────────


def test_one_now_broadcast_recounts_the_age_of_every_pane():
    now = _NowStub(date(1203, 1, 1))
    vm = EntityPreviewViewModel(now_vm=now)
    changed = []
    vm.contentChanged.connect(lambda: changed.append(1))
    vm.show_slots(
        [("character", _entity(id=1)), ("character", _entity(id=2, start_date=date(1201, 1, 1)))],
        ("character", _entity(id=3, start_date=date(1199, 1, 1))),
    )
    changed.clear()

    now.coord = date(1205, 1, 1)
    now.nowChanged.emit()

    ages = [pane["ageText"] for pane in vm.panes]
    assert ages == ["Возраст: 5 лет", "Возраст: 4 года", "Возраст: 6 лет"]
    # ONE subscription on the column VM — one broadcast, one repaint signal
    # however many cards the frame holds (design Д2).
    assert changed == [1]


# ── task 2.1/2.2: the pane flags ─────────────────────────────────────────────


def test_panes_carry_the_slot_flags_and_identity_in_pin_order():
    vm = EntityPreviewViewModel()
    vm.show_slots(
        [("character", _entity(id=7)), ("location", _entity("location", id=8))],
        ("item", _entity("item", id=9)),
    )
    assert [
        (pane["pinned"], pane["slotIndex"], pane["entityType"], pane["entityId"])
        for pane in vm.panes
    ] == [
        (True, 0, "character", 7),
        (True, 1, "location", 8),
        (False, 2, "item", 9),
    ]


# ── task 2.2: the pane gestures out of the VM ────────────────────────────────


def test_requestPinToggle_carries_the_pair_and_the_current_state_both_ways():
    vm = EntityPreviewViewModel()
    vm.show_slots([("character", _entity(id=7))], ("character", _entity(id=9)))
    emits = []
    vm.pinToggleRequested.connect(lambda *args: emits.append(args))

    vm.requestPinToggle("character", 9, False)  # the live card's pin
    vm.requestPinToggle("character", 7, True)   # a pinned card's pin
    assert emits == [("character", 9, False), ("character", 7, True)]


def test_image_request_names_the_pane_that_raised_it():
    vm = EntityPreviewViewModel()
    vm.show_slots([("location", _entity("location", id=8))], ("character", _entity()))
    opens = []
    vm.imageRequested.connect(lambda *args: opens.append(args))

    vm.requestImageFor("location", 8, True)    # the pinned pane's picture
    vm.requestImageFor("character", 4, False)  # the live pane's picture
    assert opens == [("location", 8, True), ("character", 4, False)]


def test_an_image_request_for_a_pair_that_is_not_a_pane_is_silent():
    vm = EntityPreviewViewModel()
    vm.show_slots([], ("character", _entity()))
    opens = []
    vm.imageRequested.connect(lambda *args: opens.append(args))

    vm.requestImageFor("character", 4, True)   # right pair, wrong half
    vm.requestImageFor("location", 8, False)   # no such pane at all
    assert opens == []


def test_pane_entity_resolves_each_half_of_a_doubled_pair():
    # The duplicate scenario (spec «Дубль закреплённой сущности»): the same
    # pair pinned AND live — the request's pinned flag picks the copy.
    pinned_entity = _entity(id=4)
    live_entity = _entity(id=4)
    assert pinned_entity is not live_entity
    vm = EntityPreviewViewModel()
    vm.show_slots([("character", pinned_entity)], ("character", live_entity))
    assert vm.pane_entity("character", 4, True) is pinned_entity
    assert vm.pane_entity("character", 4, False) is live_entity
    assert vm.pane_entity("character", 404, False) is None


# ── task 2.2: the facade — frames, pin relay, per-pane viewer ────────────────


class _ViewerRecorder:
    calls: list = []

    def __init__(self, original, preview, parent=None, theme=None):
        type(self).calls.append((original, preview, parent, theme))


@pytest.fixture()
def viewer_recorder(monkeypatch):
    _ViewerRecorder.calls = []
    monkeypatch.setattr(preview_module, "ImageViewerDialog", _ViewerRecorder)
    monkeypatch.setattr(preview_module, "load_entity_original", lambda e: f"original-{e.name}")
    monkeypatch.setattr(
        preview_module,
        "load_entity_preview",
        lambda e, slot_size: (f"preview-{e.name}", slot_size),
    )
    return _ViewerRecorder.calls


def _widget(qtbot) -> EntityPreviewWidget:
    widget = EntityPreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(420, 900)
    widget.show()
    QApplication.processEvents()
    return widget


def test_the_facade_frames_delegate_to_the_slot_vm(qtbot):
    widget = _widget(qtbot)
    widget.show_slots(
        [("character", _entity(id=1))], ("item", _entity("item", id=2, name="Меч"))
    )
    panes = widget.vm.panes
    assert [(p["pinned"], p["nameText"]) for p in panes] == [(True, "Банн"), (False, "Меч")]

    # The live card alone is a zero-pins frame — the single-card column
    # the connector pushes with nothing pinned.
    widget.show_slots([], ("location", _entity("location", id=3, name="Пещера")))
    assert [(p["pinned"], p["nameText"]) for p in widget.vm.panes] == [(False, "Пещера")]

    widget.clear()
    assert widget.vm.panes == []


def test_the_facade_relays_the_pin_channel(qtbot):
    widget = _widget(qtbot)
    widget.show_slots([("character", _entity(id=7))], None)
    pins = []
    widget.pin_toggle_requested.connect(lambda *args: pins.append(args))
    widget.vm.requestPinToggle("character", 7, True)
    assert pins == [("character", 7, True)]


def test_the_viewer_is_built_from_the_entity_of_the_requesting_pane(
    qtbot, viewer_recorder
):
    pinned = _entity("location", id=8, name="Замок")
    live = _entity("character", name="Банн")
    widget = _widget(qtbot)
    widget.show_slots([("location", pinned)], ("character", live))

    requested: list = []
    widget.sheet_requested.connect(requested.append)
    widget.vm.requestImageFor("character", 4, False)
    widget.vm.requestImageFor("location", 8, True)

    assert len(requested) == 2
    originals = [call[0] for call in viewer_recorder]
    assert originals == ["original-Банн", "original-Замок"]
    # The 4096 slot the card's viewer uses — preserved per pane (task 2.2).
    assert [call[1] for call in viewer_recorder] == [
        ("preview-Банн", 4096),
        ("preview-Замок", 4096),
    ]
    assert [call[2] for call in viewer_recorder] == [widget, widget]


def test_an_image_signal_for_a_vanished_pane_opens_nothing(qtbot, viewer_recorder):
    widget = _widget(qtbot)
    widget.show_slots([], ("character", _entity()))
    requested: list = []
    widget.sheet_requested.connect(requested.append)
    # The pair stopped being shown between the press and the delivery.
    widget.clear()
    widget.vm.imageRequested.emit("character", 4, False)
    assert requested == []
    assert viewer_recorder == []


# ── 2026-10-03 scroll-reset fix: frames carry slot identity (Python half) ─────
#
# The bug (docs/qa/2026-10-03-preview-scroll-reset.md): every frame rebuilt
# every card, so QML tore down and refilled all panes and each fresh Flickable
# started at the top. The fix's Python invariant: a frame re-presenting an
# unchanged slot reuses its card whole (rev included — the island's scroll
# memory validates offsets against it), and a frame answering an unchanged one
# announces nothing at all.

def test_unchanged_slots_survive_a_frame_without_being_rebuilt():
    vm = EntityPreviewViewModel()
    a = _entity(id=1)
    b = _entity("location", id=2)
    x = _entity("item", id=3, name="Меч")
    changed = []
    vm.contentChanged.connect(lambda: changed.append(1))

    vm.show_slots([("character", a), ("location", b)], ("item", x))
    built = list(vm._cards)
    assert changed == [1]

    # A new live selection: the two pins ride along as the very same card
    # objects (the island restores their scroll from the same revs), only
    # the live slot is a new construction.
    y = _entity("item", id=9, name="Кинжал")
    vm.show_slots([("character", a), ("location", b)], ("item", y))
    assert changed == [1, 1]
    assert vm._cards[0] is built[0]
    assert vm._cards[1] is built[1]
    assert vm._cards[2] is not built[2]


def test_an_identical_frame_announces_nothing():
    vm = EntityPreviewViewModel()
    a = _entity(id=1)
    x = _entity(id=9)
    vm.show_slots([("character", a)], ("character", x))
    changed = []
    vm.contentChanged.connect(lambda: changed.append(1))

    # The same pairs with the same cached rows re-presented (the connector
    # may push a frame for an unrelated reason): nothing to repaint, so no
    # notify — the QML scene, scrolls included, is never touched.
    vm.show_slots([("character", a)], ("character", x))
    assert changed == []


def test_a_saved_pair_rebuilds_only_that_card():
    vm = EntityPreviewViewModel()
    a = _entity(id=1)
    b = _entity(id=2)
    vm.show_slots([("character", a), ("character", b)], None)
    built = list(vm._cards)

    # The next frame carries the saved content under the pair: that slot is a
    # new construction, its neighbour — same row, same rendered fields —
    # rides on.
    a_saved = _entity(id=1, name="Банн II")
    vm.show_slots([("character", a_saved), ("character", b)], None)
    assert vm._cards[0] is not built[0]
    assert vm._cards[1] is built[1]
    assert vm.panes[0]["nameText"] == "Банн II"
    assert vm.panes[1]["nameText"] == "Банн"


def test_an_in_place_row_update_rebuilds_the_card():
    # The mechanism the e2e save test pins: the service updates the session's
    # identity-mapped row IN PLACE mid-save, so the connector hands back the
    # very same object with new values. Object identity must not lull the
    # frame into reusing the stale card — the rendered-fields fingerprint is
    # what catches the edit (spec «Сохранение карточки обновляет
    # предпросмотр»).
    vm = EntityPreviewViewModel()
    a = _entity(id=1)
    vm.show_slots([("character", a)], None)
    built = vm._cards[0]
    changed = []
    vm.contentChanged.connect(lambda: changed.append(1))

    a.name = "Банн-2"  # the identity map mutates the row under the card
    vm.show_slots([("character", a)], None)
    assert vm._cards[0] is not built
    assert vm.panes[0]["nameText"] == "Банн-2"
    assert changed == [1]


def test_a_relation_rename_in_place_rebuilds_the_card():
    # Same fingerprint guard on the relations half: a related row renamed in
    # place moves the host card's compact section, so the card is rebuilt.
    vm = EntityPreviewViewModel()
    character = _entity(id=1)
    character.items = [SimpleNamespace(id=11, name="Кинжал")]
    vm.show_slots([("character", character)], None)
    built = vm._cards[0]

    character.items[0].name = "Меч"
    vm.show_slots([("character", character)], None)
    assert vm._cards[0] is not built
    [[row]] = [section["rows"] for section in vm.panes[0]["relatedSections"]]
    assert row["name"] == "Меч"


def test_panes_carry_the_slot_key_and_the_construction_rev():
    vm = EntityPreviewViewModel()
    pinned = _entity(id=4)
    live = _entity(id=4)
    vm.show_slots([("character", pinned)], ("character", live))
    # The same pair in both halves is two slots with two keys (the duplicate
    # scenario must never share one scroll memory).
    assert [pane["slotKey"] for pane in vm.panes] == [
        "character/4#pinned",
        "character/4#live",
    ]
    pinned_rev, live_rev = (pane["rev"] for pane in vm.panes)
    assert pinned_rev != live_rev  # every construction stamps its own rev

    # A reused card keeps its rev (the remembered offset stays valid); a
    # card rebuilt from a fresh row carries a new one (the remembered offset
    # belonged to the old content and must not be restored).
    vm.show_slots(
        [("character", _entity(id=4, name="Банн II"))], ("character", live)
    )
    pin_after, live_after = vm.panes
    assert pin_after["rev"] != pinned_rev
    assert live_after["rev"] == live_rev


def test_a_live_pin_word_change_rebuilds_only_the_live_card():
    vm = EntityPreviewViewModel()
    pins = [_entity(id=i) for i in (1, 2, 3)]
    live = _entity(id=9)
    vm.show_slots([("character", e) for e in pins], ("character", live))
    assert vm.panes[-1]["pinState"] == PIN_STATE_LIMIT  # a fourth live one
    built = list(vm._cards)

    # Unpinning a pin frees the capacity: the live card's authored word
    # changes (its pin becomes actionable), so THAT card is a new
    # construction while the surviving pins ride on.
    vm.show_slots(
        [("character", pins[0]), ("character", pins[1])], ("character", live)
    )
    assert vm.panes[-1]["pinState"] == PIN_STATE_UNPIN
    assert vm._cards[0] is built[0]
    assert vm._cards[1] is built[1]
    assert vm._cards[-1] is not built[-1]


def test_the_pin_order_is_part_of_the_frame():
    vm = EntityPreviewViewModel()
    a = _entity(id=1)
    b = _entity(id=2)
    vm.show_slots([("character", a), ("character", b)], None)
    changed = []
    vm.contentChanged.connect(lambda: changed.append(1))

    # A reshuffle reuses both cards but moves them between slots — the list
    # changed and must re-announce in the new order (the reused cards carry
    # their new positions).
    vm.show_slots([("character", b), ("character", a)], None)
    assert changed == [1]
    assert [pane["entityId"] for pane in vm.panes] == [2, 1]
    assert [pane["slotIndex"] for pane in vm.panes] == [0, 1]
    assert [(c.pinned, c.slot_index) for c in vm._cards] == [(True, 0), (True, 1)]
