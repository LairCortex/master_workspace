"""NRI-0015 task 1.1 — the detail-panel tab captions read without eliding.

Spec main-window «Подписи вкладок деталей читаемы при дефолтной ширине»: the
tab strip shows the registry's short tab_label, every tab keeps at least the
width its short caption needs, and the full plural label stays available as
the tab's accessible name (control property — the QAccessible interface for
these text-stamped tabs exists on the live platform, AGENTS' F4).

Pins: registry guard (non-empty tab_label for everyEntityType, the approved
short captions, full plural preserved as name source); the view model
exposes both lists; on the shown island every tab button is at least as wide
as its own content at both the nominal and the narrowest legitimate panel
width, and carries the full plural as accessibleName.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from app.domain import entity_registry as reg
from app.domain.enums.entity_type import EntityType
from app.presentation.views.detail_panel import DetailPanel
from tests.presentation.qml_helpers import find_item, walk_items

SHORT_TAB_LABELS = ["Орг.", "Персы", "Вещи", "Локации"]
FULL_TAB_LABELS = ["Организации", "Персонажи", "Предметы", "Локации"]
# 1028 — the nominal window; 346 and 279 — legitimate detail-column widths,
# 279 being the column the live window really leaves the panel at the default
# 1028 window width (live audit tail: equal-width tab division elided
# «Локации» exactly there).
PANEL_WIDTHS = (1028, 346, 279)


@pytest.mark.parametrize("entity_type", list(EntityType))
def test_every_registered_type_has_a_nonempty_tab_label(entity_type):
    assert reg.descriptor(entity_type).tab_label.strip() != ""


def test_detail_tab_captions_are_the_approved_short_forms():
    captioned = (
        EntityType.ORGANIZATION,
        EntityType.CHARACTER,
        EntityType.ITEM,
        EntityType.LOCATION,
    )
    assert [reg.descriptor(t).tab_label for t in captioned] == SHORT_TAB_LABELS
    assert [reg.descriptor(t).plural_label for t in captioned] == FULL_TAB_LABELS


def test_view_model_publishes_short_labels_and_full_titles():
    from app.presentation.viewmodels.detail_panel_view_model import (
        DetailPanelViewModel,
    )

    vm = DetailPanelViewModel()
    assert list(vm.tabLabels) == SHORT_TAB_LABELS
    assert list(vm.tabTitles) == FULL_TAB_LABELS


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


@pytest.mark.parametrize("width", PANEL_WIDTHS)
def test_tab_geometry_and_names(width, qtbot):
    panel = _shown_panel(qtbot, width)
    tabs = _tabs(panel)
    assert len(tabs) == 4
    for tab, short, full in zip(tabs, SHORT_TAB_LABELS, FULL_TAB_LABELS):
        assert tab.property("text") == short
        # The real caption floor: content PLUS the button's own horizontal
        # padding — width >= implicitContentWidth alone still allowed the
        # live elide of «Локации» (the bar's equal-width division ignored
        # implicitWidth, which the delegate now overrides with its own).
        assert tab.width() >= tab.property("implicitWidth")
        # Via the QAccessible interface (the offscreen-projected surface).
        iface = QAccessible.queryAccessibleInterface(tab)
        assert iface is not None
        assert iface.text(QAccessible.Name) == full


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
