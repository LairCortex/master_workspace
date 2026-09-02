"""QML engine bootstrap (change add-qml-shell-launcher-pilot-q1, tasks 3.1/3.2).

Spec qml-shell «QML-каркас приложения»: ``Application.start()`` brings up
exactly one shared ``QQmlEngine`` for the process (parented to QApplication,
so ``findChildren`` counts it), the Controls style is Basic chosen
programmatically (``QQuickStyle.name()`` — the PySide6 binding of the C++
``QQuickStyle::style()``; checked here before any QML is loaded in the test),
the engine's import path contains ``app/presentation/qml/`` (files, no qmldir
module — none is imported in conftest and none may exist yet), the token
bridge sits in the engine's root context (design D3), and a repeated
``start()`` (game switch) reuses the one engine instead of building a second
one (design D2).
"""
from __future__ import annotations

import os
from pathlib import Path

import app as app_package
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
import pytest_asyncio

from app.main import Application
from app.presentation import qml as qml_shell
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette


def shell_engines(qapp) -> list[QQmlEngine]:
    """All QQmlEngine instances the shell owns: children of the app object."""
    return qapp.findChildren(QQmlEngine)


@pytest_asyncio.fixture
async def started_app(qapp, tmp_path):
    """Application started on a scratch game DB (engine set up by start())."""
    application = Application(qapp)
    window = await application.start(str(tmp_path / "engine_game.db"))
    try:
        yield application
    finally:
        window.close()
        await application.shutdown()


# ── 3.1: exactly one engine, Basic style, import path, no qmldir ───────────


def test_exactly_one_engine_after_start(started_app, qapp):
    engines = shell_engines(qapp)
    assert len(engines) == 1
    engine = started_app.qml_engine
    assert isinstance(engine, QQmlEngine)
    # The engine the islands will be handed is that same single one, parented
    # to the application so its lifetime is the process's (design D2).
    assert engine is engines[0]
    assert engine.parent() is qapp
    # The module-level accessor hands the same engine to callers that show a
    # QML surface before/without an Application handle.
    assert qml_shell.qml_engine() is engine


def test_controls_style_is_basic_before_any_qml_load(started_app):
    # This test loads no QML: the value asserted here is the one the app set
    # at start(), i.e. before any island could import Qt Quick Controls.
    # Left to itself the style would be the native one (macOS/Windows), never
    # "Basic" — so the assertion proves the programmatic choice (design D4).
    assert QQuickStyle.name() == "Basic"


def test_engine_import_path_includes_the_qml_directory(started_app):
    # The qml sources dir as located through the installed ``app`` package,
    # independently of the shell module's own constant.
    expected = Path(app_package.__file__).resolve().parent / "presentation" / "qml"
    assert expected.is_dir()  # the directory ships with the package
    assert Path(qml_shell.QML_IMPORT_PATH) == expected

    # Qt canonicalizes imported paths — compare canonical forms.
    real_paths = {os.path.realpath(p) for p in started_app.qml_engine.importPathList()}
    assert os.path.realpath(str(expected)) in real_paths
    # No qmldir module in this chunk: islands load files, conftest imports no
    # "qml-shell" module (spec «Размещение qml-файлов и поставка»).
    assert not (expected / "qmldir").exists()


def test_palette_exposed_in_engine_root_context(started_app):
    palette = started_app.qml_engine.rootContext().contextProperty("palette")
    assert isinstance(palette, QmlPalette)
    # Shipped tokens are valid: the bridge is populated from the runtime the
    # application uses (the process-wide default here).
    theme = get_default_theme()
    assert palette.tokens
    assert palette.tokens["color.accent"] == theme.tokens["color.accent"][theme.theme]
    assert palette.changed  # the live-retheme signal the qml side connects to


# ── 3.2: repeated start() must not build a second engine ───────────────────


async def test_repeated_start_reuses_the_single_engine(qapp, tmp_path):
    """Game switch flow (shutdown → start again): one engine, same instance."""
    application = Application(qapp)
    w1 = await application.start(str(tmp_path / "one.db"))
    engine1 = application.qml_engine
    w1.close()
    await application.shutdown()

    w2 = await application.start(str(tmp_path / "two.db"))
    try:
        assert application.qml_engine is engine1
        assert len(shell_engines(qapp)) == 1
        # The context bridge survived too — islands keep one palette.
        assert (
            application.qml_engine.rootContext().contextProperty("palette")
            is engine1.rootContext().contextProperty("palette")
        )
    finally:
        w2.close()
        await application.shutdown()
