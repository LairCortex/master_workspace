# Environment ordering: QT_QUICK_BACKEND must be set here — before any QML
# surface is created (the QSG backend env var is read lazily at first render),
# so this conftest import precedes every Qt Quick usage in the suite.
# Decision (task 1.2, spec qml-shell «Тестирование QML-поверхностей»): the
# software backend renders QQuickWidget under QT_QPA_PLATFORM=offscreen and
# grab() yields the expected pixel locally (macOS, PySide6 6.10.2 — see
# tests/test_qml_render_smoke.py), so pixel acceptance keeps grab()+hex-token
# convention; the spec's fallback (status/property checks without grab()) is
# NOT enabled — if some CI OS fails to render, apply it there only (task 9.1).
import os

os.environ["QT_QUICK_BACKEND"] = "software"

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.infrastructure.db.database import create_engine as app_create_engine
from app.infrastructure.db.models import Base


@pytest.fixture(autouse=True)
def isolated_ui_theme_defaults(tmp_path, monkeypatch):
    """No test may read or write the developer's real ~/.nri_manager/ui.json.

    The process-wide theme runtime is a singleton (Application default, table
    host); resetting it per test also keeps chrome widgets registered by one
    test from being recolored by the next one.
    """
    from app.infrastructure.ui_prefs import config as ui_prefs_config
    from app.presentation import theme as theme_package

    monkeypatch.setattr(ui_prefs_config, "CONFIG_FILE", tmp_path / "ui.json")
    theme_package.reset_default_theme()
    yield
    theme_package.reset_default_theme()


@pytest.fixture(autouse=True)
def isolated_qml_shell():
    """QML engine singleton isolation next to the theme-runtime reset above.

    The shell's palette lives inside the one process-wide QQmlEngine and
    tracks the process-wide theme runtime through a weak listener; the
    fixture above drops that runtime after every test, so the engine must
    die with it — otherwise tests would inherit a palette frozen on a dead
    runtime and leaked QQmlEngine children would break the "exactly one
    engine" assertion in tests/presentation/test_qml_engine.py.
    """
    from app.presentation.qml.engine import reset_qml_shell

    reset_qml_shell()
    yield
    reset_qml_shell()


@pytest_asyncio.fixture
async def async_engine():
    # App's create_engine registers a unicode-aware SQLite lower() —
    # fixtures must match runtime behavior for case-insensitive search.
    engine = app_create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine):
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
