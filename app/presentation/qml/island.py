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
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QTimer

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

    # Qt leaves a QDialog through all three of these (done covers close()).

    def accept(self) -> None:
        self._schedule_island_release()
        super().accept()

    def reject(self) -> None:
        self._schedule_island_release()
        super().reject()

    def done(self, result: int) -> None:
        self._schedule_island_release()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt casing
        self._schedule_island_release()
        super().closeEvent(event)
