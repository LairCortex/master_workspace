"""NRI-0019 — the detail tabs are tabs, and they follow the column width.

Spec main-window «Подписи вкладок деталей читаемы при дефолтной ширине»
(NRI-0019 re-pin): every tab's visible text IS the registry plural_label,
and that same caption is the tab's accessibility name and its tooltip
(scenario «Подпись и имя доступности одно»); no short-caption field survives
in the registry. The strip no longer needs the «all tabs whole» threshold:
the tabs share the panel's whole width (stretch beyond their natural widths,
shrink proportionally below them) and a narrow column shortens the captions
with the ellipsis instead of clipping the strip — the retired threshold is
gone from the panel, the placement memory and the splitter floors (see
test_main_window_default_start.py).

Pins: registry guard (the tab_label field is gone from EntityDescriptor);
the view model exposes only the full titles; on the shown island every tab's
text, QAccessible name and tooltip-bridge request equal the full caption; at
the default width every caption stands whole while the tabs together fill the
bar's whole width; in a narrow column the tabs shrink proportionally to their
natural widths and the eliding labels prove the shortened captions.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from app.domain import entity_registry as reg
from app.domain.enums.entity_type import EntityType
from app.presentation.views.detail_panel import DetailPanel
from tests.presentation.qml_helpers import find_item, walk_items

FULL_TAB_LABELS = ["Организации", "Персонажи", "Предметы", "Локации"]
# 1280 — the default window width; the detail column it leaves the panel
# must show every full caption whole while the tabs fill the strip (spec
# scenario «Все вкладки прочитаны на дефолте»).
DEFAULT_PANEL_WIDTH = 1280
# A column clearly narrower than the natural captions: the tabs must shrink
# and the labels must elide instead of the strip leaking out of the panel
# (spec scenario «Узкая колонка сокращает подписи»).
NARROW_PANEL_WIDTH = 240


# ── the registry no longer carries a short-caption field (task 4.2) ─────────


def test_registry_has_no_tab_short_caption_field_anymore():
    field_names = {f.name for f in dataclasses.fields(reg.EntityDescriptor)}
    assert "tab_label" not in field_names
    for entity_type in EntityType:
        assert not hasattr(reg.descriptor(entity_type), "tab_label")


def test_detail_tab_captions_are_the_full_registry_names():
    captioned = (
        EntityType.ORGANIZATION,
        EntityType.CHARACTER,
        EntityType.ITEM,
        EntityType.LOCATION,
    )
    assert [reg.descriptor(t).plural_label for t in captioned] == FULL_TAB_LABELS


def test_view_model_publishes_full_titles_only():
    from app.presentation.viewmodels.detail_panel_view_model import (
        DetailPanelViewModel,
    )

    vm = DetailPanelViewModel()
    assert list(vm.tabTitles) == FULL_TAB_LABELS
    # The short-caption half of the NRI-0015 API retired with the registry field.
    assert not hasattr(vm, "tabLabels")


# ── the shown island: text = name = tooltip = full caption (task 4.1) ───────


def _shown_panel(qtbot, width: int) -> DetailPanel:
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.resize(width, 700)
    panel.show()
    QApplication.processEvents()
    return panel


def _tabs(panel: DetailPanel):
    tabs = [
        item
        for item in walk_items(find_item(panel.quick, "detailTabBar"))
        if item.metaObject().className().startswith("ThemeTabButton")
    ]
    tabs.sort(key=lambda item: item.x())
    return tabs


def _bar(panel: DetailPanel):
    return find_item(panel.quick, "detailTabBar")


def test_tab_text_accessible_name_and_tooltip_are_one_caption(qtbot):
    panel = _shown_panel(qtbot, DEFAULT_PANEL_WIDTH)
    tabs = _tabs(panel)
    assert len(tabs) == 4
    for tab, full in zip(tabs, FULL_TAB_LABELS):
        assert tab.property("text") == full
        # Via the QAccessible interface (the offscreen-projected surface).
        iface = QAccessible.queryAccessibleInterface(tab)
        assert iface is not None
        assert iface.text(QAccessible.Name) == full

    # The tooltip half: hovering a tab reports its caption to the island's
    # own tooltip bridge (the timeline-button pattern) — the SAME caption.
    # The bridge's own smoke pin (test_qml_components.py) established the
    # harness: reports surface on later loop turns, so each one is waited
    # for, and the pointer passes over neutral ground between the tabs —
    # handed straight from delegate to neighbour, Qt's hover switch lets the
    # previous tab's empty release land AFTER the next tab's show, which is
    # the window's event ordering, not this island's tooltip contract
    # (scenario «Подпись и имя доступности одно» pins the report, not the
    # handoff).
    bridge = panel._tooltip_bridge
    try:
        for tab, full in zip(tabs, FULL_TAB_LABELS):
            center = tab.mapToScene(QPointF(tab.width() / 2, tab.height() / 2))
            QTest.mouseMove(panel.quick, QPoint(1, 1))  # neutral: release any tab
            qtbot.waitUntil(
                lambda: bridge.last_request is None
                or bridge.last_request[0] == "",
                timeout=5000,
            )
            QTest.mouseMove(panel.quick, QPoint(int(center.x()), int(center.y())))
            qtbot.waitUntil(
                lambda: bridge.last_request is not None
                and bridge.last_request[0] == full,
                timeout=5000,
            )
    finally:
        QToolTip.hideText()


def test_tabs_stretch_to_fill_the_strip_whole_at_the_default_width(qtbot):
    """Spec «Все вкладки прочитаны на дефолте» + the stretch half of the
    NRI-0019 contract: whole captions AND the tabs share the bar's width."""
    panel = _shown_panel(qtbot, DEFAULT_PANEL_WIDTH)
    root = panel.quick.rootObject()
    bar = _bar(panel)
    tabs = _tabs(panel)
    for tab, full in zip(tabs, FULL_TAB_LABELS):
        # Whole: every tab stands at least at its natural caption width…
        assert tab.width() >= tab.property("implicitWidth") - 0.5, full
        # …inside the panel, nothing leaks past the island edge.
        scene = tab.mapToItem(root, QPointF(0, 0))
        assert scene.x() + tab.width() <= root.width() + 0.5, full
    # Stretched: the tabs together cover the bar's whole width (the retired
    # natural-width row left the strip's remainder empty; the spacing between
    # underline tabs is zero, so the sum lands on the bar exactly).
    assert abs(sum(tab.width() for tab in tabs) - bar.width()) <= 1.0


