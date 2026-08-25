"""Line-coverage gap-fillers for branches no UI flow reaches.

Pure unit tests (no full Application boot): None-guards in viewmodels,
JSON fallbacks, frozen-build path resolution, import-error branches,
ad-hoc schema-migration edge paths and service edge branches.
"""
from __future__ import annotations

import sys
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog

from app.application.services.xlsx_import_service import XlsxImportService
from app.presentation.viewmodels.entity_viewmodel import EntityViewModel
from app.presentation.viewmodels.event_dialog_viewmodel import EventDialogViewModel
from app.presentation.viewmodels.llm_viewmodel import (
    LlmViewModel,
    _default_field_prompts,
)


# ── viewmodels ────────────────────────────────────────────────────────────

async def test_entity_viewmodel_guards_without_entity():
    vm = EntityViewModel(entity_service=None)
    assert await vm.save(name="x") is None
    assert await vm.delete() is False


async def test_event_dialog_viewmodel_invalid_ranges():
    vm = EventDialogViewModel(event_service=None)
    vm.name = "Событие"
    vm.start_date = date(1300, 1, 1)
    vm.end_date = date(1299, 12, 31)  # end before start
    assert not vm.is_valid
    vm.end_date = date(1300, 2, 1)
    assert not vm.is_valid  # no characteristics and no backstory
    assert await vm.save() is None


async def test_llm_viewmodel_json_fallbacks(qapp):
    vm = LlmViewModel(
        llm_service=SimpleNamespace(),
        config_manager=SimpleNamespace(load=lambda: None),
        http=SimpleNamespace(),
    )
    vm.world_prompt_from_json("{{{not json")
    assert vm.world_prompt == ""
    vm.field_prompts_from_json("{{{not json")
    assert vm.field_prompts == _default_field_prompts()


# ── dialogs: guards outside the happy path ────────────────────────────────

def test_launcher_open_without_selection(qapp, monkeypatch):
    import app.presentation.views.game_launcher_dialog as gl

    monkeypatch.setattr(gl, "list_games", lambda: [])
    dlg = gl.GameLauncherDialog()
    dlg._on_open()  # no current item → early return
    assert dlg._selected_path is None


async def test_llm_setup_dialog_guards(qapp):
    from app.infrastructure.llm.config import LlmConfig
    from app.presentation.views.llm_setup_dialog import LlmSetupDialog

    dlg = LlmSetupDialog(config=LlmConfig())
    # Not saving → reject goes through
    dlg.reject()
    assert dlg.result() == QDialog.DialogCode.Rejected
    # Empty endpoint/model → connection check returns early, no http use
    await dlg._on_check()


# ── llm errors ────────────────────────────────────────────────────────────

def test_parse_error_message_plain_json_fallback():
    from app.infrastructure.llm.errors import parse_error_message

    # dict without error/message keys and a JSON array both fall through
    assert parse_error_message('{"detail": "oops"}') == '{"detail": "oops"}'
    assert parse_error_message("[1, 2, 3]") == "[1, 2, 3]"


# ── game manager: frozen builds + import errors ───────────────────────────

def test_games_dir_dev_and_frozen(monkeypatch, tmp_path):
    import app.infrastructure.db.game_manager as gm

    # Dev mode: project root next to the source tree
    dev_dir = gm._resolve_games_dir()
    assert dev_dir.name == "games"
    assert dev_dir == Path(__file__).resolve().parent.parent / "games"

    # Frozen (PyInstaller): directory next to the executable
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "bundle" / "nri-manager"
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    assert gm._resolve_games_dir() == tmp_path / "bundle" / "games"


def test_import_game_errors(tmp_path):
    import app.infrastructure.db.game_manager as gm

    with pytest.raises(FileNotFoundError):
        gm.import_game(tmp_path / "missing.nri")

    bad_archive = tmp_path / "bad.nri"
    with zipfile.ZipFile(bad_archive, "w") as zf:
        zf.writestr("meta.json", "{}")
    with pytest.raises(ValueError):
        gm.import_game(bad_archive)




# ── search bar: empty results with a short query ──────────────────────────

class _StubSearchVm(QObject):
    results_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.results: dict = {}


