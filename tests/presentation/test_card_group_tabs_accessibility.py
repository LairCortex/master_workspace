"""Accessibility pins for the card grouping tabs (add-dnd-game-face task 12.1,
spec entity-card-tabs «Доступность без координат»).

The strips in EventDialogRoot/EntityCardRoot are bars of stock
``ThemeTabButton`` (TabButton): the role reaches the tree as PageTab, the
NAME slot is штатно — offscreen it stays empty and the name==caption half is
a live-display rule (the pinned Qt quirk), while the forbidden
re-annotation half is guarded source-side by
test_qml_accessibility_conventions.py over the whole QML corpus. What this
file pins is the offscreen-pinnable half, exactly the NRI-0017 F4 pattern:
ONE ``actionInterface().doAction("Press")`` on each tab is one mouse click —
the vm strip follows, the visible page follows, and the module tail of
group 7.2 (the CardTabHost tabs) walks the very same channel: Press on the
module tab seats its overlay widget over the body.
"""
from __future__ import annotations

from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QWidget

from app.presentation.card_tab_groups import (
    GROUP_OVERVIEW,
    GROUP_RELATIONS,
    GROUP_TEXTS,
)
from app.presentation.card_tab_host import CardTabHost
from app.presentation.modules.protocol import CardTabSpec
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item, walk_items

GROUP_KEYS = (GROUP_OVERVIEW, GROUP_TEXTS, GROUP_RELATIONS)
GROUP_TITLES = ("Обзор", "Тексты", "Связи")


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def strip_tabs(widget, strip_name: str):
    strip = find_item(widget, strip_name)
    return sorted(
        (
            item
            for item in walk_items(strip)
            if item.metaObject().className().startswith("ThemeTabButton")
        ),
        key=lambda item: item.x(),
    )


def press_tab(item) -> None:
    actions = accessible_of(item).actionInterface()
    assert "Press" in actions.actionNames(), (
        f"{item.objectName()!r} exposes actions {actions.actionNames()!r} — "
        "the tab is unreachable to a single Press (NRI-0017 F4 regression)"
    )
    actions.doAction("Press")


def _strip_case(qtbot, dialog, strip_name: str, tab_prefix: str, titles, keys):
    tabs = strip_tabs(dialog.quick, strip_name)
    assert [tab.property("text") for tab in tabs] == list(titles)
    for tab, key in zip(tabs, keys):
        assert tab.objectName() == f"{tab_prefix}{key}"
        iface = accessible_of(tab)
        assert iface.role() == QAccessible.Role.PageTab
        # Offscreen the stock name slot is empty; a non-empty slot could
        # only be the forbidden re-annotation (source guard covers that —
        # the tree face must simply never contradict the caption).
        assert iface.text(QAccessible.Name) in ("", tab.property("text"))
    # One Press per tab walks the whole strip — and the visible active tab
    # follows the vm, not just its counter.
    for index, key in enumerate(keys):
        press_tab(tabs[index])
        assert dialog.vm.active_group_key() == key
        assert [bool(tab.property("checked")) for tab in tabs] == [
            i == index for i in range(len(keys))
        ]
    press_tab(tabs[0])
    assert dialog.vm.active_group_key() == keys[0]


def test_event_dialog_group_tabs_answer_page_tabs_and_press_walks_the_strip(
    qtbot,
):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    _strip_case(
        qtbot, dialog, "eventGroupTabs", "eventGroupTab_", GROUP_TITLES, GROUP_KEYS
    )


def test_entity_card_group_tabs_press_walks_trio_and_pair(qtbot):
    card = EntityCardDialog(None, "character")
    qtbot.addWidget(card)
    _strip_case(
        qtbot, card, "entityGroupTabs", "entityGroupTab_", GROUP_TITLES, GROUP_KEYS
    )
    # The relation-less type: the pair answers the same contract.
    rating = EntityCardDialog(None, "rating")
    qtbot.addWidget(rating)
    _strip_case(
        qtbot,
        rating,
        "entityGroupTabs",
        "entityGroupTab_",
        ("Обзор", "Тексты"),
        (GROUP_OVERVIEW, GROUP_TEXTS),
    )


def test_module_tab_is_addressable_and_press_seats_its_widget(qtbot):
    class _TabWidget(QWidget):
        released = 0

        def release_tab(self) -> None:
            pass

    class _Source:
        visible = True

        def card_tabs(self, target):
            return (
                CardTabSpec(
                    key="dnd.sheet",
                    title="D&D",
                    factory=lambda wiring, source_id: _TabWidget(),
                ),
            )

    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    host = CardTabHost(dialog, dialog.vm, (_Source(),), "WIRING", target_key="event")
    host.refresh("1")
    dialog.show()
    QApplication.processEvents()

    tabs = strip_tabs(dialog.quick, "eventGroupTabs")
    assert [tab.property("text") for tab in tabs] == [*GROUP_TITLES, "D&D"]
    module_tab = tabs[3]
    assert module_tab.objectName() == "eventGroupTab_dnd.sheet"
    assert accessible_of(module_tab).role() == QAccessible.Role.PageTab

    widget = next(iter(dialog.findChildren(_TabWidget)))
    assert widget.isVisible() is False
    press_tab(module_tab)
    assert dialog.vm.active_group_key() == "dnd.sheet"
    assert widget.isVisible() is True
    # Back through the tree: the overlay steps aside again, the kernel tab
    # stays where the reader put it.
    press_tab(tabs[1])
    assert dialog.vm.active_group_key() == GROUP_TEXTS
    assert widget.isVisible() is False
    host.release()
    assert dialog.findChildren(_TabWidget) == []
