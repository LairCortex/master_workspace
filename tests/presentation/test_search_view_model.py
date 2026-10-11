"""QML-facing state on the existing global-search view model (R4 §2)."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain import entity_registry
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from tests.presentation.qml_helpers import track


def _vm(results=None):
    service = SimpleNamespace(search_all=AsyncMock(return_value=results or {}))
    return SearchViewModel(service), service


def test_short_or_empty_query_cancels_debounce_and_clears_rows(qtbot):
    vm, _ = _vm()
    vm.setQuery("Battle")
    assert vm.debounceActive is True

    vm.setQuery(" B ")
    assert vm.query == " B "
    assert vm.debounceActive is False
    assert vm.rows == []
    assert vm.listVisible is False

    vm.setQuery("")
    assert vm.rows == []
    assert vm.listVisible is False


def test_two_char_input_emits_after_300_ms_debounce(qtbot):
    vm, _ = _vm()
    requested = track(vm.searchRequested)

    vm.setQuery("  Ba  ")
    assert vm.debounceInterval == 300
    assert vm.debounceActive is True
    qtbot.waitUntil(lambda: requested == [("Ba",)], timeout=700)
    assert vm.debounceActive is False


def test_explicit_search_emits_immediately_and_cancels_debounce():
    vm, _ = _vm()
    requested = track(vm.searchRequested)

    vm.setQuery("  Battle  ")
    vm.requestSearch()
    assert requested == [("Battle",)]
    assert vm.debounceActive is False

    vm.setQuery("x")
    vm.requestSearch()
    assert requested == [("Battle",)]


async def test_empty_query_keeps_existing_domain_search_contract():
    vm, service = _vm()
    vm.results = {"events": [object()]}

    await vm.search("   ")

    service.search_all.assert_not_awaited()
    assert vm.results == {}
    assert vm.rows == []
    assert vm.listVisible is False


async def test_completed_empty_search_publishes_non_clickable_no_match_row():
    vm, _ = _vm({
        "events": [],
        "organizations": [],
        "characters": [],
        "items": [],
        "locations": [],
    })
    vm.setQuery("missing")

    await vm.search("missing")

    assert vm.rows == [{
        "kind": "noMatch",
        "text": "Ничего не найдено",
        "type": "",
        "id": None,
        "dateText": "",
        "clickable": False,
        "iconName": "",
    }]
    assert vm.listVisible is True


async def test_results_publish_headers_and_render_ready_identity_date_rows():
    event = SimpleNamespace(id=42, name="Battle", start_date=date(1200, 1, 2))
    org = SimpleNamespace(id=7, name="Guild")
    vm, _ = _vm({
        "events": [event],
        "organizations": [org],
        "characters": [],
        "items": [],
        "locations": [],
    })
    vm.setQuery("Ba")

    await vm.search("Ba")

    assert vm.rows == [
        {
            "kind": "sectionHeader",
            "text": "— События (1) —",
            "type": "",
            "id": None,
            "dateText": "",
            "clickable": False,
            # the section's glyph rides the row from the one type→icon map
            "iconName": "calendar-days",
        },
        {
            "kind": "result",
            "text": "Battle  [02 Январь 1200]",
            "type": "event",
            "id": 42,
            "dateText": "02 Январь 1200",
            "clickable": True,
            "iconName": "",
        },
        {
            "kind": "sectionHeader",
            "text": "— Организации (1) —",
            "type": "",
            "id": None,
            "dateText": "",
            "clickable": False,
            "iconName": "building",
        },
        {
            "kind": "result",
            "text": "Guild",
            "type": "organization",
            "id": 7,
            "dateText": "",
            "clickable": True,
            "iconName": "",
        },
    ]
    assert vm.listVisible is True


async def test_section_headers_carry_the_one_map_glyph_and_unknown_keys_stay_plain():
    # Lucide pass 2026-09-30: every section header's iconName comes from the
    # presentation.entity_icons map; a collection the registry does not know
    # keeps the tolerant caption fallback and paints no glyph.
    from app.domain.enums.entity_type import EntityType
    from app.presentation.entity_icons import icon_for

    payload = {
        collection: [SimpleNamespace(id=1, name="X", start_date=None)]
        for collection in ("events", "organizations", "characters", "items", "locations")
    }
    vm, _ = _vm(payload)
    await vm.search("x")
    headers = {row["text"]: row["iconName"] for row in vm.rows if row["kind"] == "sectionHeader"}
    for entity_type in entity_registry.SEARCH_TYPES:
        desc = entity_registry.descriptor(entity_type)
        caption = f"— {desc.plural_label} (1) —"
        assert headers[caption] == icon_for(entity_type)
    assert icon_for(EntityType.EVENT) == "calendar-days"

    vm, _ = _vm({"ghosts": [SimpleNamespace(name="Boo")]})
    await vm.search("x")
    assert vm.rows[0]["kind"] == "sectionHeader"
    assert vm.rows[0]["iconName"] == ""


async def test_only_result_rows_select_and_selection_hides_list():
    event = SimpleNamespace(id=42, name="Battle", start_date=None)
    vm, _ = _vm({"events": [event]})
    vm.setQuery("Ba")
    await vm.search("Ba")
    selected = track(vm.resultSelected)

    vm.select(-1)
    vm.select(99)
    vm.select(0)
    assert selected == []
    assert vm.listVisible is True

    vm.select(1)
    assert selected == [("event", 42)]
    assert vm.listVisible is False


async def test_activate_shares_the_row_guard_and_hides_the_list():
    """NRI-0022 task 6.2: the double-click channel answers the SAME row
    contract — headers/no-match/out-of-range stay silent — and on a result
    row it emits resultActivated (the edit route) plus collapse."""
    event = SimpleNamespace(id=42, name="Battle", start_date=None)
    vm, _ = _vm({"events": [event]})
    vm.setQuery("Ba")
    await vm.search("Ba")
    activated = track(vm.resultActivated)

    vm.activate(-1)
    vm.activate(99)
    vm.activate(0)  # the section header row
    assert activated == []
    assert vm.listVisible is True

    vm.activate(1)
    assert activated == [("event", 42)]
    assert vm.listVisible is False


def test_double_click_interval_is_the_platform_one(qtbot):
    """NRI-0022 task 6.2: the island's single-click hold rides the platform
    double-click interval (the value QGuiApplication reports), not a literal."""
    from PySide6.QtGui import QGuiApplication

    vm, _ = _vm()
    assert vm.doubleClickIntervalMs == QGuiApplication.instance().doubleClickInterval()
    assert vm.doubleClickIntervalMs > 0


async def test_result_date_carries_the_bc_era_suffix():
    """Spec «Отображение эры» (add-era-aware-dates): search is one of the places
    an entity's date is shown, so a BC start_date prints with the suffix."""
    event = SimpleNamespace(
        id=42, name="Battle", start_date=date(44, 3, 5), start_bc=True
    )
    vm, _ = _vm({
        "events": [event],
        "organizations": [],
        "characters": [],
        "items": [],
        "locations": [],
    })
    vm.setQuery("Ba")

    await vm.search("Ba")

    result_row = next(row for row in vm.rows if row["kind"] == "result")
    assert result_row["text"] == "Battle  [05 Март 44 г. до н.э.]"
    assert result_row["dateText"] == "05 Март 44 г. до н.э."


