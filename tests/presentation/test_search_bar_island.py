"""Real QML-island and thin-facade contracts for the R4 search panel."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest

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
    # Lucide pass 2026-09-30: the header's glyph is the VM row's iconName —
    # the one type→icon map reaching the paint through the row model.
    assert find_item(bar.quick, "searchSectionHeaderIcon").property("name") == "calendar-days"
    click_item(bar.quick, header)
    assert selected == []

    click_item(bar.quick, find_item(bar.quick, "searchResultRow"))
    # NRI-0022 task 6.2: the jump waits out the double-click interval (a real
    # double click releases a single click first); after the hold it is the
    # same single navigation as before.
    qtbot.waitUntil(
        lambda: selected == [("event", 42)],
        timeout=vm.doubleClickIntervalMs + 1500,
    )
    assert vm.listVisible is False


async def test_accessibility_press_on_result_row_opens_the_edit_route(qtbot, tmp_path):
    """nri-0017 task 2.2 sweep re-pinned for NRI-0022 task 6.2: RowItem's
    press mirrors the DOUBLE-click path, and the double click now means
    editing — a Press emits resultActivated (the wiring opens the card /
    event editor) and collapses the list; the single-click channel stays
    silent (no hold is started)."""
    event = SimpleNamespace(id=42, name="Battle", start_date=None)
    vm = _vm({"events": [event]})
    bar = _bar(qtbot, tmp_path, vm)
    selected = track(bar.result_selected)
    activated = track(bar.result_activated)
    find_item(bar.quick, "searchInput").setProperty("text", "Ba")

    await vm.search("Ba")
    qtbot.waitUntil(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)

    row = find_item(bar.quick, "searchResultRow")
    iface = QAccessible.queryAccessibleInterface(row)
    assert iface is not None
    actions = iface.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")

    assert activated == [("event", 42)]
    assert selected == []
    assert vm.listVisible is False


async def test_single_click_holds_then_navigates_double_click_edits(qtbot, tmp_path):
    """NRI-0022 task 6.2 race pin: a single click does NOT jump while the
    double-click interval is open; the real double-click sequence (click —
    then double-click event, as Qt delivers it) cancels the held jump and
    ends as the edit gesture exactly once."""
    event = SimpleNamespace(id=42, name="Battle", start_date=None)
    vm = _vm({"events": [event]})
    bar = _bar(qtbot, tmp_path, vm)
    selected = track(bar.result_selected)
    activated = track(bar.result_activated)
    find_item(bar.quick, "searchInput").setProperty("text", "Ba")
    await vm.search("Ba")
    qtbot.waitUntil(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)
    row = find_item(bar.quick, "searchResultRow")

    click_item(bar.quick, row, double=True)
    assert activated == [("event", 42)]
    assert selected == []
    assert vm.listVisible is False

    # A re-shown second search: the click→double-click sequence (what a real
    # mouse produces) must land ONLY on the edit route, after the hold window.
    await vm.search("Ba")
    vm._set_list_visible(True)
    qtbot.waitUntil(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)
    row = find_item(bar.quick, "searchResultRow")
    click_item(bar.quick, row)
    assert selected == []  # held, not fired
    click_item(bar.quick, row, double=True)
    qtbot.waitUntil(
        lambda: len(activated) == 2,
        timeout=vm.doubleClickIntervalMs + 1500,
    )
    QTest.qWait(vm.doubleClickIntervalMs + 200)
    assert selected == []
    assert activated == [("event", 42), ("event", 42)]


async def test_right_button_on_result_row_is_inert(qtbot, tmp_path):
    """Spec «Правая кнопка не делает ничего» (NRI-0022 task 6.2): the row's
    MouseArea accepts the left button only — the right one opens nothing,
    selects nothing, closes nothing (the context-menu slot stays reserved)."""
    event = SimpleNamespace(id=42, name="Battle", start_date=None)
    vm = _vm({"events": [event]})
    bar = _bar(qtbot, tmp_path, vm)
    selected = track(bar.result_selected)
    activated = track(bar.result_activated)
    find_item(bar.quick, "searchInput").setProperty("text", "Ba")
    await vm.search("Ba")
    qtbot.waitUntil(lambda: len(island_rows(bar.quick, "searchResultRow")) == 1)

    row = island_rows(bar.quick, "searchResultRow")[0]
    center = row.mapToScene(QPointF(row.width() / 2, row.height() / 2))
    QTest.mouseClick(bar.quick, Qt.RightButton, Qt.NoModifier,
                     QPoint(int(center.x()), int(center.y())))
    QTest.qWait(50)

    assert selected == []
    assert activated == []
    assert vm.listVisible is True


def test_facade_relays_both_result_gestures(qtbot, tmp_path):
    """The thin facade maps the VM's two gesture signals onto its own
    (type, id) channels the wiring connects to (NRI-0022 task 6.2)."""
    vm = _vm()
    bar = _bar(qtbot, tmp_path, vm)
    selected = track(bar.result_selected)
    activated = track(bar.result_activated)

    vm.resultSelected.emit("character", 1)
    vm.resultActivated.emit("event", 2)

    assert selected == [("character", 1)]
    assert activated == [("event", 2)]


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
