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
