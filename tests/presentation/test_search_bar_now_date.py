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
from tests.presentation.qml_helpers import click_item, find_item, track, walk_items


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


def _scene_y(item) -> float:
    return item.mapToScene(QPointF(0, 0)).y()


def test_widget_row_resolves_by_object_name_above_the_field_pair_centered(qtbot, tmp_path):
    bar = _bar(qtbot, tmp_path)
    vm = bar._now_date_vm
    chip = find_item(bar.quick, "nowDateField")  # exactly one, the contract
    combo = find_item(bar.quick, "nowHourCombo")  # NRI-0023 task 9.1 neighbor
    field = find_item(bar.quick, "searchInput")

    assert bool(chip.property("visible")) is True
    assert chip.property("display") == "Сейчас: 14 Март 2027" == vm.caption
    # «рядом» — same line: the RowLayout centers both on one vertical axis
    # (the shorter combo shares the chip's line, its top edge sits lower).
    chip_mid_y = _scene_y(chip) + chip.height() / 2
    assert _scene_y(combo) + combo.height() / 2 == pytest.approx(chip_mid_y, abs=1.0)
    combo_left = combo.mapToScene(QPointF(0, 0)).x()
    chip_right = chip.mapToScene(QPointF(chip.width(), 0)).x()
    assert combo_left > chip_right - 1
    # NRI-0023 group 12 (centering restored over audit A9 by the user request
    # of 2026-09-30): the left edge is no longer pinned to the field — the
    # MIDDLE of the chip+selector pair sits on the middle of the row, and the
    # row's middle is the island's middle (spec current-date «середина пары
    # совпадает с центром панели поиска»).
    assert _scene_y(chip) + chip.height() <= _scene_y(field) + 1.0
    chip_left = chip.mapToScene(QPointF(0, 0)).x()
    field_left = field.mapToScene(QPointF(0, 0)).x()
    combo_right = combo.mapToScene(QPointF(combo.width(), 0)).x()
    pair_mid = (chip_left + combo_right) / 2
    row = find_item(bar.quick, "nowDateRow")
    row_mid = row.mapToScene(QPointF(0, 0)).x() + row.width() / 2
    island = bar.quick.rootObject()
    island_mid = island.mapToScene(QPointF(0, 0)).x() + island.width() / 2
    assert pair_mid == pytest.approx(row_mid, abs=0.5)
    assert row_mid == pytest.approx(island_mid, abs=0.5)
    # …and the pair is genuinely centered, not left-hugged: with the bar at
    # 640 pt the freed gutter is far wider than the pair's half.
    assert chip_left > field_left + 1.0
    _retire(bar, qtbot)


def test_now_row_pair_shares_one_height_and_a_fixed_selector_width(qtbot, tmp_path):
    """Д14.2/Д14.3 (H1/H2/A5/A7) on the real island: the selector prints the
    VM's labelled display text («Час:» видна до всякого выбора, список остаётся
    цифрами), the empty value is the placeholder rank, the pair shares one
    height, and the selector's width is the calendar's worst label — switching
    hours moves nothing, while the chip's hour-tail growth only re-centers the
    pair symmetrically (centering restored by the 2026-09-30 user request)."""
    bar = _bar(qtbot, tmp_path)
    vm = bar._now_date_vm
    chip = find_item(bar.quick, "nowDateField")
    combo = find_item(bar.quick, "nowHourCombo")

    assert str(combo.property("displayText")) == "Час: —" == vm.hourDisplay
    assert "Час:" not in str(combo.property("model")[0])  # rows stay bare
    assert str(combo.property("worstCaseText")) == vm.worstCaseHourOption == "Час: 23"
    assert bool(combo.property("valueIsPlaceholder")) is True
    # единая геометрия пары (Д14.3): чип и селектор — одна высота
    assert combo.property("height") == pytest.approx(chip.property("height"), abs=0.5)

    def pair_mid() -> float:
        left = chip.mapToScene(QPointF(0, 0)).x()
        right = combo.mapToScene(QPointF(combo.width(), 0)).x()
        return (left + right) / 2

    width_at_rest = float(combo.property("width"))
    mid_at_rest = pair_mid()
    vm.applyNow(MonthDay(2027, 3, 14), False, 1)  # the narrowest glyph
    qtbot.waitUntil(
        lambda: str(combo.property("displayText")) == "Час: 1", timeout=2000
    )
    assert bool(combo.property("valueIsPlaceholder")) is False
    assert float(combo.property("width")) == pytest.approx(width_at_rest, abs=0.5)
    # the set hour raises the chip's worstCase floor (the «, HH:00» tail): the
    # pair grows around its own middle — the middle never moves (A5 under the
    # restored centering: the pin is the pair's center, not the chip's left)
    assert pair_mid() == pytest.approx(mid_at_rest, abs=0.5)
    chip_left_hour_one = chip.mapToScene(QPointF(0, 0)).x()
    vm.applyNow(MonthDay(2027, 3, 14), False, 23)  # the widest glyph
    qtbot.waitUntil(
        lambda: str(combo.property("displayText")) == "Час: 23", timeout=2000
    )
    assert float(combo.property("width")) == pytest.approx(width_at_rest, abs=0.5)
    # hour-to-hour the floors are already worst-case, so neither the chip's
    # left edge nor the pair's center shifts at all (A5)
    assert chip.mapToScene(QPointF(0, 0)).x() == pytest.approx(chip_left_hour_one, abs=0.5)
    assert pair_mid() == pytest.approx(mid_at_rest, abs=0.5)
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
    # NRI-0023 task 9.1: the hour list shares the row guard — no game, no chip,
    # no list.
    assert bool(find_item(bar.quick, "nowHourCombo").property("visible")) is False
    # The search field keeps working without the widget; the query is drained
    # back to empty so no debounce timer outlives the retired island.
    field = find_item(bar.quick, "searchInput")
    field.setProperty("text", "Ba")
    assert bar._vm.query == "Ba"
    field.setProperty("text", "")
    _retire(bar, qtbot)


