"""E2E scenario 9: export the game to a .nri archive (save dialog stubbed)."""
from __future__ import annotations

import json
import zipfile

from tests.ui import helpers
from tests.ui.conftest import query_db


async def test_export_game_creates_nri_archive(app, file_dialogs, tmp_path, wait_for):
    application, window = app

    # A game with data to export.
    await helpers.create_event_via_ui(window, wait_for, "Экспортное событие")

    export_path = tmp_path / "game_export.nri"
    file_dialogs["save"] = str(export_path)
    window.export_action.trigger()  # sync handler: export + info box (auto-accepted)
    await wait_for(lambda: export_path.exists())

    with zipfile.ZipFile(export_path) as zf:
        names = zf.namelist()
        assert "game.db" in names
        assert "meta.json" in names
        meta = json.loads(zf.read("meta.json"))
        assert meta["game_name"] == "game"
        archived_db = zf.read("game.db")

    # The archive really contains the game database with its data.
    db_copy = tmp_path / "archived.db"
    db_copy.write_bytes(archived_db)
    rows = query_db(db_copy, "SELECT name FROM events")
    assert any(name == "Экспортное событие" for name, in rows)
