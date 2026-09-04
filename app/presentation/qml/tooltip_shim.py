"""Tooltip shim of the nri.components library (change
port-event-timeline-qml-island-q2-5a, tasks 2.1–2.2; design D9).

The library owns the *declaration*, the island's Python side owns the
*showing* (spec qml-shell «Нативный шим всплывающих подсказок для островов»),
and this module is the shared Python half of that contract. It contains:

* :class:`Nri` — the library's tooltip-declaration scope. An island declares
  a tooltip exactly in the design's example form::

      ThemeButton { Nri.tooltip: "Добавить событие" }        // static
      Rectangle   { Nri.tooltip: "Событие: " + name }        // dynamic binding

  The declaration lives on a per-item :class:`NriAttached` object that the
  engine creates lazily on the first assignment and parents to the host item
  (it dies with the control). Why not plain-QML: the QML engine resolves the
  ``Name.prop:`` scope against the *host object's* attached-object factory —
  attached types are registered metadata, and a QML-defined type has none
  (“Non-existent attached object” in 6.10 is the honest failure for a
  QML-only carrier). So the carrier is a Python type registered into the very
  module URI ``nri.components`` builds from its qmldir: the engine merges
  registered types and qmldir file entries into one import surface, so an
  island still gets the whole library from a single ``import
  nri.components`` (no extra qmldir entry: a file-type entry would name a
  ``Nri.qml`` that does not ship — it would break the qmldir entries
  contract and PyInstaller's qmlimportscanner for nothing).
* :class:`IslandTooltipBridge` — the per-island shared bridge (design D9:
  «мост-сигнал — общий контракт острова»), and
  :func:`install_island_tooltips` — the facade-side wiring helper.

Registration facts the tests pin:

* :func:`register_tooltip_shim` is guarded to run exactly once per process
  (importing this module does it, and every ``setup_qml_shell`` call re-
  asserts it). Re-registering is NOT a harmless overwrite: PySide6 rebuilds
  the Python class's meta-object on every ``qmlRegisterType``-family call,
  and rebuilt attached-type identity silently splits the attached-object
  lookups between the engine's meta-object and the Python-side wrapper's one
  (QML keeps seeing its declarations, ``qmlAttachedPropertiesObject`` reads
  ``None``) — the once-guard is what keeps the two halves on the same key.
* The registration is process-wide and outlives engine resets; an island
  must never register the scope itself.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, Property, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtQml import QmlAttached, qmlRegisterUncreatableType
from PySide6.QtWidgets import QToolTip

# The library module URI the scope ships under — the same URI its qmldir
# file builds; the registered scope and the qmldir file entries become one
# import surface (islands import the module once, get both).
_COMPONENTS_URI = "nri.components"
_SCOPE_VERSION = (1, 0)
_SCOPE_NAME = "Nri"
_SCOPE_NOT_INSTANTIABLE = (
    "Nri is a tooltip-declaration scope (attached property `Nri.tooltip`), "
    "not an instantiable type"
)


class NriAttached(QObject):
    """Per-item tooltip declaration attached from the ``Nri`` scope.

    The only payload is ``tooltip`` — display never starts from here (design
    D9: the mechanism stays on the island's Python side; empty text simply
    means "no tooltip for this item"). The live ``tooltipChanged`` notify is
    what makes a dynamic declaration *look* live to every reader, including
    QML read-backs like ``(target).Nri.tooltip``.
    """

    tooltipChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tooltip = ""

    def _get_tooltip(self) -> str:
        return self._tooltip

    def _set_tooltip(self, text: str) -> None:
        if self._tooltip == text:
            return
        self._tooltip = text
        self.tooltipChanged.emit()

    tooltip = Property(str, _get_tooltip, _set_tooltip, notify=tooltipChanged)


@QmlAttached(NriAttached)
class Nri(QObject):
    """QML-scope carrier: ``Nri.tooltip: "…"`` attaches a declaration to the
    declared item (registered uncreatable, see ``register_tooltip_shim``).

    The factory below is attached-object plumbing mirrored from PySide6's
    attached-properties example — shiboken calls it with the host object and
    the engine keeps the returned object alive as the host's attached
    object.
    """

    @staticmethod
    def qmlAttachedProperties(self, o):  # noqa: ANN001, N805 — shiboken's fixed two-argument call
        return NriAttached(o)


_registered = False


def register_tooltip_shim() -> None:
    """Register the ``Nri`` scope into ``nri.components`` (design D9).

    Idempotent by module flag: every ``setup_qml_shell`` re-asserts it, but
    the actual ``qmlRegisterUncreatableType`` runs exactly once per process —
    re-registering would rebuild ``Nri``'s meta-object and split attached
    lookups between engines (see module docstring).

    Uncreatable on purpose: ``Nri`` is only ever a declaration scope, and the
    "типа контракт" of task 2.1 is that ``Nri {}`` — a stray instantiation —
    reports the reason instead of silently creating a useless object.
    """
    global _registered
    if _registered:
        return
    qmlRegisterUncreatableType(
        Nri, _COMPONENTS_URI, _SCOPE_VERSION[0], _SCOPE_VERSION[1],
        _SCOPE_NAME, _SCOPE_NOT_INSTANTIABLE,
    )
    _registered = True


class IslandTooltipBridge(QObject):
    """One island's tooltip bridge — the shared QML→Python display contract.

    The QML side reports ``(text, position)`` by *emitting* the
    ``tooltipRequested`` signal (calling a signal is legal QML); the Python
    facade already listens (connected in ``__init__``, so no island wiring
    can forget it). ``position`` is in the island's scene coordinates —
    exactly what ``HoverHandler``'s ``point.scenePosition`` carries — and the
    bridge maps it to global and shows the app's single tooltip widget with
    it: ``QToolTip`` (already themed by the shared popup sheet, so the
    tooltip works both in-skin and off-skin; no QML overlay is ever created).

    The recommended per-control glue, mirrored from design D9 («наведение QML
    передаёт текст+локальные координаты мосту фасада») — read at hover time,
    so a dynamic text is current without re-loading the island::

        ThemeButton {
            Nri.tooltip: "Открыть период"   // static OR a live binding
            HoverHandler {
                onHoveredChanged: {
                    if (hovered)
                        tooltipBridge.tooltipRequested(
                            (parent).Nri.tooltip, point.scenePosition)
                    else
                        tooltipBridge.tooltipRequested("", Qt.point(0, 0))
                }
            }
        }

    An empty text releases the tooltip (``QToolTip.hideText``).
    ``last_request`` records the most recent report so smoke tests can pin
    the bridge contract itself; the QToolTip outcome is asserted separately.
    """

    tooltipRequested = Signal(str, QPointF)

    def __init__(self, island: QQuickWidget, parent: QObject | None = None) -> None:
        super().__init__(parent if parent is not None else island)
        self._island = island
        self._last: tuple[str, QPointF] | None = None
        self.tooltipRequested.connect(self._show_or_release)

    @property
    def last_request(self) -> tuple[str, QPointF] | None:
        """The last ``(text, scene-position)`` pair the island reported."""
        return self._last

    def _show_or_release(self, text: str, scene_pos: QPointF) -> None:
        self._last = (text, scene_pos)
        if text:
            QToolTip.showText(
                self._island.mapToGlobal(scene_pos.toPoint()), text, self._island
            )
        else:
            QToolTip.hideText()


def install_island_tooltips(
    island: QQuickWidget, context=None  # noqa: ANN001 — QQmlContext, late import avoided
) -> IslandTooltipBridge:
    """Put a fresh bridge in the island's root context as ``tooltipBridge``.

    Like ``vm``/``islandPalette`` (design D1), a context property is a raw
    pointer: the bridge is parented to the island so QML never reads a
    dangling null. The widget's root context *is* the shared engine context
    — same known seam the existing islands live on; a facade that builds its
    own child context (concurrent islands, e.g. the Q2b panels reusing this
    bridge) passes it as ``context``.
    """
    bridge = IslandTooltipBridge(island)
    (context if context is not None else island.rootContext()).setContextProperty(
        "tooltipBridge", bridge
    )
    return bridge
