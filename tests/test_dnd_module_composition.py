"""Composition-root decision on the ``dnd_module`` flag (add-dnd-module-foundation,
task 1.2; spec dnd-module-lifecycle «Признак модуля определяет состав»,
«Испорченный признак открывает игру как обычную», version-compat scenario).

Two halves:

* the factory :func:`app.main._compose_game_system_module` — enabled+supported
  composes the concrete ``DndModule``, everything else composes the no-op stub;
  the «module asked, cannot give» branches (profile without the module —
  its own module pins the no-import rule — and a version ahead) and the
  «data hidden» branch of a stored «off» (task 2.3) return the warning body
  for the deferred show;
* the live contour through ``Application.start``: the flag is read through the
  штатный settings repository, the module is attached to the shown window and
  detached again at shutdown, and the unavailable warning rides the PR-010
  ``call_soon`` channel — the trap borrowed from
  ``tests/test_application_settings_errors.py`` turns any nested modal show
  red, while the sanctioned modeless ``show()`` is recorded. A damaged or
  ahead row is left byte-identical (the read never rewrites).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

import pytest
from PySide6.QtWidgets import QDialog
from sqlalchemy import text

from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db as raw_init_db
from app.infrastructure.db.models import Base
from app.infrastructure.repositories.game_settings_repository import (
    DND_MODULE_KEY,
    DndModuleFlag,
)
from app.main import (
    DD_MODULE_PROFILE_DISABLE_ENV,
    DD_MODULE_PROFILE_WARNING,
    DD_MODULE_UNAVAILABLE_TITLE,
    DD_MODULE_VERSION_WARNING,
    Application,
    _compose_game_system_module,
    _dd_module_disabled_by_profile,
)
from app.presentation.modules.protocol import NoopGameSystemModule
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from tests.test_application_settings_errors import _install_modal_trap


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """Freshly seeded games open the first-entry wizard inside ``start()``;
    offscreen must not block on a real modal loop (the settings-errors
    convention, local copy)."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


@pytest.fixture(autouse=True)
def default_profile(monkeypatch):
    """The module-profile switch is process-global; every test here owns its
    value explicitly — the ambient one starts clean."""
    monkeypatch.delenv(DD_MODULE_PROFILE_DISABLE_ENV, raising=False)


