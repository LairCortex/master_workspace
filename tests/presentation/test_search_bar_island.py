"""Real QML-island and thin-facade contracts for the R4 search panel."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PySide6.QtGui import QAccessible
from PySide6.QtQuickWidgets import QQuickWidget

from app.presentation import qml as qml_shell
from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.views.search_bar import SearchBar
from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    find_items,
    island_rows,
    track,
    walk_items,
)

ROOT_QML = Path(qml_shell.__file__).resolve().parent / "SearchBarRoot.qml"

OBJECT_NAMES = (
    "searchBarRoot",
    "searchInput",
    "searchButton",
    "searchResultsList",
)


def make_runtime(tmp_path, theme):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    if theme != "dark":
        prefs.save(UiPrefs(theme=theme))
    return ThemeRuntime(prefs=prefs, tokens_path=tokens_file_path())


def _vm(results=None):
    service = SimpleNamespace(search_all=AsyncMock(return_value=results or {}))
    return SearchViewModel(service)


def _bar(qtbot, tmp_path, vm=None):
    bar = SearchBar(vm or _vm(), theme=make_runtime(tmp_path, "dark"))
    qtbot.addWidget(bar)
    bar.resize(640, 360)
    bar.show()
    qtbot.waitExposed(bar)
    return bar


def _all_object_names(bar) -> set[str]:
    return {bar.quick.rootObject().objectName()} | {
        item.objectName() for item in walk_items(bar.quick.rootObject())
    }


def test_root_exists_and_all_interactive_controls_have_object_names(qtbot, tmp_path):
    bar = _bar(qtbot, tmp_path)
    assert ROOT_QML.is_file()
    assert isinstance(bar.quick, QQuickWidget)
    names = _all_object_names(bar)
    for name in OBJECT_NAMES:
        assert name in names


def test_search_input_accessibility_name_other_controls_untouched(qtbot, tmp_path):
    """nri-0012 task 3.1: the search field is named «Поиск по всем сущностям»
    through the accessibility interface; the neighbouring text button keeps
    the stock face (offscreen: empty name slot, caption in ``text``)."""
    bar = _bar(qtbot, tmp_path)

    field = QAccessible.queryAccessibleInterface(find_item(bar.quick, "searchInput"))
    assert field is not None
    assert field.role() == QAccessible.Role.EditableText
    assert field.text(QAccessible.Name) == "Поиск по всем сущностям"

    button_item = find_item(bar.quick, "searchButton")
    button = QAccessible.queryAccessibleInterface(button_item)
    assert button is not None
    assert button.role() == QAccessible.Role.Button
    assert button.text(QAccessible.Name) == ""
    assert button_item.property("text") == "Найти"


def test_facade_uses_child_context_with_only_vm_and_palette(qtbot, tmp_path):
    vm = _vm()
    bar = _bar(qtbot, tmp_path, vm)

    assert bar._context.parentContext() is bar._engine.rootContext()
    assert bar._context.contextProperty("searchBarVm") is vm
    assert bar._context.contextProperty("islandPalette") is bar._palette
    assert bar._context.contextProperty("tooltipBridge") is None
    assert bar._context.contextProperty("service") is None
    assert bar._context.contextProperty("facade") is None
    assert bar._engine.rootContext().contextProperty("searchBarVm") is None
    assert bar._engine.rootContext().contextProperty("islandPalette") is None


def test_input_debounce_and_explicit_button_keep_public_search_signal(qtbot, tmp_path):
    bar = _bar(qtbot, tmp_path)
    requested = track(bar.search_requested)
    field = find_item(bar.quick, "searchInput")

    field.setProperty("text", "  Ba  ")
    qtbot.waitUntil(lambda: requested == [("Ba",)], timeout=700)

    field.setProperty("text", "Battle")
    click_item(bar.quick, find_item(bar.quick, "searchButton"))
    assert requested[-1] == ("Battle",)


async def test_headers_and_results_have_distinct_row_contracts_and_select(qtbot, tmp_path):
    event = SimpleNamespace(id=42, name="Battle", start_date=None)
    vm = _vm({"events": [event]})
    bar = _bar(qtbot, tmp_path, vm)
    selected = track(bar.result_selected)
    find_item(bar.quick, "searchInput").setProperty("text", "Ba")

    await vm.search("Ba")
    qtbot.waitUntil(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)
    assert len(find_items(bar.quick, "searchSectionHeader")) == 1
    assert len(find_items(bar.quick, "searchNoMatchRow")) == 0

    header = find_item(bar.quick, "searchSectionHeader")
    click_item(bar.quick, header)
    assert selected == []

    click_item(bar.quick, find_item(bar.quick, "searchResultRow"))
    assert selected == [("event", 42)]
    assert vm.listVisible is False


async def test_accessibility_press_on_result_row_jumps_like_the_click(qtbot, tmp_path):
    """nri-0017 task 2.2 sweep (the B3 family): the result row's action IS the
    jump (the click emits it and the list collapses with it) — RowItem's
    press path emits ``activateRequested``, and without a listener here the
    tree press was a silent no-op. One Press now runs the very same jump."""
    event = SimpleNamespace(id=42, name="Battle", start_date=None)
    vm = _vm({"events": [event]})
    bar = _bar(qtbot, tmp_path, vm)
    selected = track(bar.result_selected)
    find_item(bar.quick, "searchInput").setProperty("text", "Ba")

    await vm.search("Ba")
    qtbot.waitUntil(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)

    row = find_item(bar.quick, "searchResultRow")
    iface = QAccessible.queryAccessibleInterface(row)
    assert iface is not None
    actions = iface.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")

    assert selected == [("event", 42)]
    assert vm.listVisible is False


async def test_empty_query_and_no_match_list_semantics(qtbot, tmp_path):
    vm = _vm({})
    bar = _bar(qtbot, tmp_path, vm)
    field = find_item(bar.quick, "searchInput")

    field.setProperty("text", "")
    assert vm.rows == []
    assert find_item(bar.quick, "searchResultsList").property("visible") is False

    field.setProperty("text", "missing")
    await vm.search("missing")
    qtbot.waitUntil(lambda: len(find_items(bar.quick, "searchNoMatchRow")) == 1)
    assert find_item(bar.quick, "searchNoMatchRow").property("enabled") is False


async def test_live_retheme_preserves_current_index_and_scroll(qtbot, tmp_path):
    entities = [
        SimpleNamespace(id=index, name=f"Character {index:02d}")
        for index in range(40)
    ]
    vm = _vm({"characters": entities})
    runtime = make_runtime(tmp_path, "dark")
    bar = SearchBar(vm, theme=runtime)
    qtbot.addWidget(bar)
    bar.resize(420, 220)
    bar.show()
    qtbot.waitExposed(bar)
    find_item(bar.quick, "searchInput").setProperty("text", "ch")
    await vm.search("ch")

    results = find_item(bar.quick, "searchResultsList")
    qtbot.waitUntil(lambda: len(island_rows(bar.quick, "searchResultRow")) > 5)
    results.setProperty("currentIndex", 8)
    results.setProperty("contentY", 60.0)
    before_color = bar.quick.rootObject().property("surfaceColor")
    before_y = float(results.property("contentY"))

    assert runtime.toggle() is True
    assert bar.quick.rootObject().property("surfaceColor") != before_color
    assert results.property("currentIndex") == 8
    assert float(results.property("contentY")) == before_y


def test_done_uses_deferred_source_teardown(qtbot, tmp_path):
    bar = _bar(qtbot, tmp_path)
    bar.close()
    qtbot.waitUntil(lambda: bar.quick.source().isEmpty(), timeout=2000)


def test_late_height_sync_is_inert_after_the_release(qtbot, tmp_path):
    """The deferred release can land before a queued ``implicitHeightChanged``
    is delivered: with the scene gone the mirror must no-op, not crash."""
    bar = _bar(qtbot, tmp_path)
    height_before = bar.height()
    bar.close()
    qtbot.waitUntil(lambda: bar.quick.rootObject() is None, timeout=2000)
    bar._sync_island_height()
    assert bar.height() == height_before
