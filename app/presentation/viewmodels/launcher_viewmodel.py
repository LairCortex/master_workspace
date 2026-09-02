"""LauncherViewModel — game-catalog access for the QML launcher island.

Design D5: the Q1 launcher screen finally gets a view model. It wraps the
five synchronous ``game_manager`` catalog functions (``list_games``,
``create_game``, ``delete_game``, ``import_game``, ``read_archive_meta``)
behind a QObject with property+Signal — the catalog service itself never
reaches the QML context, only this VM does.

Binding contract (spec qml-shell «Контракт биндингов»): every method here is
synchronous; catalog exceptions (``FileExistsError``/``ValueError``)
propagate to the caller untouched so the QDialog controller can raise native
popups, and state (``games``/selection) stays untouched when a mutation
fails. The ``*Requested`` signals are emitted by the QML island — they exist
so popups are handled by the Python controller, never by QML.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot

import app.infrastructure.db.game_manager as game_manager

# Row label shown next to the name ("имя (дата_изменения)" is composed in
# QML from these roles); same format the widgets dialog used.
MODIFIED_LABEL_FORMAT = "%Y-%m-%d %H:%M"


class LauncherViewModel(QObject):
    """Sync facade over the games catalog for the launcher screen."""

    gamesChanged = Signal()
    selectionChanged = Signal()

    # Emitted from QML; the controller listens and drives native popups.
    openRequested = Signal(str)
    createRequested = Signal(str)
    deleteRequested = Signal(int)
    importRequested = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._games: list[dict] = []
        self._selected_index = -1
        self.refresh()

    # ---- QML surface (roles per design D5) ----

    def _get_games(self) -> list[dict]:
        return self._games

    games = Property(list, _get_games, notify=gamesChanged)

    def _get_selected_index(self) -> int:
        return self._selected_index

    selectedIndex = Property(int, _get_selected_index, notify=selectionChanged)

    def _get_selected_path_qml(self) -> object:
        return self._selected_path()

    # QVariant (not str): "no selection" must reach QML as null, not "".
    selectedPath = Property("QVariant", _get_selected_path_qml, notify=selectionChanged)

    # ---- Python (tests / controller) contract ----

    @property
    def selected_path(self) -> str | None:
        return self._selected_path()

    # QML calls in through meta-object slots (Qt for Python exposes
    # @Slot-decorated methods to QML only; the contract stays sync).
    @Slot(int)
    def set_selected(self, index: int) -> None:
        """Select a row by index; anything outside the list means "no selection"."""
        if not 0 <= index < len(self._games):
            index = -1
        if index == self._selected_index:
            return
        self._selected_index = index
        self.selectionChanged.emit()

    # ---- sync catalog methods (spec: exceptions propagate, state intact) ----

    def refresh(self) -> None:
        """Rescan the catalog; reset the selection when the list shrinks."""
        infos = game_manager.list_games()
        infos.sort(key=lambda info: info["modified"], reverse=True)  # newest first
        games = [
            {
                "name": info["name"],
                "modifiedLabel": info["modified"].strftime(MODIFIED_LABEL_FORMAT),
                "path": info["path"],
            }
            for info in infos
        ]
        shrunk = len(games) < len(self._games)
        self._games = games
        self.gamesChanged.emit()
        if shrunk or self._selected_index >= len(games):
            self.set_selected(-1)

    def create(self, name: str) -> str:
        """Create a game (name trimmed); ``ValueError``/``FileExistsError``
        propagate without touching VM state. Returns the new game's path."""
        path = game_manager.create_game(name.strip())
        self.refresh()
        return str(path)

    def remove(self, path: str) -> None:
        game_manager.delete_game(path)
        self.refresh()

    def import_(self, path: str) -> str:
        """Import an .nri archive; ``FileExistsError``/``ValueError`` propagate.
        Returns the imported game's path."""
        imported = game_manager.import_game(path)
        self.refresh()
        return str(imported)

    def archive_meta(self, path: str) -> dict:
        """Read archive meta without touching the catalog (or VM state)."""
        return game_manager.read_archive_meta(path)

    # ---- internals ----

    def _selected_path(self) -> str | None:
        if 0 <= self._selected_index < len(self._games):
            return self._games[self._selected_index]["path"]
        return None
