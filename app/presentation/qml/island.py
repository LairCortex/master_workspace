"""The island lifecycle shared by every QML-backed window (design D3, A5).

Each QML facade used to repeat the same four moves: build a private context
child of the shared engine's root, load a scene into its ``QQuickWidget``,
and release the scene one event-loop turn after the window closes (so the
release never runs inside the QML handler that closed the window). The mixin
owns that lifecycle: the window answers only *what* to load
(:meth:`IslandDialogMixin.island_source`) and under which context names
(:meth:`IslandDialogMixin.island_objects`).

Release trigger coverage mirrors every way a window here can leave the
screen: for the QDialog facades :meth:`accept`, :meth:`reject` and
:meth:`done` (done covers ``close()`` and the window-manager close); the
QWidget panel facades leave via :meth:`closeEvent`. Both paths are handled
here because every facade mixes this class in next to its window base.

Every close additionally waits out a nested modal/popup show (PR-003): a
static ``QFileDialog``/``QMessageBox`` show runs its own event loop INSIDE
the QML signal handler that opened it, and a close landing during that loop
would run the deferred release and the facade's ``deleteLater`` right there
— Qt 6.10 dispatches zero-timers AND DeferredDelete inside a nested loop,
destroying QML objects whose handler is still on the stack (the
«Object destroyed while one of its QML signal handlers is in progress»
abort). :meth:`_defer_close_under_modal` parks such a close and replays it
on the first loop turn with no nested show, where the stack holds only the
event dispatch.

The same facade family also owes its island the keyboard default action —
see :meth:`IslandDialogMixin.take_island_default_key`, the one bridge that
reads the root's ``defaultButton`` marker.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from app.presentation.qml.engine import (
    QML_IMPORT_PATH,
    island_context,
    load_island,
    release_island,
)

__all__ = [
    "IslandDialogMixin",
    "QML_IMPORT_PATH",
    "island_context",
    "load_island",
    "release_island",
]


class IslandDialogMixin:
    """Owns the island lifecycle for one QML window.

    Call :meth:`setup_island` where the facade used to place the widget into
    its layout (or, without a layout, right after construction). The mixin
    stores nothing the window did not store before: the widget and the VM are
    the caller's own attributes (``island_attribute`` /
    ``island_vm_attribute``); the context and component become ``_context``
    and ``_component`` exactly as the hand-written facades named them.

    Composition stays the default in this project; this mixin is the single
    sanctioned exception (design D3): the island lifecycle is inseparable from
    the window's lifetime, and a per-window delegate would repeat the same
    four lines in seventeen files.
    """

    #: Attribute of the window holding its ``QQuickWidget`` island.
    island_attribute: str = "quick"
    #: context-name -> window attribute bound into the island context
    #: (set as a class attribute in facades that bind a VM). Only the names
    #: listed here reach QML — the attribute name is never bound as a
    #: side effect (the LLM-dialog spec pins services/`vm` OUT of the
    #: context, so an implicit alias would leak exactly what isolation
    #: forbids).
    island_context_names: dict[str, str] = {}
    #: Release runs one loop turn after the window closed (acceptance Q1).
    #: The preset dialog pins the opposite rule (WA_DeleteOnClose + the
    #: qasync DeferredDelete sweep outrun the one-shot there — see the
    #: comment at its site) and sets this flag to ``False``.
    island_release_deferred: bool = True

    def island_source(self) -> str:
        """Absolute path of the island's root QML file (overridden)."""
        raise NotImplementedError

    def island_objects(self) -> dict[str, Any]:
        """Context names the island compiles against — exactly these."""
        objects = self._palette_objects()
        for name, attr in self.island_context_names.items():
            objects[name] = getattr(self, attr)
        return objects

    def _palette_objects(self) -> dict[str, Any]:
        """Context names owned by the palette.

        The palette lives on the window as ``_palette`` — the attribute name
        pre-existing test contracts read; the mixin only guarantees
        ``islandPalette`` is in the context before the scene loads.
        """
        return {"islandPalette": self._palette}

    def setup_island(self) -> None:
        """Create the widget, private context and root scene.

        The context is built AFTER the island widget so the scene is torn
        down before the objects it names (engine.island_context contract).
        """
        from PySide6.QtQuickWidgets import QQuickWidget

        from app.presentation.theme.qml_palette import QmlPalette

        engine = self._engine
        widget_name = self.island_attribute
        quick = getattr(self, widget_name, None)
        if quick is None:
            quick = QQuickWidget(engine, self)
            quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            setattr(self, widget_name, quick)
        if getattr(self, "_palette", None) is None:
            palette_theme = getattr(self, "_qml_theme", None) or self._theme
            self._palette = QmlPalette(palette_theme, parent=self)
        objects = self.island_objects()
        self._context = island_context(engine, self, **objects)
        for obj in objects.values():
            if isinstance(obj, QmlPalette):
                # The bridge dies with its context: the scene (created before
                # it) can never outlive-observe the palette.
                obj.setParent(self._context)
        # Some roots (sheet canvas) take creation-time properties; facades
        # hand them through the optional ``island_initial_properties`` and
        # hook pre/post-load steps (tooltip bridge) in ``load_island_scene``.
        self.load_island_scene(quick)
        self._root = quick.rootObject()
        assert quick.status() == quick.Status.Ready, quick.errors()

    def load_island_scene(self, quick) -> None:
        """Build the root scene in the private context (override to differ)."""
        initial: Optional[dict[str, Any]] = getattr(self, "island_initial_properties", None)
        self._component = load_island(quick, self._context, self.island_source(), initial)
        self._root = quick.rootObject()

    # ── keyboard default action: the island's own «Сохранить» ────────────────

    #: The two keys Qt's default-button machinery answers with (PR-029).
    ISLAND_DEFAULT_KEYS = (Qt.Key_Return, Qt.Key_Enter)

    def take_island_default_key(self, event) -> bool:
        """Give a default-action key to the island's ``defaultButton`` marker.

        A QML island has no ``QPushButton`` for :class:`QDialog` to auto-default,
        so every sheet with a default action has to press the marker itself.
        Reading it is one knowledge, held here (PR-029 — the event dialog and
        the entity card had simply forgotten the bridge and their Enter stayed
        dead while the marker was declared):

        * the keys are Qt's own pair, Return and numpad Enter;
        * the marker is the root's ``defaultButton`` property, duck-typed on
          ``clicked`` — an island without a marker claims nothing;
        * only an ENABLED marker claims the key: the Save of an invalid (or
          saving, or generation-locked) form is disabled, and a sheet must not
          eat the key of a form it refuses to save — the key stays where Qt
          would have left it;
        * a key the scene consumed never reaches a facade at all: a multiline
          field takes Return into its own text (the «Предыстория» newline), so
          this bridge only ever sees the keys the island let go.

        Returns True when the marker took the key; False means the caller owes
        the event to its own base (``super().keyPressEvent(event)``).
        """
        if event.key() not in self.ISLAND_DEFAULT_KEYS:
            return False
        root = getattr(self, "_root", None)
        marker = root.property("defaultButton") if root is not None else None
        clicked = getattr(marker, "clicked", None) if marker is not None else None
        if clicked is None or marker.property("enabled") is False:
            return False
        clicked.emit()
        return True

    # ── release: one loop turn after the window closed, never inside QML ──

    def release_island(self) -> None:
        """Run the deferred release step (kept by the old test contracts)."""
        self._release_island()

    def _release_island(self) -> None:
        """Unbind the island; facades with per-window resources override
        their cleanup and chain to this (image maps the scene may still
        reference are cleared before the island dies).

        The window-owned palette is unsubscribed from the theme runtime here
        (DEFECT-1, spec app-logging «Слушатели состояния не переживают окно»):
        once released, this island never paints again, and its palette's C++
        side is on the way out with the context — the wrapper surviving it
        must not stay a live theme listener (weakness and destroyed-signals
        are both unreliable; see qml_palette for the measurements).
        """
        palette = getattr(self, "_palette", None)
        if palette is not None:
            palette.detach()
        release_island(getattr(self, self.island_attribute, None))

    def _schedule_island_release(self) -> None:
        if self.island_release_deferred:
            QTimer.singleShot(0, self, self.release_island)
        else:
            # Pinned synchronous release (the preset dialog's WA_DeleteOnClose
            # race, documented at its flag site).
            self.release_island()

    # ── close: parked while a nested modal/popup show is in progress ────────

    #: One parked close at most (the first press wins, re-presses ignored
    #: until it replays). Class-level default: the instance gains the slot
    #: only while a close is actually parked.
    _pending_close = None

    def _close_is_nested(self) -> bool:
        """True while a nested exec() loop could run this window's teardown.

        The loop-depth fact this module can observe: Qt tracks the one modal
        widget and the one active popup for the application, and both exist
        exactly while their static convenience show (``getOpenFileName``,
        ``getSaveFileName``, ``QMessageBox.question``, ``QMenu.exec``) blocks
        inside the QML handler that opened it. A modal that IS this window
        (a launcher under its own ``exec()``) is not a nesting above the
        handler stack — that close has to run synchronously, or the show it
        answers could never end.
        """
        app = QApplication.instance()
        modal = app.activeModalWidget()
        if modal is not None and modal is not self:
            return True
        return app.activePopupWidget() is not None

    def _defer_close_under_modal(self, close_call) -> bool:
        """Park the public close while a nested show runs; else let it pass.

        Returns True when the caller must not proceed: the close rides a
        zero-timer that re-arms every loop turn it still finds a nested show
        (zero-timers fire inside nested loops — the one-shot alone is what
        PR-003 died of), and replays the PUBLIC entry (``self.accept`` and
        friends, never a bound ``super()``) so the replayed close walks the
        exact same scheduling path a normal one does.
        """
        if not self._close_is_nested():
            return False
        if self._pending_close is None:
            self._pending_close = close_call
            QTimer.singleShot(0, self, self._run_pending_close)
        return True

    def _run_pending_close(self) -> None:
        if self._pending_close is None:
            return
        if self._close_is_nested():
            QTimer.singleShot(0, self, self._run_pending_close)
            return
        close_call, self._pending_close = self._pending_close, None
        close_call()

    # Qt leaves a QDialog through all three of these (done covers close()).

    def accept(self) -> None:
        if self._defer_close_under_modal(self.accept):
            return
        self._schedule_island_release()
        super().accept()

    def reject(self) -> None:
        if self._defer_close_under_modal(self.reject):
            return
        self._schedule_island_release()
        super().reject()

    def done(self, result: int) -> None:
        if self._defer_close_under_modal(lambda: self.done(result)):
            return
        self._schedule_island_release()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt casing
        # Parked as ``self.close`` (not this event): a QCloseEvent is owned
        # by the dispatch it arrived with and must not outlive it. Qt 6
        # treats a SILENT closeEvent as an accepted close (measured: the
        # widget hides), so the park must ignore this event explicitly —
        # the window stays open until the replayed close() walks the whole
        # chain on the outer loop.
        if self._defer_close_under_modal(self.close):
            event.ignore()
            return
        self._schedule_island_release()
        super().closeEvent(event)
