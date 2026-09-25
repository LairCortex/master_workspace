"""Accessibility contract of the «Чар-листы» island tabs (change
nri-0017-accessibility-completers, task 2.1 — live finding B1).

The two tabs are stock ``ThemeTabButton`` (TabButton) controls, so their tree
face stays штатно: role PageTab reaches the interface, the NAME slot is never
re-annotated (offscreen the stock slot is empty — the name==caption half is a
live-display rule pinned by test_qml_stock_controls_accessibility.py; the
forbidden re-annotation half is pinned here at the source level for exactly
these two instances).

The B1 pin itself is the offscreen action contract (design F4): ONE
``actionInterface().doAction("Press")`` on the «Листы» tab behaves as one mouse
click — the bar mirrors it into the VM through the island's sync slot
(``setCurrentTab``), the checked states and the StackLayout page follow, and
the reverse tab switches back the same way.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QAccessible

from app.presentation.viewmodels.sheet_list_view_model import (
    TAB_INSTANCES,
    TAB_TEMPLATES,
)
from tests.presentation.qml_helpers import find_item, track
from tests.presentation.test_sheet_islands_qml import (  # noqa: F401 — fixtures travel with the import
    INSTANCES,
    TEMPLATES,
    SHEET_LIST_QML,
    list_vm,
    load_island,
    palette,
    tokens_file,
)
from tests.qml_a11y_scan import QML_ROOT, object_name_annotation_violation

# (objectName, visible caption) — the two-tab contract of SheetListRoot.qml.
TABS = (
    ("tabTemplates", "Шаблоны"),
    ("tabInstances", "Листы"),
)


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def press(item) -> None:
    actions = accessible_of(item).actionInterface()
    assert "Press" in actions.actionNames(), (
        f"{item.objectName()!r} exposes accessibility actions "
        f"{actions.actionNames()!r} — the tab is unreachable to a single Press"
    )
    actions.doAction("Press")


def _loaded_list_island(qtbot, list_vm, palette):
    list_vm.set_rows(templates=TEMPLATES, instances=INSTANCES)
    widget = load_island(qtbot, SHEET_LIST_QML, list_vm, palette, (420, 520))
    assert widget.errors() == []
    return widget


def test_tabs_carry_the_stock_page_tab_face(qtbot, list_vm, palette):
    # Role is delivered; the offscreen name slot never contradicts the caption
    # (a non-empty slot here can only be a forbidden re-annotation).
    widget = _loaded_list_island(qtbot, list_vm, palette)
    for object_name, caption in TABS:
        item = find_item(widget, object_name)
        iface = accessible_of(item)
        assert iface.role() == QAccessible.Role.PageTab
        name = iface.text(QAccessible.Name)
        assert name in ("", caption), (
            f"{object_name}: name slot {name!r} contradicts visible caption "
            f"{caption!r} — someone annotated a stock tab"
        )
        assert item.property("text") == caption != ""


def test_tab_declarations_carry_no_accessible_name_in_source():
    # «имена вкладок штатные»: the two instances derive their name from the
    # caption — any Accessible.name on them (even "") is forbidden (4.2 pin).
    source = (QML_ROOT / "SheetListRoot.qml").read_text(encoding="utf-8")
    for object_name, _caption in TABS:
        assert object_name_annotation_violation(
            source, "ThemeTabButton", object_name
        ) is None


def test_press_on_the_instances_tab_switches_the_vm(qtbot, list_vm, palette):
    widget = _loaded_list_island(qtbot, list_vm, palette)
    tab_changed = track(list_vm.tabChanged)
    assert list_vm.current_tab == TAB_TEMPLATES

    press(find_item(widget, "tabInstances"))

    # The single Press landed as one click on the tab: the sync slot ran, the
    # bar and the per-tab checked states followed.
    assert list_vm.current_tab == TAB_INSTANCES
    assert tab_changed == [()]
    assert find_item(widget, "tabInstances").property("checked") is True
    assert find_item(widget, "tabTemplates").property("checked") is False
    assert widget.errors() == []


def test_press_on_the_templates_tab_switches_back(qtbot, list_vm, palette):
    widget = _loaded_list_island(qtbot, list_vm, palette)
    from tests.presentation.qml_helpers import click_item

    click_item(widget, find_item(widget, "tabInstances"))
    assert list_vm.current_tab == TAB_INSTANCES

    press(find_item(widget, "tabTemplates"))

    assert list_vm.current_tab == TAB_TEMPLATES
    assert find_item(widget, "tabTemplates").property("checked") is True
    assert widget.errors() == []
