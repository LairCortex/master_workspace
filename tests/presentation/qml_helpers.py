"""Shared offscreen helpers for addressing the launcher QML island from tests.

The ``QQuickWidget`` scene is not a ``QObject`` child tree reachable by
``findChild`` (an unexposed widget never exposes its items that way) and
delegate rows live in the flickable, not the C++ parent chain — only the
visual ``childItems()`` walk sees them. These helpers are the same ones the
island unit tests (``test_launcher_qml.py``) established for group 5, kept as
a module so the QDialog-wrapper contract tests (group 6) address the island
by its ``objectName`` contract the same way.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest


def walk_items(root: QQuickItem):
    """All descendant visual items of a QQuickItem (the visual tree)."""
    stack = [root]
    while stack:
        for child in stack.pop().childItems():
            yield child
            stack.append(child)


def find_items(widget, object_name: str) -> list[QQuickItem]:
    return [i for i in walk_items(widget.rootObject()) if i.objectName() == object_name]


def find_item(widget, object_name: str) -> QQuickItem:
    items = find_items(widget, object_name)
    assert len(items) == 1, f"expected exactly one {object_name!r}, got {len(items)}"
    return items[0]


def island_rows(widget, row_object_name: str) -> list[QQuickItem]:
    """Materialized delegate rows top-to-bottom (the launcher convention:
    ``grab`` first — delegate materialization rides the render pass; sort by
    scene y, not by child order)."""
    widget.grab()
    found = find_items(widget, row_object_name)
    found.sort(key=lambda r: r.mapToScene(QPointF(0, 0)).y())
    return found


def island_row_texts(widget, row_object_name: str, text_object_name: str) -> list[str]:
    """Delegate row labels top-to-bottom (``text`` read without a text pass:
    the QML ``Text`` items expose the bindable property directly)."""
    items = []
    for row in island_rows(widget, row_object_name):
        texts = [i for i in walk_items(row) if i.objectName() == text_object_name]
        assert len(texts) == 1
        items.append(texts[0].property("text"))
    return items


def island_toggle_text(widget) -> str:
    """The current label of the island's theme toggle (its ``text`` property).

    QML ``Text``/``Button`` expose the bindable ``text`` property directly, so
    the label is readable without a render pass (the property binding is
    evaluated as soon as its inputs change).
    """
    return find_item(widget, "themeToggleButton").property("text")


def click_item(widget, item: QQuickItem, *, double: bool = False) -> None:
    """A synthetic mouse click on a scene item's centre."""
    center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    pos = QPoint(int(center.x()), int(center.y()))
    click = QTest.mouseDClick if double else QTest.mouseClick
    click(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(0)


def track(signal) -> list:
    """Collect a signal's emit-argument tuples into a list."""
    emits: list = []
    signal.connect(lambda *args: emits.append(args))
    return emits