def test_search_bar_hides_empty_short_query(qapp):
    from app.presentation.views.search_bar import SearchBar

    bar = SearchBar(_StubSearchVm())
    bar.search_input.clear()
    bar._show_results()  # zero results and query shorter than 2 chars
    assert not bar.results_list.isVisible()


# ── main window path helpers: dev + frozen ────────────────────────────────

def test_main_window_path_helpers(tmp_path, monkeypatch):
    import app.presentation.views.main_window as mw

    # Dev mode
    assert mw._app_root() == Path(__file__).resolve().parent.parent
    assert mw._docs_dir().is_dir()

    # Frozen: executable inside a bundle that ships docs
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "app" / "nri"
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    assert mw._app_root() == tmp_path / "app"
    (tmp_path / "app" / "_internal" / "docs").mkdir(parents=True)
    assert mw._docs_dir() == tmp_path / "app" / "_internal" / "docs"

    # Frozen fallback: no docs anywhere near a lonely executable
    exe2 = tmp_path / "lonely" / "deeper" / "nri"
    monkeypatch.setattr(sys, "executable", str(exe2), raising=False)
    assert mw._docs_dir() == tmp_path / "lonely" / "deeper" / "_internal" / "docs"


# ── sheet_pdf fonts dir: dev + frozen ──────────────────────────────────────

def test_sheet_pdf_fonts_dir_dev_and_frozen(tmp_path, monkeypatch):
    from app.infrastructure.pdf import sheet_pdf

    # Dev mode: fonts live next to the source tree
    assert sheet_pdf._fonts_dir() == Path(sheet_pdf.__file__).resolve().parent / "fonts"

    # Frozen (PyInstaller): fonts bundled under _internal next to the executable
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "bundle" / "nri-manager"
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    rel = Path("app") / "infrastructure" / "pdf" / "fonts"
    internal = tmp_path / "bundle" / "_internal" / rel
    internal.mkdir(parents=True)
    assert sheet_pdf._fonts_dir() == internal

    # Frozen fallback: no fonts anywhere near a lonely executable
    exe2 = tmp_path / "lonely" / "nri-manager"
    monkeypatch.setattr(sys, "executable", str(exe2), raising=False)
    assert sheet_pdf._fonts_dir() == tmp_path / "lonely" / "_internal" / rel


# ── xlsx import edge branches ─────────────────────────────────────────────

class _FakeWs:
    def __init__(self, rows) -> None:
        self._rows = rows

    def iter_rows(self, values_only=None):
        return iter(self._rows)


class _FakeWb:
    def __init__(self, ws) -> None:
        self.active = ws


def _noop_service() -> XlsxImportService:
    # Services are not touched on the paths under test
    return XlsxImportService(None, None, None, None, None)  # type: ignore[arg-type]


def test_xlsx_validate_no_active_sheet(tmp_path, monkeypatch):
    import app.application.services.xlsx_import_service as xmod

    xlsx = tmp_path / "empty.xlsx"
    xlsx.write_bytes(b"")
    monkeypatch.setattr(xmod, "load_workbook", lambda *a, **k: _FakeWb(None))
    assert _noop_service().validate_file("event", str(xlsx)) == ["В книге нет активного листа."]


