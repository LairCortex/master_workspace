"""D&D game through the ``.nri`` archive loop (add-dnd-module-foundation, task 6.1).

Spec dnd-module-lifecycle «Данные модуля переживают архивный перенос», scenario
«Round-trip через архив»: export and import SHALL preserve the module flag,
its version and the dataset connections, and the imported game SHALL open with
the module. The archive already rides whole ``game.db`` bytes (v2 packager),
and both module facts are ``game_settings`` rows — so what THIS test pins is
the combination: rows written by the штатный production writers (the launcher's
creation seed and the typed connections repository) survive export→delete→
import byte-identically, the synchronous catalog read still stamps the game
«D&D», and a real ``Application.start`` on the imported path composes and
attaches the concrete module.

No network, no user directories: the shared HTTP client is the injected
``httpx.MockTransport`` holder (a refused-off any request the attach-time SRD
bootstrap would attempt anyway gets a Russian error and stays modeless), and
``paths.DATASETS_DIR`` is redirected to ``tmp_path`` before the composition
resolves the storage (the shelf binds the module attribute at construction).
"""
from __future__ import annotations

import sqlite3

import httpx
import pytest
from PySide6.QtWidgets import QDialog

from app.dd.module import DndModule
from app.infrastructure.db.database import create_engine, create_session_factory
from app.infrastructure.db.game_manager import (
    create_game,
    delete_game,
    export_game,
    get_db_url,
    import_game,
    list_games,
)
from app.infrastructure.db.migrations import init_db
from app.infrastructure.http.client import AppHttpClient
from app.infrastructure.repositories.game_settings_repository import (
    DND_DATASETS_KEY,
    DND_MODULE_DATA_VERSION,
    DND_MODULE_KEY,
    decode_dnd_module_flag,
    DndDatasetsRepository,
)
from app.main import DD_MODULE_PROFILE_DISABLE_ENV, Application
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from tests.test_application_settings_errors import _install_modal_trap

_CONNECTED = ["srd-2014", "хом-пак"]


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """First open of a freshly created game raises the calendar wizard on the
    deferred contour; offscreen answers it instantly (the composition-file
    convention, local copy)."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


def _settings_rows(db_path) -> dict[str, str]:
    """Raw ``game_settings`` rows — the byte-level truth the archive carries."""
    conn = sqlite3.connect(str(db_path))
    try:
        return dict(
            conn.execute("SELECT key, value FROM game_settings").fetchall()
        )
    finally:
        conn.close()


def _refused_transport() -> AppHttpClient:
    """A client that refuses every request: the attach-time SRD bootstrap
    must never reach the network from the test suite; its failure path is
    modeless and stays unasserted here."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    return AppHttpClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_dnd_game_survives_nri_roundtrip(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager.get_games_dir",
        lambda: tmp_path / "games",
    )
    # The module's global shelf belongs to the user's config home in
    # production; this test owns a throwaway one (resolved at storage
    # construction — the composition below happens after this patch).
    monkeypatch.setattr(
        "app.infrastructure.paths.DATASETS_DIR", tmp_path / "datasets"
    )

    # ── arrange: a D&D game written by the production writers ───────────────
    # The launcher's «D&D» creation seeds the flag+version through the штатный
    # codec; the connection list goes in through the typed repository.
    db_path = create_game("D&D-сага", dnd=True)
    engine = create_engine(get_db_url(db_path))
    try:
        await init_db(engine, image_dir=db_path.parent / "images")
        session = create_session_factory(engine)()
        try:
            await DndDatasetsRepository(session).save(_CONNECTED)
            await session.commit()
        finally:
            await session.close()
    finally:
        await engine.dispose()

    rows_before = _settings_rows(db_path)
    flag = decode_dnd_module_flag(rows_before[DND_MODULE_KEY])
    assert flag is not None and flag.enabled  # the seed itself is in place
    assert flag.version == DND_MODULE_DATA_VERSION  # «версию» — explicitly

    # ── act: export → remove the original → import (the archive cycle) ──────
    dest = tmp_path / "dnd-saga.nri"
    export_game(str(db_path), dest)
    delete_game(str(db_path))
    imported = import_game(dest)
    assert imported.is_file()

    # ── assert: the module facts rode through byte-identically ──────────────
    rows_after = _settings_rows(imported)
    assert rows_after[DND_MODULE_KEY] == rows_before[DND_MODULE_KEY]
    assert rows_after[DND_DATASETS_KEY] == rows_before[DND_DATASETS_KEY]
    imported_flag = decode_dnd_module_flag(rows_after[DND_MODULE_KEY])
    assert imported_flag == flag  # признак + версия preserved through the codec

    # The synchronous catalog read still stamps the imported game «D&D» —
    # the launcher would mark its row before anyone opens it.
    entry = next(g for g in list_games() if g["name"] == "D&D-сага")
    assert entry["dnd"] is True

    # The typed connection list reads back on the imported database.
    engine = create_engine(get_db_url(imported))
    try:
        session = create_session_factory(engine)()
        try:
            assert await DndDatasetsRepository(session).load() == _CONNECTED
        finally:
            await session.close()
    finally:
        await engine.dispose()

    # ── assert: the imported game OPENS with the module (spec scenario) ─────
    # This scenario half speaks about the FULL composition (the kernel-profile
    # half — the module staying out — belongs to tests/test_dd_module_profile.py,
    # which manages its own env): opt out of the profile switch explicitly so
    # the suite passes in the «ядро» acceptance run too (task 6.4 convention:
    # composition-asserting tests self-manage the switch).
    monkeypatch.delenv(DD_MODULE_PROFILE_DISABLE_ENV, raising=False)
    _install_modal_trap(monkeypatch)  # app.main.QMessageBox
    _install_modal_trap(monkeypatch, target="app.dd.module.QMessageBox")
    application = Application(qapp, http=_refused_transport())
    window = await application.start(str(imported))
    try:
        module = application._game_system_module
        assert isinstance(module, DndModule)
        assert module.enabled is True  # attached to the imported game
    finally:
        window.close()
        await application.shutdown()
