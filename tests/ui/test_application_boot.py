"""DI smoke test: Application.start() on a scratch DB (glue-layer wiring).

Guards the catalog/wiring seam: one service catalog per game, signal
wiring connected, window shown; shutdown releases everything.
"""
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
