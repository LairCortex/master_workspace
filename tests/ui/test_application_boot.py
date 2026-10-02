"""DI smoke test: Application.start() on a scratch DB (glue-layer wiring).

Guards the catalog/wiring seam: one service catalog per game, signal
wiring connected, window shown; shutdown releases everything.
"""
import json

from PySide6.QtWidgets import QApplication

from app.main import Application


async def test_application_start_smoke(qapp, tmp_path):
    db_path = str(tmp_path / "smoke.db")
    application = Application(qapp)
    window = await application.start(db_path)
    try:
        assert window is not None
        # Catalog built once per game
        assert set(application._entity_services) == {
            "organization", "character", "item", "location",
        }
        # Thin wrapper resolves from the catalog
        assert application._get_entity_service("character") is not None
        assert application._get_entity_service("nope") is None
        # Sibling wiring for link-only relation sync
        char_svc = application._entity_services["character"]
        assert char_svc._related_services["item"] is application._entity_services["item"]
        # Timeline loaded (empty for a fresh game)
        assert window.timeline_widget is not None
    finally:
        window.close()
        await application.shutdown()


async def test_application_start_twice_switches_game(qapp, tmp_path):
    """start() twice (game switch): catalog rebuilt, old window closed."""
    application = Application(qapp)
    w1 = await application.start(str(tmp_path / "one.db"))
    # Real switch flow (menu action): shutdown first, then start the new game
    await application.shutdown()
    w2 = await application.start(str(tmp_path / "two.db"))
    try:
        assert w1 is not w2
        assert not w1.isVisible()
        assert "two" in w2.windowTitle()
    finally:
        await application.shutdown()


async def test_startup_with_legacy_geometry_roles_is_silent(qapp, tmp_path, wait_for):
    """NRI-0024 task 6.1 — spec main-window «Сохранённая роль упразднённого
    окна не мешает»: ui.json still carries the frames the retired ``world_
    snapshot``/``table_host`` roles had. The boot survives the stale file,
    the keys lead to no window (the geometry memory tracks the live roles
    only), a sheet still opens at its default size, and the close-time save
    does not aggressively repair the file — the stale keys ride through
    byte-for-byte next to the saved ``main`` placement."""
    ui_file = tmp_path / "ui.json"
    stale = {
        "world_snapshot": [99999, 99999, 480, 700],
        "table_host": [8000, 8000, 640, 480],
    }
    ui_file.write_text(
        json.dumps({"theme": "dark", "windows": dict(stale)}),
        encoding="utf-8",
    )

    from tests.ui import helpers

    application = Application(qapp)
    window = await application.start(str(tmp_path / "legacy_prefs.db"))
    try:
        # The boot ran without error on the stale file; the main window
        # opens under its no-placement default and the stale keys stay
        # inert data in the memory.
        assert window.isVisible()
        tracked_roles = {t._role for t in application._geometries._trackers}
        assert tracked_roles == {"main"}
        # The stale frames led to no window: no top level sits on them
        # (clamping aside — the roles are never even looked up).
        stale_frames = {tuple(v) for v in stale.values()}
        visible_frames = {
            w.frameGeometry().getRect()
            for w in QApplication.topLevelWidgets()
            if w.isVisible()
        }
        assert not stale_frames & visible_frames

        # «листы открываются в дефолтном размере»: dismiss the boot wizard
        # (a sheet — it gates the sheet-opening entries), open «Обзор мира…».
        await wait_for(lambda: application._calendar_wizard is not None)
        await helpers.wait_until_settled()
        application._calendar_wizard.reject()
        await wait_for(lambda: application._calendar_wizard is None)
        # Height the sheet rule reads (parent − 40); the offscreen screen is
        # 800 px tall, so a shown default window lands a stub-border shorter.
        window.resize(1280, 800)
        window.world_snapshot_action.trigger()
        sheet = application._wiring.snapshot_sheet
        assert sheet is not None and sheet.isVisible()
        assert sheet.size().width() == 520
        assert sheet.size().height() == 760  # the default, never the stale 480×700
        sheet.close()
        await helpers.wait_until_settled()
    finally:
        window.close()  # the close-time save of the «main» role
        await application.shutdown()

    # No aggressive repair: the save kept the theme, wrote the live role
    # (the window's own frame, wherever it stands) and left the retired
    # roles' keys exactly where they were.
    data = json.loads(ui_file.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"  # the theme owner's field survived too
    windows = data["windows"]
    assert windows["world_snapshot"] == stale["world_snapshot"]
    assert windows["table_host"] == stale["table_host"]
    # the live role saved through the file: a well-shaped frame, written by
    # the close tracker, not by the stale data.
    assert windows["main"] != stale["world_snapshot"]
    assert [type(n) for n in windows["main"]] == [int, int, int, int]