async def test_xlsx_import_empty_body(tmp_path, monkeypatch):
    import app.application.services.xlsx_import_service as xmod

    xlsx = tmp_path / "header-only.xlsx"
    xlsx.write_bytes(b"")
    calls = {"n": 0}

    def fake_load(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeWb(_FakeWs([("name", "start_date")]))  # validation passes
        return _FakeWb(_FakeWs([]))  # import pass sees no rows at all

    monkeypatch.setattr(xmod, "load_workbook", fake_load)
    result = await _noop_service().import_file("event", str(xlsx))
    assert result.errors == ["Файл пустой."]
    assert (result.created, result.updated) == (0, 0)


def test_xlsx_get_date_falls_through():
    # Fewer than 3 dash parts: no match, falls through to the final return
    assert XlsxImportService._get_date(("2021-02",), {"start_date": 0}, "start_date") is None
    assert XlsxImportService._get_date((None,), {"start_date": 0}, "start_date") is None


# ── schema migration edge branches ────────────────────────────────────────

class _BrokenConn:
    """PRAGMA itself fails (e.g. catalog unavailable mid-rebuild)."""

    async def exec_driver_sql(self, sql):
        raise RuntimeError("catalog unavailable")


async def test_migrate_end_dates_prAGMA_failure():
    from app.infrastructure.db.migrations import _migrate_nullable_end_dates

    await _migrate_nullable_end_dates(_BrokenConn())


class _ScalarResult:
    def __init__(self, rows, scalar) -> None:
        self._rows = rows
        self._scalar = scalar

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _NoSqlConn:
    """PRAGMA works, but the table has no sqlite_master entry."""

    async def exec_driver_sql(self, sql):
        if sql.startswith("PRAGMA table_info"):
            return _ScalarResult([(0, "end_date", "DATE", 1, None, 0)], None)
        return _ScalarResult([], None)


async def test_migrate_end_dates_missing_sql():
    from app.infrastructure.db.migrations import _migrate_nullable_end_dates

    await _migrate_nullable_end_dates(_NoSqlConn())


async def test_migrate_end_dates_fallback_rename(tmp_path):
    """DDL where the table name is not adjacent to space/paren/quotes: the
    naive replace chain misses and the first-occurrence rename is used."""
    from app.infrastructure.db.database import create_engine
    from app.infrastructure.db.migrations import _migrate_nullable_end_dates

    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'fallback.db'}")
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TABLE items\n"
                " (\n"
                "   id INTEGER NOT NULL PRIMARY KEY,\n"
                "   end_date DATE NOT NULL\n"
                " )"
            )
            await conn.exec_driver_sql(
                "INSERT INTO items (id, end_date) VALUES (1, '1200-01-01')"
            )

        async with engine.begin() as conn:
            await _migrate_nullable_end_dates(conn)

        async with engine.connect() as conn:
            notnull = 1
            for row in (await conn.exec_driver_sql("PRAGMA table_info(items)")).fetchall():
                if row[1] == "end_date":
                    notnull = row[3]
            name = (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
            )).scalar()
        assert notnull == 0
        assert name == "items"
        async with engine.connect() as conn:
            from sqlalchemy import text
            # The row survived the rebuild
            assert (await conn.execute(text("SELECT COUNT(*) FROM items"))).scalar() == 1
    finally:
        await engine.dispose()


# ── entity service: unknown relation-attr skips ───────────────────────────

async def test_entity_service_skips_unknown_relation_attrs(async_session):
    from app.infrastructure.db.models import CharacterModel, DescriptionModel
    from app.infrastructure.repositories.base_repository import BaseRepository
    from app.infrastructure.repositories.character_repository import CharacterRepository
    from app.application.services.entity_service import EntityService

    desc_repo = BaseRepository(async_session, DescriptionModel)
    svc = EntityService(CharacterRepository(async_session), desc_repo)

    desc = DescriptionModel(characteristics="c", backstory="b")
    async_session.add(desc)
    await async_session.flush()
    hero = CharacterModel(
        name="Стрелок", description_id=desc.id,
        start_date=date(1300, 1, 1), end_date=date(1300, 2, 1),
    )
    async_session.add(hero)
    await async_session.flush()

    # "bogus_attr" has no relation type at all; "items" has one, but no
    # sibling service is registered — both must be skipped, not crash.
    await svc.update_entity_with_relations(
        hero.id,
        {"name": "Стрелок-2"},
        "",
        "",
        {"bogus_attr": {"current_ids": []}, "items": {"current_ids": []}},
    )
    assert (await svc.get_entity(hero.id)).name == "Стрелок-2"


# ── AI button wiring guard ────────────────────────────────────────────────

def test_wire_ai_buttons_without_buttons_attr():
    from app.main import Application

    # A dialog object without get_ai_buttons must be a silent no-op
    Application._wire_ai_buttons(object(), object())


# ── domain: rating validation ───────────────────────────────────────────────

def test_rating_post_init_validation():
    from app.domain.entities.description import Description
    from app.domain.entities.rating import Rating

    with pytest.raises(ValueError, match="description"):
        Rating(description=None, start_date=date(1300, 1, 1))
    with pytest.raises(ValueError, match="end_date"):
        Rating(
            description=Description(characteristics="c"),
            start_date=date(1300, 2, 1),
            end_date=date(1300, 1, 1),  # before start
        )