def _make_dd_db(tmp_path, flag_value: str | None):
    """Minimal game DB whose distinguishing row is ``dnd_module`` (``None``
    leaves it absent — the ordinary game); the rest of the schema arrives
    from ``init_db`` exactly like the settings-errors fixture shape."""
    db_path = tmp_path / "game" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE game_settings "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
        )
        if flag_value is not None:
            conn.execute(
                "INSERT INTO game_settings (key, value) VALUES (?, ?)",
                (DND_MODULE_KEY, flag_value),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _read_dnd_row(db_path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT value FROM game_settings WHERE key = ?", (DND_MODULE_KEY,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ── the factory decision (unit) ──────────────────────────────────────────────


def test_absent_flag_composes_the_stub_silently():
    module, warning = _compose_game_system_module(None)
    assert type(module) is NoopGameSystemModule
    assert warning is None


def test_disabled_flag_opens_the_stub_with_the_hidden_data_warning():
    # Task 2.3 grew this branch: a stored «off» is the game that once had the
    # module — «предупреждение о том, что модуль выключен и данные D&D
    # скрыты» rides the same deferred channel as the other warnings.
    from app.main import DD_MODULE_OFF_WARNING

    module, warning = _compose_game_system_module(
        DndModuleFlag(enabled=False, version=1)
    )
    assert type(module) is NoopGameSystemModule
    assert warning == DD_MODULE_OFF_WARNING


def test_disabled_flag_with_ahead_version_warns_about_hidden_data():
    # The version warning is for a game that ASKED for the module; a stored
    # «off» is off whatever version wrote it — but the row still proves the
    # game holds module data, so the hidden-data warning stands (task 2.3).
    from app.main import DD_MODULE_OFF_WARNING

    module, warning = _compose_game_system_module(
        DndModuleFlag(enabled=False, version=99)
    )
    assert type(module) is NoopGameSystemModule
    assert warning == DD_MODULE_OFF_WARNING


def test_enabled_supported_flag_composes_the_module():
    from app.dd import MODULE_VERSION
    from app.dd.module import DndModule

    module, warning = _compose_game_system_module(
        DndModuleFlag(enabled=True, version=MODULE_VERSION)
    )
    assert type(module) is DndModule
    assert warning is None


def test_enabled_but_too_new_opens_ordinary_with_warning_and_journal(caplog):
    module, warning = _compose_game_system_module(
        DndModuleFlag(enabled=True, version=10_000)
    )
    assert type(module) is NoopGameSystemModule
    assert warning == DD_MODULE_VERSION_WARNING
    assert "ahead" in caplog.text


def test_profile_switch_short_circuits_before_the_module_import(monkeypatch):
    monkeypatch.setenv(DD_MODULE_PROFILE_DISABLE_ENV, "1")
    module, warning = _compose_game_system_module(
        DndModuleFlag(enabled=True, version=1)
    )
    assert type(module) is NoopGameSystemModule
    assert warning == DD_MODULE_PROFILE_WARNING


def test_profile_switch_reads_exactly_one(monkeypatch):
    assert _dd_module_disabled_by_profile() is False
    monkeypatch.setenv(DD_MODULE_PROFILE_DISABLE_ENV, "0")
    assert _dd_module_disabled_by_profile() is False
    monkeypatch.setenv(DD_MODULE_PROFILE_DISABLE_ENV, "1")
    assert _dd_module_disabled_by_profile() is True


# ── the live contour through Application.start (offscreen) ──────────────────


async def test_enabled_game_starts_with_the_module_attached_and_detached(qapp, tmp_path):
    from app.dd import MODULE_VERSION
    from app.dd.module import DndModule

    db_path = _make_dd_db(
        tmp_path, json.dumps({"enabled": True, "version": MODULE_VERSION})
    )
    application = Application(qapp)
    window = await application.start(str(db_path))
    module = application._game_system_module
    try:
        assert isinstance(module, DndModule)
        assert module.enabled is True  # attached to THIS game's composition
        # no warning is due — the module is exactly what the game asked for
        await asyncio.sleep(0)
        assert application._dd_unavailable_box is None
    finally:
        window.close()
        await application.shutdown()
    # task 1.1: shutdown detaches and replaces the composition with the stub
    assert module.enabled is False
    assert type(application._game_system_module) is NoopGameSystemModule


async def test_absent_flag_game_starts_stub_silently(qapp, tmp_path, monkeypatch):
    db_path = _make_dd_db(tmp_path, None)
    boxes = _install_modal_trap(monkeypatch)
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        assert _read_dnd_row(db_path) is None  # absence is the ordinary game
        await asyncio.sleep(0)
        assert boxes == []
        assert application._dd_unavailable_box is None
    finally:
        window.close()
        await application.shutdown()


async def test_corrupt_flag_opens_ordinary_with_journal_row_untouched(
    qapp, tmp_path, monkeypatch, caplog
):
    broken = '{"enabled": "yes", "version": 1}'  # enabled is not a boolean
    db_path = _make_dd_db(tmp_path, broken)
    boxes = _install_modal_trap(monkeypatch)
    application = Application(qapp)
    with caplog.at_level(
        logging.WARNING,
        logger="app.infrastructure.repositories.game_settings_repository",
    ):
        window = await application.start(str(db_path))  # must not raise
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        # journal entry naming the key and the reason (spec «…занося в журнал»)
        assert any(
            DND_MODULE_KEY in r.getMessage() and "not a boolean" in r.getMessage()
            for r in caplog.records
        )
        # silence on screen: corruption is «module off», not a user warning
        assert boxes == []
        await asyncio.sleep(0)
        assert boxes == []
        assert application._dd_unavailable_box is None
        # the damaged row stays byte-identical — the read never rewrites
        assert _read_dnd_row(db_path) == broken
    finally:
        window.close()
        await application.shutdown()


async def test_too_new_version_opens_ordinary_deferring_one_warning(
    qapp, tmp_path, monkeypatch, caplog
):
    ahead = json.dumps({"enabled": True, "version": 10_000})
    db_path = _make_dd_db(tmp_path, ahead)
    boxes = _install_modal_trap(monkeypatch)
    application = Application(qapp)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        assert "ahead" in caplog.text
        # PR-010 posture: nothing modal on the contour…
        assert boxes == []
        # …the one warning lands on the next loop pass, modeless, Russian.
        await asyncio.sleep(0)
        assert len(boxes) == 1
        box = boxes[0]
        assert box.parent is window
        assert box.shown_via == "show"
        assert box.title == DD_MODULE_UNAVAILABLE_TITLE
        assert box.text == DD_MODULE_VERSION_WARNING
        assert application._dd_unavailable_box is box
        # closing the box drops the live ref
        for handler in box.finished.handlers:
            handler(0)
        assert application._dd_unavailable_box is None
        # the ahead row is untouched — opening old keeps newer data intact
        assert _read_dnd_row(db_path) == ahead
    finally:
        window.close()
        await application.shutdown()


# ── DENC-LIVE-2: the ladder's ring survives a game reopen (boot order) ───────


async def _seed_reopened_encounter_game(db_path) -> None:
    """The storage state of a REOPENED game: the kernel event and its live
    encounter overlay ride on disk BEFORE ``start()`` — the defect's posture,
    no in-session save participates. The dd tables are created with the same
    additive wave the module bootstrap runs at start (checkfirst there skips
    them; here the row must pre-exist)."""
    from app.dd.infrastructure.db.dd_models import DD_TABLES

    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await raw_init_db(engine)  # no image_dir: schema only (startup-tests shape)
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=DD_TABLES
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO events (id, name, start_date, end_date,"
                    " start_bc, end_bc)"
                    " VALUES (1, 'Засада у ворот', '1000-01-01', '1000-01-01', 0, 0)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO dd_encounter (event_id, composition, note)"
                    " VALUES (1, '[{\"monster_id\": 1, \"count\": 1,"
                    " \"name\": \"Тестовый Гоблин\"}]', 'засада')"
                )
            )
    finally:
        await engine.dispose()


async def test_opened_game_boot_paints_encounter_marks_without_a_save(
    qapp, tmp_path
):
    """DENC-LIVE-2 (docs/qa/2026-10-10-dnd-game-face-acceptance.md, живая
    приёмка 2026-10-11): the ring must stand on the ladder's FIRST frame of a
    reopened game — spec event-timeline «Пометка встречи на лестнице», the
    «Где у меня засада» scenario. Boot warms the external sources inside
    ``restore_preview_pins``; the module must be ATTACHED before that warm —
    a dark source's ``warm`` is its honest silence, and with the reverse
    order the first ``load_events()`` read an empty marks cache through the
    SYNC door while the live save hid the loss behind ``apply_saved``."""
    from app.dd import MODULE_VERSION
    from app.dd.presentation.dd_encounter_source import ENCOUNTER_MARK

    db_path = _make_dd_db(
        tmp_path, json.dumps({"enabled": True, "version": MODULE_VERSION})
    )
    await _seed_reopened_encounter_game(db_path)
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        event_rows = [
            row for row in application._wiring.timeline_vm.rows
            if row.kind == "event"
        ]
        assert [row.event_id for row in event_rows] == [1]
        # no save, no reload, no user gesture — the boot frame itself carries
        assert event_rows[0].marks == (ENCOUNTER_MARK,)
    finally:
        window.close()
        await application.shutdown()
