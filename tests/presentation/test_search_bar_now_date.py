"""Offscreen contract of the «now» widget row in the search island (NRI-0021
task 3.2, design Д4, spec current-date «Виджет „Сейчас: <дата>“» + qml-shell).

No new island: the row is a library ``ThemeDateField`` inside the existing
``SearchBarRoot`` above the search field, centered; the island's context gains
exactly one name — the widget's sync VM ``nowDateVm``. Pinned here offscreen:
``objectName`` addressability, the placement above the field, the
accessibility face (role Button from the component, name = the caption at the
usage site, Press reaches the VM's popup channel — pattern of
``tests/presentation/test_*_accessibility*.py``), live retheme without losing
the caption, and the null-VM guard of unit-built islands.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QAccessible

from app.domain.game_calendar import MonthDay
from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.viewmodels.now_date_view_model import NowDateViewModel
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.views.search_bar import SearchBar
from tests.presentation.qml_helpers import find_item, track


def make_runtime(tmp_path, theme):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    if theme != "dark":
        prefs.save(UiPrefs(theme=theme))
    return ThemeRuntime(prefs=prefs, tokens_path=tokens_file_path())


def _search_vm() -> SearchViewModel:
    return SearchViewModel(SimpleNamespace(search_all=AsyncMock(return_value={})))


def _now_vm() -> NowDateViewModel:
    """The widget VM, unparented at birth; the island tests adopt it under
    the bar right after construction (the facade's own context-adoption
    pattern for scene-referenced VMs), so the context's raw pointer can
    never outlive the QObject through Python GC in tests."""
    return NowDateViewModel(MonthDay(2027, 3, 14))


def _bar(qtbot, tmp_path, with_now=True, theme="dark"):
    runtime = make_runtime(tmp_path, theme)
    now_vm = _now_vm() if with_now else None
    bar = SearchBar(_search_vm(), theme=runtime, now_date_vm=now_vm)
    if now_vm is not None:
        now_vm.setParent(bar)
    qtbot.addWidget(bar)
    bar.resize(640, 360)
    bar.show()
    qtbot.waitExposed(bar)
    return bar


def _retire(bar, qtbot) -> None:
    """Run the panel's production exit path: close → the one-shot deferred
    island release. The scene dies here, inside its own test, instead of
    being swept out under the next test's engine reset (the idiom of
    test_done_uses_deferred_source_teardown)."""
    bar.close()
    qtbot.waitUntil(lambda: bar.quick.source().isEmpty(), timeout=2000)


def _scene_center_x(item) -> float:
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).x()


def _scene_y(item) -> float:
    return item.mapToScene(QPointF(0, 0)).y()


def test_widget_row_resolves_by_object_name_above_the_field_centered(qtbot, tmp_path):
    bar = _bar(qtbot, tmp_path)
    vm = bar._now_date_vm
    chip = find_item(bar.quick, "nowDateField")  # exactly one, the contract
    field = find_item(bar.quick, "searchInput")

    assert bool(chip.property("visible")) is True
    assert chip.property("display") == "Сейчас: 14 Март 2027" == vm.caption
    # «над полем ввода по центру» (spec qml-shell delta):
    assert _scene_y(chip) < _scene_y(field)
    root = bar.quick.rootObject()
    assert _scene_center_x(chip) == pytest.approx(root.width() / 2, abs=1.0)
    _retire(bar, qtbot)


def test_accessibility_face_is_a_named_button_pressing_reaches_the_vm(qtbot, tmp_path):
    """Role/press come from ThemeDateField (component-owned), the name is the
    usage-site caption (design Д4), and the tree Press runs the very same
    ``clicked`` path as the mouse: VM popup request with the chip rectangle."""
    bar = _bar(qtbot, tmp_path)
    vm = bar._now_date_vm
    chip = find_item(bar.quick, "nowDateField")
    requested = track(vm.datePopupRequested)

    iface = QAccessible.queryAccessibleInterface(chip)
    assert iface is not None
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == vm.caption == "Сейчас: 14 Март 2027"

    actions = iface.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")

    assert len(requested) == 1
    x, y, width, height = requested[0]
    assert x >= 0 and y >= 0
    assert width > 0 and height > 0
    _retire(bar, qtbot)


def test_caption_and_name_follow_the_vm_without_a_rebuild(qtbot, tmp_path):
    bar = _bar(qtbot, tmp_path)
    vm = bar._now_date_vm
    chip = find_item(bar.quick, "nowDateField")

    vm.applyNow(MonthDay(44, 11, 3), True)

    assert chip.property("display") == "Сейчас: 03 Ноябрь 44 г. до н.э."
    iface = QAccessible.queryAccessibleInterface(chip)
    assert iface.text(QAccessible.Name) == vm.caption
    _retire(bar, qtbot)


def test_live_retheme_does_not_lose_the_caption(qtbot, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    bar = SearchBar(_search_vm(), theme=runtime, now_date_vm=_now_vm())
    vm = bar._now_date_vm
    vm.setParent(bar)
    qtbot.addWidget(bar)
    bar.resize(640, 360)
    bar.show()
    qtbot.waitExposed(bar)
    chip = find_item(bar.quick, "nowDateField")
    before_color = bar.quick.rootObject().property("surfaceColor")

    assert runtime.toggle() is True

    root = bar.quick.rootObject()
    assert root.property("surfaceColor") != before_color  # the theme really moved
    assert chip.property("display") == vm.caption == "Сейчас: 14 Март 2027"
    iface = QAccessible.queryAccessibleInterface(chip)
    assert iface.text(QAccessible.Name) == vm.caption
    _retire(bar, qtbot)


def test_island_context_gains_exactly_the_widget_vm(qtbot, tmp_path):
    search_vm = _search_vm()
    runtime = make_runtime(tmp_path, "dark")
    bar = SearchBar(search_vm, theme=runtime, now_date_vm=_now_vm())
    now_vm = bar._now_date_vm
    now_vm.setParent(bar)
    qtbot.addWidget(bar)
    bar.resize(640, 360)
    bar.show()
    qtbot.waitExposed(bar)

    assert bar._context.contextProperty("searchBarVm") is search_vm
    assert bar._context.contextProperty("nowDateVm") is now_vm
    assert bar._context.contextProperty("islandPalette") is bar._palette
    # searchBarVm stays purely the search VM — the date surface is a name of
    # its own, and nothing else joins (spec «Контекст каждого острова
    # минимален»).
    assert bar._context.contextProperty("tooltipBridge") is None
    assert bar._context.contextProperty("current_date_service") is None
    _retire(bar, qtbot)


def test_island_without_a_game_value_hides_the_row(qtbot, tmp_path):
    """Unit-built islands (no game open) carry the context name as null; the
    row is hidden and the search half is untouched."""
    bar = _bar(qtbot, tmp_path, with_now=False)

    assert bar._context.contextProperty("nowDateVm") is None
    chip = find_item(bar.quick, "nowDateField")
    assert bool(chip.property("visible")) is False
    # The search field keeps working without the widget; the query is drained
    # back to empty so no debounce timer outlives the retired island.
    field = find_item(bar.quick, "searchInput")
    field.setProperty("text", "Ba")
    assert bar._vm.query == "Ba"
    field.setProperty("text", "")
    _retire(bar, qtbot)


def test_now_date_anchor_maps_the_chip_rect_to_global(qtbot, tmp_path):
    bar = _bar(qtbot, tmp_path)

    anchor = bar.now_date_anchor(12.7, 30.4, 140.9, 24.2)

    assert anchor.topLeft() == bar.quick.mapToGlobal(QPoint(12, 30))
    assert anchor.width() == 140
    assert anchor.height() == 24
    # Negative geometry clamps to an empty size (the popup tolerates it).
    empty = bar.now_date_anchor(0, 0, -5, -5)
    assert empty.width() == 0 and empty.height() == 0
    _retire(bar, qtbot)
