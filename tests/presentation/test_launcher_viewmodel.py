"""LauncherViewModel unit tests (task 4.1, spec game-launcher + qml-shell).

The catalog is faked in-memory by monkeypatching the five ``game_manager``
functions the VM wraps (``list_games``/``create_game``/``delete_game``/
``import_game``/``read_archive_meta``) — same call-time lookup contract the
widgets dialog used, so the VM stays trivially testable (spec qml-shell
«VM не знает про QML»: no QML, no real filesystem here).
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import app.infrastructure.db.game_manager as game_manager
from app.infrastructure.db.game_manager import GameInfo
from app.presentation.viewmodels.launcher_viewmodel import LauncherViewModel

BASE_TIME = datetime(2026, 1, 1)


class FakeCatalog:
    """In-memory stand-in with the same semantics as the catalog functions."""

    def __init__(self) -> None:
        self.entries: list[GameInfo] = []
        self.calls: list[tuple] = []
        self.import_error: Exception | None = None
        self.meta_error: Exception | None = None
        self._seq = 0

    def _next_modified(self) -> datetime:
        self._seq += 1
        return BASE_TIME + timedelta(minutes=self._seq)

    # -- the five monkeypatched game_manager functions ---------------------

    def list_games(self) -> list[GameInfo]:
        # Insertion order (ascending mtime) — like the real impl the VM must
        # not rely on the catalog pre-sorting by modification time.
        self.calls.append(("list_games",))
        return [dict(e) for e in self.entries]

    def create_game(self, name: str) -> Path:
        self.calls.append(("create_game", name))
        if any(e["name"] == name for e in self.entries):
            raise FileExistsError(f"Game '{name}' already exists")
        path = f"/games/{name}/game.db"
        self.entries.append(GameInfo(name=name, path=path, modified=self._next_modified()))
        return Path(path)

    def delete_game(self, path: str) -> None:
        self.calls.append(("delete_game", path))
        self.entries = [e for e in self.entries if e["path"] != path]

    def import_game(self, archive_path) -> Path:
        self.calls.append(("import_game", str(archive_path)))
        if self.import_error is not None:
            raise self.import_error
        name = "Импортируемая"
        path = f"/games/{name}/game.db"
        self.entries.append(GameInfo(name=name, path=path, modified=self._next_modified()))
        return Path(path)

    def read_archive_meta(self, archive_path) -> dict:
        self.calls.append(("read_archive_meta", str(archive_path)))
        if self.meta_error is not None:
            raise self.meta_error
        return {"game_name": "Дар", "version": "0.15.0", "exported_at": "2026-01-02T03:04:05"}


@pytest.fixture
def catalog(monkeypatch):
    fake = FakeCatalog()
    for fn in ("list_games", "create_game", "delete_game", "import_game", "read_archive_meta"):
        monkeypatch.setattr(game_manager, fn, getattr(fake, fn))
    return fake


@pytest.fixture
def vm(catalog):
    return LauncherViewModel()


# --- refresh() ---------------------------------------------------------------


def test_refresh_empty_catalog(vm):
    assert vm.games == []


def test_refresh_fills_games_with_name_label_path(catalog, vm):
    catalog.entries.append(
        GameInfo(name="Погоня", path="/games/Погоня/game.db", modified=BASE_TIME)
    )
    vm.refresh()
    assert vm.games == [
        {
            "name": "Погоня",
            "modifiedLabel": BASE_TIME.strftime("%Y-%m-%d %H:%M"),
            "path": "/games/Погоня/game.db",
        }
    ]


def test_refresh_sorts_by_modification_time_newest_first(catalog, vm):
    catalog.entries = [
        GameInfo(name="Старая", path="/games/Старая/game.db", modified=BASE_TIME),
        GameInfo(name="Средняя", path="/games/Средняя/game.db", modified=BASE_TIME + timedelta(hours=1)),
        GameInfo(name="Новая", path="/games/Новая/game.db", modified=BASE_TIME + timedelta(hours=2)),
    ]
    vm.refresh()
    assert [g["name"] for g in vm.games] == ["Новая", "Средняя", "Старая"]


def test_refresh_emits_games_changed(catalog, vm, qtbot):
    with qtbot.waitSignal(vm.gamesChanged, timeout=1000):
        vm.refresh()


# --- create() -----------------------------------------------------------------


def test_create_trims_name_and_refreshes(catalog, vm, qtbot):
    with qtbot.waitSignal(vm.gamesChanged, timeout=1000):
        path = vm.create(" Погоня ")
    assert ("create_game", "Погоня") in catalog.calls  # trimmed before the catalog call
    assert path == "/games/Погоня/game.db"
    assert [g["name"] for g in vm.games] == ["Погоня"]


def test_create_collision_raises_and_state_unchanged(catalog, vm):
    vm.create("Погоня")
    games_before = list(vm.games)
    emissions = []
    vm.gamesChanged.connect(lambda: emissions.append(1))
    with pytest.raises(FileExistsError):
        vm.create(" Погоня ")
    assert vm.games == games_before
    assert emissions == []  # no refresh happened: state untouched


# --- remove() -----------------------------------------------------------------


def test_remove_deletes_and_updates_games(catalog, vm, qtbot):
    vm.create("Погоня")
    vm.create("Дар")
    with qtbot.waitSignal(vm.gamesChanged, timeout=1000):
        vm.remove("/games/Погоня/game.db")
    assert ("delete_game", "/games/Погоня/game.db") in catalog.calls
    assert [g["name"] for g in vm.games] == ["Дар"]


# --- import_() / archive_meta() error propagation ------------------------------


def test_import_success_adds_game(catalog, vm, qtbot):
    with qtbot.waitSignal(vm.gamesChanged, timeout=1000):
        path = vm.import_("/tmp/entry.nri")
    assert path == "/games/Импортируемая/game.db"
    assert [g["name"] for g in vm.games] == ["Импортируемая"]


@pytest.mark.parametrize("error", [FileExistsError("занято"), ValueError("битый архив")])
def test_import_propagates_errors_state_unchanged(catalog, vm, error):
    vm.create("Погоня")
    catalog.import_error = error
    games_before = list(vm.games)
    emissions = []
    vm.gamesChanged.connect(lambda: emissions.append(1))
    with pytest.raises(type(error)):
        vm.import_("/tmp/entry.nri")
    assert vm.games == games_before
    assert emissions == []


def test_archive_meta_returns_meta(catalog, vm):
    meta = vm.archive_meta("/tmp/entry.nri")
    assert meta["game_name"] == "Дар"
    assert ("read_archive_meta", "/tmp/entry.nri") in catalog.calls
    assert vm.games == []  # reading meta never touches the catalog state


@pytest.mark.parametrize("error", [FileExistsError("занято"), ValueError("Неверный формат архива")])
def test_archive_meta_propagates_errors(catalog, vm, error):
    catalog.meta_error = error
    with pytest.raises(type(error)):
        vm.archive_meta("/tmp/broken.nri")


# --- selection -----------------------------------------------------------------


def test_selection_initial_none(catalog, vm):
    vm.create("Погоня")
    vm.create("Дар")
    assert vm.selectedPath is None
    assert vm.selectedIndex == -1


def test_set_selected_updates_selected_path(catalog, vm, qtbot):
    vm.create("Погоня")  # older
    vm.create("Дар")  # newer → first row
    with qtbot.waitSignal(vm.selectionChanged, timeout=1000):
        vm.set_selected(1)
    assert vm.selected_path == "/games/Погоня/game.db"
    assert vm.selectedPath == vm.selected_path  # QML-side camelCase alias
    assert vm.selectedIndex == 1


def test_set_selected_minus_one_clears(catalog, vm):
    vm.create("Погоня")
    vm.set_selected(0)
    vm.set_selected(-1)
    assert vm.selected_path is None
    assert vm.selectedIndex == -1


def test_set_selected_out_of_range_clears(catalog, vm):
    vm.create("Погоня")
    vm.set_selected(0)
    vm.set_selected(99)
    assert vm.selected_path is None


def test_selection_reset_when_list_shrinks(catalog, vm, qtbot):
    vm.create("Альфа")
    vm.create("Бета")
    vm.create("Гамма")  # newest first: Гамма, Бета, Альфа
    vm.set_selected(1)  # «Бета»
    assert vm.selected_path == "/games/Бета/game.db"
    # Delete a *different* game: the list shrinks, the stale selection must go.
    with qtbot.waitSignal(vm.selectionChanged, timeout=1000):
        vm.remove("/games/Гамма/game.db")
    assert vm.selected_path is None
    assert vm.selectedIndex == -1


def test_selection_kept_when_list_grows(catalog, vm):
    vm.create("Альфа")
    vm.set_selected(0)
    vm.create("Бета")  # list grows, row 0 keeps pointing at the newest game
    assert vm.games[0]["name"] == "Бета"
    assert vm.selected_path == "/games/Бета/game.db"


# --- QML binding contract --------------------------------------------------------


def test_camel_case_qml_accessors_exist(catalog, vm):
    """Design D5 binding surface: games/selectedIndex/selectedPath + notify."""
    vm.create("Погоня")
    assert isinstance(vm.games, list)
    assert vm.selectedIndex == -1
    vm.set_selected(0)
    assert vm.selectedPath == "/games/Погоня/game.db"
    assert hasattr(LauncherViewModel, "gamesChanged")
    assert hasattr(LauncherViewModel, "selectionChanged")
    for requested in ("openRequested", "createRequested", "deleteRequested", "importRequested"):
        assert hasattr(LauncherViewModel, requested)


def test_vm_methods_are_all_sync(catalog, vm):
    """Spec qml-shell «Контракт биндингов»: QML may only call sync entrances.

    Signature inspection: no coroutine callable on the VM class — an
    ``async def`` sneaking in here would break the sync contract.
    """
    for name, member in inspect.getmembers(LauncherViewModel):
        if name.startswith("__"):
            continue
        if inspect.isfunction(member) or inspect.ismethod(member):
            assert not inspect.iscoroutinefunction(member), f"{name} is a coroutine"
        if isinstance(member, property) or callable(member):
            assert not inspect.iscoroutinefunction(getattr(member, "__call__", None))