# ── NRI-0023 task 8.2: the sub-event prefix and the time tail ────────────────


async def test_sub_event_row_is_named_through_its_parent_and_stays_clickable():
    """Spec global-search «Подсобытие названо через родителя»: the wiring's
    id → имя card names a parent the query never matched; the row keeps the
    child's own identity and stays the ordinary clickable result."""
    from app.presentation.viewmodels.search_viewmodel import SearchViewModel

    child = SimpleNamespace(
        id=43, name="Встреча в таверне", start_date=None, parent_id=42
    )
    service = SimpleNamespace(search_all=AsyncMock(return_value={"events": [child]}))
    vm = SearchViewModel(service)
    vm.setQuery("Встреча")

    await vm.search("Встреча", {42: "Бой у реки"})

    result_row = next(row for row in vm.rows if row["kind"] == "result")
    assert result_row["text"] == "Встреча в таверне · Бой у реки"
    assert (result_row["type"], result_row["id"], result_row["clickable"]) == (
        "event",
        43,
        True,
    )
    selected = track(vm.resultSelected)
    vm.select(vm.rows.index(result_row))
    assert selected == [("event", 43)]


async def test_parent_the_card_cannot_names_adds_no_prefix():
    """A link the id → имя card cannot resolve (no card at all, or a stale
    id) leaves the row the plain name — the prefix is naming, never noise."""
    from app.presentation.viewmodels.search_viewmodel import SearchViewModel

    child = SimpleNamespace(id=43, name="Встреча", start_date=None, parent_id=42)
    service = SimpleNamespace(search_all=AsyncMock(return_value={"events": [child]}))
    vm = SearchViewModel(service)

    await vm.search("Встреча")  # no card handed in
    rows_no_card = [row for row in vm.rows if row["kind"] == "result"]
    assert rows_no_card[0]["text"] == "Встреча"

    await vm.search("Встреча", {99: "Другое событие"})  # stale parent id
    rows_stale = [row for row in vm.rows if row["kind"] == "result"]
    assert rows_stale[0]["text"] == "Встреча"


