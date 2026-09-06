"""QML-facing state on the existing global-search view model (R4 §2)."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
        },
        {
            "kind": "result",
            "text": "Battle  [02 Январь 1200]",
            "type": "event",
            "id": 42,
            "dateText": "02 Январь 1200",
            "clickable": True,
        },
        {
            "kind": "sectionHeader",
            "text": "— Организации (1) —",
            "type": "",
            "id": None,
            "dateText": "",
            "clickable": False,
        },
        {
            "kind": "result",
            "text": "Guild",
            "type": "organization",
            "id": 7,
            "dateText": "",
            "clickable": True,
        },
    ]
    assert vm.listVisible is True


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
