"""DI smoke test: Application.start() on a scratch DB (glue-layer wiring).

Guards the catalog/wiring seam: one service catalog per game, signal
wiring connected, window shown; shutdown releases everything.
"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import qasync
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.main import Application, _run_game_session


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


def test_normal_quit_sequence_disposes_the_game_engine(
    qapp, tmp_path, tmp_llm_config
):
    """PR-007 (lifecycle half): the ordinary exit runs ``shutdown``.

    The ``main`` session sequence (``_run_game_session``) on a real qasync
    loop: штатный startup of a fixture game, the quit landing as a window
    close while the runner's own ``run_forever`` frame is on the loop
    (closeEvent teardown + the quit the window-close drives live), then
    the exit sequence must finish the game session and dispose the engine
    — the engine and session leaving as ``None`` is what keeps the
    interpreter's collector from terminating the still-checked-out pool
    connection at exit (the stderr half is pinned subprocess-wide by
    :func:`test_normal_quit_writes_no_neglected_connection_to_stderr`;
    in-process GC of the Qt-anchored graph cannot be steered here).
    """
    from app.infrastructure.db.database import create_engine
    from app.infrastructure.db.game_manager import get_db_url
    from app.infrastructure.db.migrations import init_db
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme import ThemeRuntime

    # A shown game (the live repro opened an existing one): the wizard is
    # seeded away so the startup paints MainWindow directly on this loop.
    db_path = tmp_path / "game" / "game.db"
    (db_path.parent / "images").mkdir(parents=True)
    db_path.touch()

    # A sync test starts with no running loop; None restores that state.
    prev_loop = None
    loop = qasync.QEventLoop(qapp)
    timer = QTimer()
    timer.setInterval(10)
    outer_forever = loop.run_forever
    try:
        asyncio.set_event_loop(loop)

        async def _preseed() -> None:
            engine = create_engine(get_db_url(db_path))
            await init_db(engine, image_dir=db_path.parent / "images")
            await engine.dispose()

        loop.run_until_complete(_preseed())
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE game_settings SET value='1' WHERE key='calendar_wizard_seen'"
        )
        conn.commit()
        conn.close()

        theme = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"))
        application = Application(qapp, theme=theme)

        # The window becomes visible while ``start`` still returns, so the
        # quit tick may only arm once the runner's own ``run_forever`` is
        # the outer frame: the spy counts loop entries (``run_until_complete``
        # runs its future through an inner one) and arms the tick on the
        # second — a quit landing in the inner frame would strand the
        # session run_forever without a quit (idle exec forever).
        def _quit_like_user() -> None:
            if application._window is not None and application._window.isVisible():
                timer.stop()
                application._window.close()
                qapp.quit()

        loop_entries = 0
        quit_armed = False

        def _armed_forever() -> None:
            nonlocal loop_entries, quit_armed
            loop_entries += 1
            if loop_entries == 2 and not quit_armed:
                quit_armed = True
                timer.timeout.connect(_quit_like_user)
                timer.start()
            return outer_forever()

        loop.run_forever = _armed_forever
        _run_game_session(application, loop, str(db_path))
        loop.run_forever = outer_forever
        timer.stop()
        try:
            timer.timeout.disconnect(_quit_like_user)
        except RuntimeError:
            pass  # never armed — nothing connected

        async def _settle() -> None:
            from tests.ui import helpers

            await helpers.wait_until_settled(15.0)

        loop.run_until_complete(_settle())

        # The exit sequence owns the session and the engine away; the
        # exit used to stop at ``run_forever`` and left both alive.
        assert application.engine is None
        assert application._session is None
    finally:
        timer.stop()
        loop.run_forever = outer_forever
        loop.close()
        asyncio.set_event_loop(prev_loop)


# The штатный exit in a real interpreter: the PR-007 noise is emitted by
# the GC at process exit, so the stderr half is pinned on a real process —
# exactly the live Cmd+Q measurement (offscreen platform, throwaway game,
# the same ``_run_game_session`` sequence), only smaller and repeatable.
_EXIT_SCRIPT = '''
import asyncio
import sqlite3
import sys
from pathlib import Path

import qasync
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import app.infrastructure.llm.config as llm_config_module

llm_config_module.CONFIG_FILE = Path(sys.argv[1])

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.game_manager import get_db_url
from app.infrastructure.db.migrations import init_db
from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme import ThemeRuntime
from app.main import Application, _run_game_session

db_path = Path(sys.argv[2])
qapp = QApplication([])


async def _preseed() -> None:
    engine = create_engine(get_db_url(db_path))
    await init_db(engine, image_dir=db_path.parent / "images")
    await engine.dispose()


pre_loop = asyncio.new_event_loop()
pre_loop.run_until_complete(_preseed())
pre_loop.close()

conn = sqlite3.connect(db_path)
conn.execute(
    "UPDATE game_settings SET value='1' WHERE key='calendar_wizard_seen'"
)
conn.commit()
conn.close()

loop = qasync.QEventLoop(qapp)
asyncio.set_event_loop(loop)
theme = ThemeRuntime(prefs=UiPrefsManager(Path(sys.argv[3])))
application = Application(qapp, theme=theme)

timer = QTimer()
timer.setInterval(10)


def _quit_like_user() -> None:
    if application._window is not None and application._window.isVisible():
        timer.stop()
        application._window.close()
        qapp.quit()


timer.timeout.connect(_quit_like_user)
outer_forever = loop.run_forever
entries = 0


def _armed_forever() -> None:
    # Arm the quit only on the runner's own ``run_forever`` frame (the
    # first entry is ``run_until_complete``'s inner one; the window only
    # becomes visible while ``start`` still returns).
    global entries
    entries += 1
    if entries == 2:
        timer.start()
    return outer_forever()


loop.run_forever = _armed_forever
_run_game_session(application, loop, str(db_path))
loop.run_forever = outer_forever
timer.stop()
print("PR007-ENGINE-NONE", application.engine is None, flush=True)
print("PR007-SESSION-NONE", application._session is None, flush=True)
sys.stdout.flush()
'''


def test_normal_quit_writes_no_neglected_connection_to_stderr(tmp_path):
    """PR-007 (stderr half): a штатный exit of a real interpreter leaves no
    SQLAlchemy «non-checked-in connection» noise.

    The subprocess replays the live reproduction — open a game, close the
    window (Cmd+Q/крестик are this close + the quit it drives), let the
    interpreter die — and its stderr is the measurement. Before the fix it
    carried the pool's ``ERROR: The garbage collector is trying to clean up
    non-checked-in connection`` + the SAWarning twin (live: 798 bytes on
    both exits); the journal norm is zero such lines on штатный scenarios.
    """
    db_path = tmp_path / "game" / "game.db"
    (db_path.parent / "images").mkdir(parents=True)
    db_path.touch()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _EXIT_SCRIPT,
            str(tmp_path / "llm_config.json"),
            str(db_path),
            str(tmp_path / "ui.json"),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert "non-checked-in" not in proc.stderr, proc.stderr
    assert "SAWarning" not in proc.stderr, proc.stderr
    assert "PR007-ENGINE-NONE True" in proc.stdout, proc
    assert "PR007-SESSION-NONE True" in proc.stdout, proc
    assert proc.returncode == 0, proc.stderr