async def test_time_tail_rides_the_search_row_date():
    """Spec global-search «Время в дате строки» (the event-time tail on this
    surface): a found event with time 9:05 prints the date with «, 09:05»,
    an event without it prints the date word-for-word as before."""
    from app.domain.time_of_day import TimeOfDay
    from app.presentation.viewmodels.search_viewmodel import SearchViewModel

    timed = SimpleNamespace(
        id=1, name="Засека", start_date=date(1200, 1, 2), start_time=TimeOfDay(9, 5)
    )
    plain = SimpleNamespace(id=2, name="Дозор", start_date=date(1200, 1, 2))
    service = SimpleNamespace(search_all=AsyncMock(return_value={"events": [timed, plain]}))
    vm = SearchViewModel(service)

    await vm.search("За")

    rows = {row["id"]: row for row in vm.rows if row["kind"] == "result"}
    assert rows[1]["text"] == "Засека  [02 Январь 1200, 09:05]"
    assert rows[1]["dateText"] == "02 Январь 1200, 09:05"
    assert rows[2]["text"] == "Дозор  [02 Январь 1200]"


# ── add-dnd-game-face task 3.4: external rows in the same list ─────────────


class _ExtHit:
    def __init__(self, source_id, name, origin=""):
        self.source_id = source_id
        self.name = name
        self.origin = origin


@pytest.fixture()
def restore_external_section():
    saved = dict(entity_registry._EXTERNAL)
    yield
    entity_registry._EXTERNAL.clear()
    entity_registry._EXTERNAL.update(saved)


def _register_feat_spell():
    entity_registry.register_external(
        [
            entity_registry.ExternalTypeDescriptor(
                key="dd_feat", label="Черта", plural_label="Черты", icon_key="scroll"
            ),
            entity_registry.ExternalTypeDescriptor(
                key="dd_spell", label="Заклинание", plural_label="Заклинания",
                icon_key="sparkles",
            ),
        ]
    )


async def test_external_group_publishes_signed_clickable_rows(qtbot):
    """Spec dnd-reference-records «каждая подписана набором-источником» +
    global-search подпись группы: caption from the registered descriptor,
    row text «Имя [Набор]», the row's id is the STRING source_id under the
    descriptor's key; no origin — the name alone; a source_id-less hit is
    not clickable (there is nothing to open)."""
    _register_feat_spell()
    vm, _ = _vm({
        "dd_feat": [
            _ExtHit("srd/lucky", "Везучесть", "SRD 5.1"),
            _ExtHit("hb/lucky", "Везучесть", "Мой набор"),
            _ExtHit("", "Без набора"),
        ],
    })

    await vm.search("вез")

    headers = [r for r in vm.rows if r["kind"] == "sectionHeader"]
    assert [h["text"] for h in headers] == ["— Черты (3) —"]
    assert headers[0]["iconName"] == "scroll"  # glyph from the descriptor
    results = [r for r in vm.rows if r["kind"] == "result"]
    assert [(r["text"], r["type"], r["id"], r["clickable"]) for r in results] == [
        ("Везучесть  [SRD 5.1]", "dd_feat", "srd/lucky", True),
        ("Везучесть  [Мой набор]", "dd_feat", "hb/lucky", True),
        ("Без набора", "dd_feat", "", False),
    ]


async def test_external_row_gestures_ride_the_string_channel(qtbot):
    """Дизайн Д4: both result gestures of an external row — select AND
    activate — ride ``externalResultSelected`` (the record is read-only, the
    edit gesture has nowhere to go); kernel rows keep their channels intact
    beside them."""
    _register_feat_spell()
    vm, _ = _vm({
        "dd_spell": [_ExtHit("srd/fire-ball", "Fire ball", "SRD")],
        "events": [SimpleNamespace(id=7, name="Бой", start_date=date(1200, 1, 1))],
    })
    externals = track(vm.externalResultSelected)
    activated = track(vm.resultActivated)
    selected = track(vm.resultSelected)

    await vm.search("fire")
    external_index = next(i for i, r in enumerate(vm.rows) if r["id"] == "srd/fire-ball")
    vm.select(external_index)
    assert externals == [("dd_spell", "srd/fire-ball")]
    assert selected == [] and activated == []
    assert vm.listVisible is False

    # The SECOND gesture of the same external row (double click) is the same
    # channel too — the read-only record has no edit route to open.
    vm._set_list_visible(True)
    vm.activate(external_index)
    assert externals == [
        ("dd_spell", "srd/fire-ball"),
        ("dd_spell", "srd/fire-ball"),
    ]
    assert activated == []

    vm._set_list_visible(True)
    await vm.search("бой")
    kernel_index = next(i for i, r in enumerate(vm.rows) if r["id"] == 7)
    vm.activate(kernel_index)
    assert activated == [("event", 7)]
    # external channel untouched by the kernel row's gestures
    assert all(pair == ("dd_spell", "srd/fire-ball") for pair in externals)
    assert selected == []
