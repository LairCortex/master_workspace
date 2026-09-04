"""QML-addressing probe for the timeline island (Q2.5a task 6.3).

The widgets list (``rows_view``) died with the Q2.5a port; every e2e address
into the scale now goes through the island: rows/events/selection are read
from the ViewModel (the single mutation point), tape geometry from the
``eventList`` ListView's visual tree (``walk_items`` — the same offscreen
machinery the launcher island tests and ``qml_helpers`` established), and
interactions are real synthetic input on the ``QQuickWidget`` at the target
item's scene position. Names mirror the retired view addresses one-for-one
(``rows``, ``events``, ``index_for_event``, ``scroll_to_event``, ``set_knobs``,
``selected_id``) so the ported e2e bodies keep their reading.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.presentation.qml_helpers import find_item, walk_items


class Tape:
    """Read-only tape view under the retired ``rows_view`` namespace, live
    over the ViewModel (``.events``/``.rows``/``.index_for_event``/
    ``.selected_id``) so ported e2e bodies keep their shape."""

    def __init__(self, window):
        self._window = window

    @property
    def events(self) -> list:
        return events(self._window)

    @property
    def rows(self) -> list:
        return rows(self._window)

    @property
    def selected_id(self):
        return selected_id(self._window)

    @property
    def window(self):
        """The «Выбор даты» knob the VM carries ((None, None) = «Все дни»),
        the retired ``rows_view.window`` reading (the knob was a tuple there,
        the VM spells «Все дни» as ``None``).
        """
        knob = vm(self._window).window
        if knob is None:
            return (None, None)
        return tuple(knob)

    @property
    def level(self):
        """The ladder rung the tape renders (retired ``rows_view.level``)."""
        return vm(self._window).level

    @property
    def hide_empty(self) -> bool:
        """The «Скрыть даты без событий» knob (retired ``rows_view.hide_empty``)."""
        return vm(self._window).hide_empty

    def index_for_event(self, event_id):
        return index_for_event(self._window, event_id)

    def scroll_to_event(self, event_id) -> None:
        scroll_to_event(self._window, event_id)


def visual_items(window):
    """Every visual descendant of the island root."""
    return list(walk_items(root(window)))


def tape(window) -> Tape:
    return Tape(window)


def panel(window):
    return window.timeline_widget


def root(window):
    """The island root item (the facade's root-contract surface)."""
    return window.timeline_widget._root


def quick(window):
    return window.timeline_widget.quick


def item(window, object_name: str):
    """The unique island item with this ``objectName`` contract."""
    return find_item(quick(window), object_name)


def event_list(window):
    return item(window, "eventList")


def vm(window):
    return window.timeline_widget._vm


def events(window) -> list:
    """The windowed tape sample (the old ``rows_view.events``)."""
    return list(vm(window).events)


def rows(window) -> list:
    return list(vm(window).rows)


def index_for_event(window, event_id):
    return vm(window).index_for_event(event_id)


def selected_id(window):
    """The island's selection (``None`` = unselected, the old selected_id)."""
    value = root(window).property("selectedId")
    if value is None or int(value) < 0:
        return None
    return int(value)


def set_selected(window, event_id) -> None:
    panel(window).set_selected(event_id)


def scroll_to_event(window, event_id) -> None:
    panel(window).scroll_to_event(event_id)


def set_knobs(window, level=None, window_range=None, hide_empty=None) -> None:
    """Move the VM knobs the app's own paths move them (old ``set_knobs``)."""
    view_model = vm(window)
    if level is not None:
        view_model.level = level
    if window_range is not None:
        view_model.window = window_range
    if hide_empty is not None:
        view_model.hide_empty = hide_empty
    panel(window)._sync_from_vm()


def content_y(window) -> float:
    return float(event_list(window).property("contentY"))


def set_content_y(window, value: float) -> None:
    event_list(window).setProperty("contentY", value)
    pump()


def row_delegate(window, idx: int):
    """The materialized delegate answering for row ``idx`` (``None`` = the
    recycling window does not carry it — reveal the row first).
    """
    for it in walk_items(root(window)):
        if not it.objectName().endswith("Row"):
            continue
        if it.property("kind") is None:
            continue
        if it.property("index") == idx:
            return it
    return None


def reveal(window, idx: int):
    """Ask the island to show row ``idx`` (the facade's scroll request) and
    return its laid-out delegate."""
    root(window).scrollToIndex.emit(idx)
    pump(8)
    delegate = row_delegate(window, idx)
    assert delegate is not None, f"row {idx} did not materialize"
    return delegate


def scene_point(window, it, x: float | None = None, y_ratio: float = 0.5) -> QPoint:
    """Scene (= ``QQuickWidget`` viewport) point over an item."""
    px = it.mapToScene(QPointF(
        it.width() / 2 if x is None else x,
        it.height() * y_ratio,
    ))
    return QPoint(int(px.x()), int(px.y()))


def row_center(window, idx: int) -> QPoint:
    """Scene point on row ``idx`` in the text zone (the old ``row_center``:
    right of the type dot, on the card proper — the MouseArea spans the row,
    the inset just mirrors where a user aims).
    """
    delegate = row_delegate(window, idx)
    assert delegate is not None, f"row {idx} is not laid out"
    x = min(60, max(delegate.width() - 2, 2))
    return scene_point(window, delegate, x=x)


def chip_caption(window) -> str:
    return root(window).property("windowText")


def tooltip_of(window, object_name: str):
    """The item's declared ``Nri.tooltip`` text (the library shim scope).

    The attached :class:`NriAttached` is parented to the host item, so the
    plain QObject child walk reads the declaration Python needs not see.
    """
    from app.presentation.qml.tooltip_shim import NriAttached

    attached = item(window, object_name).findChildren(NriAttached)
    return attached[0].property("tooltip") if attached else None


def sticky_text(window) -> str:
    return item(window, "stickyCurrentText").property("text")


def _send_mouse(window, kind, pos: QPoint, button, buttons) -> None:
    """One explicit-button mouse event to the island (the wheel-notch style,
    task 6.3). QTest's helpers consult the process-global button state, which
    long e2e runs can leave stale (a leaked down bit makes a right click read
    as left); spelling every event's ``buttons`` out pins the gesture.
    """
    target = quick(window)
    QApplication.sendEvent(target, QMouseEvent(
        kind, QPointF(pos), target.mapToGlobal(pos),
        button, buttons, Qt.KeyboardModifier.NoModifier,
    ))


def click(window, pos: QPoint, *, button=Qt.MouseButton.LeftButton,
          double: bool = False) -> None:
    """A synthetic (double)click at a scene position of the island — the
    press/release(/dbl) sequence Quick sees on real hardware.
    """
    if double:
        _send_mouse(window, QEvent.Type.MouseButtonPress, pos, button, button)
        pump(1)
        _send_mouse(window, QEvent.Type.MouseButtonRelease, pos, button,
                    Qt.MouseButton.NoButton)
        pump(1)
        _send_mouse(window, QEvent.Type.MouseButtonDblClick, pos, button, button)
    else:
        _send_mouse(window, QEvent.Type.MouseButtonPress, pos, button, button)
        pump(1)
    _send_mouse(window, QEvent.Type.MouseButtonRelease, pos, button,
                Qt.MouseButton.NoButton)
    pump(1)


def click_object(window, object_name: str, *, button=Qt.MouseButton.LeftButton) -> None:
    pump(3)
    click(window, scene_point(window, item(window, object_name)), button=button)


def drag(window, start: QPoint, end: QPoint) -> None:
    """Press, one dragged move past the arming threshold, release — the
    MouseArea keeps the grab through the whole explicit-button sequence.
    """
    _send_mouse(window, QEvent.Type.MouseButtonPress, start,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    pump(1)
    _send_mouse(window, QEvent.Type.MouseMove, end,
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    pump(1)
    _send_mouse(window, QEvent.Type.MouseButtonRelease, end,
                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    pump(1)


def wheel(window, pos: QPoint, dy: int,
          modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    """One wheel notch over a scene position (the position anchors the Alt
    gesture; the tape rows live under the wheel overlay).
    """
    QApplication.sendEvent(quick(window), QWheelEvent(
        QPointF(pos), quick(window).mapToGlobal(pos),
        QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, modifiers,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))

    pump()


def pump(ticks: int = 2) -> None:
    """Turn the Qt loop enough for QML polish/animation ticks."""
    for _ in range(ticks):
        QApplication.processEvents()
        QTest.qWait(2)
