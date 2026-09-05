"""The process-wide QML engine (design D2): created once, shared by islands.

QtWidgets stays the application owner (design D1); every ``QQuickWidget``
island is handed this one engine — repeated bootstrap calls (game switch,
several islands) must never build a second one (spec qml-shell «Движок один
на приложение»).

Setup order facts pinned by tests/presentation/test_qml_engine.py:

* ``QQuickStyle.setStyle("Basic")`` runs once, before any Qt Quick Controls
  type can be loaded — Qt refuses a later style change (design D4, no conf
  file). PySide6 exposes the current style as ``QQuickStyle.name()``.
* The engine is parented to the ``QApplication``, so its lifetime is the
  process's and ``app.findChildren(QQmlEngine)`` counts the shells honestly.
* The import path is the file directory of the qml sources
  (:data:`QML_IMPORT_PATH`); Qt canonicalizes it and silently drops a
  non-existent path, hence the directory ships in the package (and, from
  group 8 on, in the PyInstaller bundle as ``datas``).
* ``QmlPalette`` is placed in the root context once (design D3); live
  retheme arrives via the palette's own signal, never by re-creating the
  engine or its context.
* ``register_tooltip_shim`` runs before the engine exists: the library's
  attached tooltip scope ``Nri`` (qml-components delta, design D9) must be
  registered before any island importing ``nri.components`` compiles it.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtQml import QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from app.presentation.qml.sheet_font import register_sheet_font
from app.presentation.qml.sheet_image_provider import register_sheet_image_provider
from app.presentation.qml.tooltip_shim import register_tooltip_shim
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime

# Import-path root for the island sources. Computed from this module's own
# location so a frozen bundle resolves it relative to the deployed layout.
QML_IMPORT_PATH = str(Path(__file__).resolve().parent)

_engine: QQmlEngine | None = None


def setup_qml_shell(qapp: QApplication, theme: ThemeRuntime) -> QQmlEngine:
    """Return the one shared engine, creating it on the first call.

    Called from ``Application.start()`` (and callable earlier by whoever must
    show a QML surface first, e.g. the launcher in ``main()``) — idempotent,
    so no caller can race a second engine into existence.
    """
    global _engine
    if _engine is not None:
        return _engine
    # Design D4: Basic chosen programmatically before the first Controls
    # import; the process-wide name is set exactly once, here.
    QQuickStyle.setStyle("Basic")
    # Design D9 (change port-event-timeline-qml-island-q2-5a): the library's
    # tooltip-declaration scope `Nri` is registered into the nri.components
    # import space before any island can load; the registration is
    # process-wide and idempotent, islands never register it themselves.
    register_tooltip_shim()
    # Change Q3b (D7): the bundled sheet font is registered here — before any
    # island (canvas included) can paint — once for the process, exactly as
    # the widgets canvas used to do at its own import time.
    register_sheet_font()
    engine = QQmlEngine(qapp)  # parented to the app: lives as long as it
    engine.addImportPath(QML_IMPORT_PATH)
    # Change Q3b (D7): ``image://sheet/<imageId>`` resolves picture-field
    # bytes through the ImageStore; registration is idempotent per engine and
    # belongs to the shell because every island shares this engine.
    register_sheet_image_provider(engine)
    palette = QmlPalette(theme, parent=engine)  # dies with the engine
    engine.rootContext().setContextProperty("palette", palette)
    # Q3a NOTE (apply-stage): no ``islandPalette`` is registered here. Widgets
    # built on one engine share the engine's root context (verified: a
    # ``setContextProperty`` from one island's ``rootContext()`` resolves in
    # every other island on the engine), so the library-bridge name belongs to
    # the island that builds the surface — the launcher/timeline contract puts
    # a dialog/panel-owned ``QmlPalette`` into that context before
    # ``setSource`` (roadmap: «в контекст острова — … и islandPalette»). An
    # engine-lifetime registration here would make the pinned off-skin
    # scenario «прогон вовсе без islandPalette в контексте» unrepresentable.
    _engine = engine
    return engine


def qml_engine() -> QQmlEngine | None:
    """The shared engine when the shell is up (islands take it from here)."""
    return _engine


def reset_qml_shell() -> None:
    """Drop the shared engine (test isolation only).

    The palette subscribes to the process-wide theme runtime via the weak
    listener registry, and the tests reset that runtime per test; the engine
    must not outlive it with a stale palette.

    Destruction order is islands then engine: a ``QQuickWidget`` destructor
    talks to the engine, so a live scene on a dead engine is use-after-free.
    Pending ``deleteLater`` and zero-timer ``_release_island`` callbacks run
    first, while the engine is still alive; leftover islands are unbound
    (``setSource(QUrl())``) and deleted immediately; only then is the engine
    reparented and dropped.
    """
    global _engine
    if _engine is None:
        return

    from PySide6.QtCore import QCoreApplication, QEvent, QUrl
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import asyncio
    import contextlib
    import shiboken6

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    created_loop = None
    previous_loop = None
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        with contextlib.suppress(RuntimeError):
            previous_loop = asyncio.get_event_loop()
        created_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(created_loop)
    try:
        QTest.qWait(5)

        app = QApplication.instance()
        living: list = []
        seen: set[int] = set()
        for top in list(app.topLevelWidgets()):
            with contextlib.suppress(RuntimeError):
                children = list(top.findChildren(QQuickWidget))
                widgets = ([top] if isinstance(top, QQuickWidget) else []) + children
                for widget in reversed(widgets):
                    key = id(widget)
                    if key not in seen:
                        seen.add(key)
                        living.append(widget)

        for widget in living:
            with contextlib.suppress(RuntimeError):
                widget.hide()
                widget.setSource(QUrl())
                widget.setParent(None)

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QTest.qWait(1)

        for widget in living:
            with contextlib.suppress(RuntimeError):
                if shiboken6.isValid(widget):
                    shiboken6.delete(widget)

        _engine.clearComponentCache()
        _engine.collectGarbage()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        _engine.setParent(None)
        _engine = None
    finally:
        if created_loop is not None:
            created_loop.close()
            asyncio.set_event_loop(previous_loop)
