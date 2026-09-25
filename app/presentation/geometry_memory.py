"""Geometry memory of the named windows (NRI-0015 task 1.3, design T3).

The app's named windows (``main``, ``sheet_list``, ``sheet_editor``,
``sheet_fill``, ``table_host``) remember their placement between runs: the
placements live in ``UiPrefs.windows`` (ui.json, role -> ``[x, y, w, h]`` of
the window's *frame* — the rectangle the user actually drags — the one 0600
file shared with the theme). A restored placement is clamped inside a
connected screen — a window can never come back unreachable (spec
main-window «Размещение окон помнится и возвращается в экраны»), and a
window opened for the first time without a remembered role is placed at the
center of its screen, never outside it (defect B4, «редактор не рождается за
экраном»).

Save policy (T3): a move/resize burst writes the file once the window has
been quiet for ``DEBOUNCE_MS``, and closing the window saves its placement
guaranteed.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from app.infrastructure.ui_prefs.config import UiPrefsManager

#: Quiet period after the last move/resize before the placement is written.
DEBOUNCE_MS = 700

# A top-level window's frame moves/resizes arrive as these QWidget events
# (PySide 6.10 exposes no dedicated window-move event type on QEvent.Type).
_WATCHED_TYPES = frozenset({QEvent.Type.Move, QEvent.Type.Resize})


def _placeable_area(rect: QRect) -> QRect:
    """Available geometry of the screen the saved placement lives on.

    A placement whose center is on no connected screen (the monitor was
    unplugged, the resolution shrank) falls back to the primary screen —
    that is exactly where the clamp then pulls the window into.
    """
    screen = QGuiApplication.screenAt(rect.center())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    return screen.availableGeometry()


def _place_inside(
    window: QWidget, area: QRect, x: int, y: int, w: int, h: int
) -> None:
    """Land the window's *frame* at ``(x, y, w, h)``, shrunk/clamped ``area``.

    Working in frame coordinates is what makes the rule platform-honest:
    ``move()`` positions a top-level's frame and ``frameGeometry()`` reports
    it, decoration margins (the offscreen stub's 2 px border, a real window
    manager's title bar) never leak into the saved numbers. A frame bigger
    than the screen is shrunk to it first, so the clamped corner never
    strands an unreachable window with no visible part.
    """
    window.resize(w, h)
    fg = window.frameGeometry()
    dw = fg.width() - window.width()
    dh = fg.height() - window.height()
    if dw or dh:
        # Make the *client* size the one that yields the requested frame:
        # the same decoration cost the saved rect already carries.
        window.resize(max(w - dw, 1), max(h - dh, 1))
        fg = window.frameGeometry()
    if fg.width() > area.width() or fg.height() > area.height():
        window.resize(
            max(area.width() - dw, 1), max(area.height() - dh, 1)
        )
        fg = window.frameGeometry(        )
    # the minimum size may still have won — trust only what the window says
    fg = window.frameGeometry()
    x = max(area.x(), min(x, area.x() + area.width() - fg.width()))
    y = max(area.y(), min(y, area.y() + area.height() - fg.height()))
    window.move(x, y)


def _shrink_into_area(window: QWidget) -> None:
    """First-open fit (B4 pre-show half): a window bigger than its screen is
    resized to it while still hidden — the scene has not been built around
    the old size yet, so nothing relays out."""
    area = window.screen().availableGeometry()
    if window.width() > area.width() or window.height() > area.height():
        window.resize(
            min(window.width(), area.width()),
            min(window.height(), area.height()),
        )


def _center_move(window: QWidget) -> None:
    """First-open center (B4 post-show half): pure move — after show the
    window frame (decoration margins, title bar) finally exists, and moving
    a top-level never relays out its scene."""
    area = window.screen().availableGeometry()
    fg = window.frameGeometry()
    x = max(
        area.x(),
        min(
            area.x() + (area.width() - fg.width()) // 2,
            area.x() + area.width() - fg.width(),
        ),
    )
    y = max(
        area.y(),
        min(
            area.y() + (area.height() - fg.height()) // 2,
            area.y() + area.height() - fg.height(),
        ),
    )
    window.move(x, y)


class WindowGeometryMemory:
    """Restore/remember the placements of the app's named windows.

    The stored roles are read once at construction; afterwards every save
    re-reads the file so a theme written by another owner in the meantime
    survives the geometry update (the one file, the symmetric merge).
    """

    def __init__(self, prefs: UiPrefsManager) -> None:
        self._prefs = prefs
        self._roles: dict[str, list[int]] = dict(prefs.load().windows)
        # event filters die with a destroyed wrapper, keep them alive here
        self._trackers: list[_PlacementTracker] = []

    def restore(
        self, window: QWidget, role: str, *, center_when_absent: bool = False
    ) -> bool:
        """Open ``window`` at its remembered placement (clamped to a screen).

        ``center_when_absent`` is the B4 rule for roles without a saved
        placement: the window is shrunk into the screen before it shows (the
        centering move itself needs the shown frame, see
        :meth:`post_show_place`). Returns whether a placement was restored.
        """
        saved = self._roles.get(role)
        if saved is None:
            if center_when_absent:
                _shrink_into_area(window)
            return False
        x, y, width, height = saved
        area = _placeable_area(QRect(x, y, width, height))
        _place_inside(window, area, x, y, width, height)
        return True

    def post_show_place(
        self, window: QWidget, role: str, *, remembered: bool = False
    ) -> None:
        """Second half of the opening: a window without a remembered role
        finally centers after show, its frame exists; then the placement
        tracker takes over."""
        if not remembered and role not in self._roles:
            _center_move(window)
        self._trackers.append(_PlacementTracker(self, window, role))

    def attach(
        self, window: QWidget, role: str, *, center_when_absent: bool = False
    ) -> bool:
        """Restore the placement (see :meth:`restore`), then remember it: the
        window grows an own tracker that saves after move/resize quiescence
        and on close. The tracker is parented to the window (and listed), so
        it never outlives the wrapper whose events it filters."""
        restored = self.restore(window, role, center_when_absent=center_when_absent)
        self._trackers.append(_PlacementTracker(self, window, role))
        return restored

    def remember(self, role: str, window: QWidget) -> None:
        """Record the placement now: in memory (for this run's reopenings)
        and through the prefs file (for the next run)."""
        frame = window.frameGeometry()
        self._roles[role] = [frame.x(), frame.y(), frame.width(), frame.height()]
        prefs = self._prefs.load()
        prefs.windows = dict(self._roles)
        self._prefs.save(prefs)


class _PlacementTracker(QObject):
    """One window's save policy: debounced on move/resize, immediate on close."""

    def __init__(self, memory: WindowGeometryMemory, window: QWidget, role: str) -> None:
        super().__init__(window)
        self._memory = memory
        self._window = window
        self._role = role
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._save)
        window.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        et = event.type()
        if et in _WATCHED_TYPES:
            self._timer.start()  # restart the quiet period
        elif et == QEvent.Type.Close:
            self._timer.stop()
            self._save()
        return False

    def _save(self) -> None:
        self._memory.remember(self._role, self._window)
