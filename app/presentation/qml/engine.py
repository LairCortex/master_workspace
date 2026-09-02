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
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtQml import QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

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
    engine = QQmlEngine(qapp)  # parented to the app: lives as long as it
    engine.addImportPath(QML_IMPORT_PATH)
    palette = QmlPalette(theme, parent=engine)  # dies with the engine
    engine.rootContext().setContextProperty("palette", palette)
    _engine = engine
    return engine


def qml_engine() -> QQmlEngine | None:
    """The shared engine when the shell is up (islands take it from here)."""
    return _engine


def reset_qml_shell() -> None:
    """Drop the shared engine (test isolation only).

    The palette subscribes to the process-wide theme runtime via the weak
    listener registry, and the tests reset that runtime per test; the engine
    must not outlive it with a stale palette. Reparenting detaches the
    engine from ``findChildren`` immediately and hands C++ ownership back to
    Python, so dropping the reference destroys it (palette child included)
    without waiting for an event loop to process ``deleteLater``.
    """
    global _engine
    if _engine is not None:
        _engine.setParent(None)
        _engine = None
