"""NRI-0018 group 4 — the detail tabs wear the FULL registry names.

Spec main-window «Подписи вкладок деталей читаемы при дефолтной ширине»
(NRI-0018 re-pin of the NRI-0015 short-caption era, design Д5): every tab's
visible text IS the registry plural_label, and that same caption is the tab's
accessibility name and its tooltip (scenario «Подпись и имя доступности
одно»); no short-caption field survives in the registry. The detail panel
publishes the «all tabs whole» threshold — the width below which the widest
full caption would clip — and that number is the width provider of the main
role's placement memory and the splitter floors (see
test_main_window_default_start.py / test_geometry_memory.py).

Pins: registry guard (the tab_label field is gone from EntityDescriptor);
the view model exposes only the full titles; on the shown island every tab's
text, QAccessible name and tooltip-bridge request equal the full caption and
keep at least their content width; the panel threshold equals the strip's own
implicit widths plus the bar spacing and this island's margins — and at that
exact width every tab stands whole while one point narrower the last tab
already leaks past the panel.
"""
from __future__ import annotations

import dataclasses
import math
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
# 1280 — the NRI-0018 default window width; the detail column it leaves the
# panel must show every full caption whole (spec scenario «Все вкладки
# прочитаны с порога»).
DEFAULT_PANEL_WIDTH = 1280


def _space_xs_px() -> int:
    """The island margin token the detail root anchors its layout with."""
    from app.presentation.theme import get_default_theme

    value = get_default_theme().tokens["space.xs"]["dark"]
    assert value.endswith("px")
    return int(value[:-2])


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


def _strip_min_width(panel: DetailPanel) -> float:
    """The threshold recomputed from the island's own numbers: the sum of the
    tabs' implicitWidth, the strip's spacing between them and the island
    margins (design Д5 «сумма implicitWidth четырёх полных вкладок + отступы
    TabBar»)."""
    tabs = _tabs(panel)
    bar = find_item(panel.quick, "detailTabBar")
    strip = sum(tab.property("implicitWidth") for tab in tabs)
    return strip + bar.property("spacing") * (len(tabs) - 1) + 2 * _space_xs_px()


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


def test_tabs_keep_their_content_width_at_the_default_panel_width(qtbot):
    panel = _shown_panel(qtbot, DEFAULT_PANEL_WIDTH)
    root = panel.quick.rootObject()
    for tab, full in zip(_tabs(panel), FULL_TAB_LABELS):
        # The real caption floor: content PLUS the button's own horizontal
        # padding (the NRI-0015 M1-tail pin stays alive for the full captions).
        assert tab.width() >= tab.property("implicitWidth")
        # …and whole inside the panel: no full caption leaks past its edge.
        scene = tab.mapToItem(root, QPointF(0, 0))
        assert scene.x() + tab.width() <= root.width() + 0.5, full


def test_threshold_is_the_all_tabs_whole_panel_width(qtbot):
    """Task 4.1 «порог = ширина панели деталей „все вкладки целиком“»."""
    panel = _shown_panel(qtbot, DEFAULT_PANEL_WIDTH)
    threshold = panel.min_tabs_width()
    assert threshold == math.ceil(_strip_min_width(panel))

    # At exactly the threshold every tab still stands whole inside the panel…
    panel.resize(threshold, 700)
    QApplication.processEvents()
    root = panel.quick.rootObject()
    for tab in _tabs(panel):
        assert tab.mapToItem(root, QPointF(0, 0)).x() + tab.width() <= root.width() + 0.5

    # …and a panel a margin-width below the threshold already clips the last
    # full caption at its edge — the threshold really is the floor, not a
    # padded guess (the strip plus both margins no longer fits).
    panel.resize(threshold - 6, 700)
    QApplication.processEvents()
    root = panel.quick.rootObject()
    last = _tabs(panel)[-1]
    assert last.mapToItem(root, QPointF(0, 0)).x() + last.width() > root.width()


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
