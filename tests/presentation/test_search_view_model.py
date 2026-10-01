"""QML-facing state on the existing global-search view model (R4 §2)."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