def test_tabs_shrink_with_elided_captions_in_a_narrow_column(qtbot):
    """Spec «Узкая колонка сокращает подписи»: below the natural widths the
    tabs shrink proportionally to those widths and their labels elide —
    the strip stays inside the panel instead of clipping."""
    panel = _shown_panel(qtbot, NARROW_PANEL_WIDTH)
    root = panel.quick.rootObject()
    bar = _bar(panel)
    tabs = _tabs(panel)
    ratios = []
    for tab, full in zip(tabs, FULL_TAB_LABELS):
        assert tab.width() < tab.property("implicitWidth"), full
        ratios.append(tab.width() / tab.property("implicitWidth"))
        # The shortened caption: the label has less room than its full text
        # (its elide: Text.ElideRight is pinned at the component source in
        # test_qml_components — the caption then renders as «Организаци…»).
        label = tab.property("contentItem")
        assert label.width() < label.property("implicitWidth"), full
        scene = tab.mapToItem(root, QPointF(0, 0))
        assert scene.x() + tab.width() <= root.width() + 0.5, full
    # Proportional shrink: every tab lost the same share of its natural width.
    assert max(ratios) - min(ratios) < 0.05
    # The shrunk tabs still fill the bar — they narrow, they do not leave a gap.
    assert abs(sum(tab.width() for tab in tabs) - bar.width()) <= 1.0


def test_bare_manager_first_open_is_a_silent_noop():
    # The guard branch of the geometry helpers: a manager built without the
    # geometry memory (tests-only shape) must neither place nor crash.
    from app.presentation.sheet_windows import SheetWindowsManager

    manager = SheetWindowsManager(
        sheet_service=None, instance_service=None, character_service=None,
        image_store=None, theme=None, window=None, table_host=None, spawn=None,
    )
    assert manager.place_first_open(None, "sheet_editor") is True
    manager.place_after_show(None, "sheet_editor", remembered=True)