# ── NRI-0023 task 9.1 — the neighbor hour list ───────────────────────────────


def test_hour_combo_mirrors_the_vm_list_selection_and_caption(qtbot, tmp_path):
    """The island's combo is a pure mirror: the list bounds and the index
    mapping live in the VM (the island hardcodes nothing); applying an hour
    moves the chip caption to the «…, HH:00» form and the selection onto the
    hour — without an island rebuild."""
    bar = _bar(qtbot, tmp_path)
    vm = bar._now_date_vm
    chip = find_item(bar.quick, "nowDateField")
    combo = find_item(bar.quick, "nowHourCombo")

    assert list(combo.property("model")) == ["—"] + [str(h) for h in range(24)]
    assert combo.property("currentIndex") == 0  # «—» — час не выставлен

    vm.applyNow(MonthDay(2027, 3, 14), False, 14)

    assert combo.property("currentIndex") == 15  # индекс часа H — H + 1
    assert chip.property("display") == "Сейчас: 14 Март 2027, 14:00" == vm.caption
    _retire(bar, qtbot)


def test_hour_combo_is_the_named_trigger_of_the_widget(qtbot, tmp_path):
    """a11y face (design Д8 pattern): the role comes from the library
    ThemeComboBox, the name is the usage-site purpose. Its drop-down is a
    native window outside the island — documented tree limit ③, never
    pinned here; the chip keeps its own caption-named Button face."""
    bar = _bar(qtbot, tmp_path)
    combo = find_item(bar.quick, "nowHourCombo")

    iface = QAccessible.queryAccessibleInterface(combo)
    assert iface is not None
    assert iface.role() == QAccessible.Role.ComboBox
    assert iface.text(QAccessible.Name) == "Час сейчас"
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


# ── NRI-0023 task 12.6 — A1 host half: the hour list leaves for the bridge ───


def test_hour_combo_press_travels_to_the_vm_not_the_clipped_qml_popup(
    qtbot, tmp_path
):
    """The host fix (design Д14.1 host half, re-audit A1): the island's widget
    is fixed to the scene's implicit height, so the component's own pop-up
    here could never grow to its full list. The usage site takes the date
    chip's route instead: the press forwards the combo rectangle through
    ``hourPopupRequested`` (the wiring answers with the widgets-bridge window)
    and the in-island pop-up NEVER becomes visible — a regression that reopens
    the clipped popup fails this pin offscreen, where the live clipping itself
    is invisible (the tests' 360 pt bar never cuts a two-row popup)."""
    bar = _bar(qtbot, tmp_path)
    vm = bar._now_date_vm
    combo = find_item(bar.quick, "nowHourCombo")
    requested = track(vm.hourPopupRequested)

    click_item(bar.quick, combo)
    qtbot.wait(80)  # a leak would have opened (and its rows realized) by now

    assert len(requested) == 1
    x, y, width, height = requested[0]
    assert x >= 0 and y >= 0
    assert width > 0 and height > 0
    # The island-local rectangle is the combo's own (the wiring maps it).
    origin = combo.mapToItem(bar.quick.rootObject(), 0, 0)
    assert (x, y) == (origin.x(), origin.y())
    # The QML pop-up stayed closed: not the popup item, not a single delegate.
    popup_items = [
        i for i in walk_items(bar.quick.rootObject())
        if i.objectName() == "themeComboPopup"
    ]
    assert all(bool(i.property("visible")) is False for i in popup_items)
    delegates = [
        i for i in walk_items(bar.quick.rootObject())
        if i.metaObject().className().startswith("ItemDelegate")
    ]
    assert delegates == []
    _retire(bar, qtbot)
