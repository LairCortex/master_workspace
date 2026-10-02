"""Game launcher — choose, create or delete a game (first screen and switch sheet).

Q1 (change add-qml-shell-launcher-pilot-q1, design D6): the whole content
(invitation title, game list, «Новая игра»/«Импорт»/«Удалить»/«Открыть»,
theme toggle) is a ``QQuickWidget`` island loading
``app/presentation/qml/LauncherRoot.qml``; the content is skinned by the token
palette, never by QSS (spec ui-theme «Область применения QSS»).

NRI-0024 (task 4.1, design Д1/Д4) splits the launcher along the three-class
window contract: the content itself becomes :class:`GameLauncherContent` —
the one island host with the controller handlers — and the two entry points
each wrap it in its contract's container:

* :class:`GameLauncherDialog` — the FIRST screen (spec game-launcher «Первый
  экран остаётся модальным»): the plain ``QDialog`` frame of ``main()``,
  ``exec()``-modality included (the chooser predates the application, there
  is no sheet stack to join it — the exception class «немодальных экранов
  два: он и главное окно»);
* :class:`GameSwitchSheet` — the «Сменить игру…» entry inside the running
  game (spec game-launcher «Смена игры открывается лаунчером-листом»): a
  ``SheetFrame`` sheet of the connector's stack, header «Сменить игру…» with
  the cancel-equal «Закрыть», opened through ``ApplicationWiring.open_sheet``.

Division of labour (design D5):

* the island binds to :class:`LauncherViewModel` (``vm``) and reads colors
  from :class:`QmlPalette` (``islandPalette``) — never the catalog service,
  never an async entry (spec qml-shell «Контракт биндингов»);
* the controller — the content widget — listens for the VM's ``*Requested``
  signals, raises the *native* popups (``QInputDialog``/``QMessageBox``/
  ``QFileDialog``), calls the sync VM method and, on success, emits
  ``gameSelected``; the HOST decides what a confirmed game means (the
  first-run frame accepts and records ``selected_path``; the switch sheet
  re-emits ``game_selected`` and the composition root rebuilds the main
  window). Popup choices stay out of QML.
* the island marks «Открыть» as the default action (root ``defaultButton``);
  Enter on the content answers through the same open path.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QVBoxLayout, QWidget,
)

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.qml.island import IslandDialogMixin
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.theme.qml_palette import QmlPalette as _QmlPalette
from app.presentation.viewmodels.launcher_viewmodel import LauncherViewModel
from app.presentation.views.sheet_frame import SheetFrame

ROOT_QML = str(Path(QML_IMPORT_PATH) / "LauncherRoot.qml")

#: The launcher surface (NRI-0016 F1, live audit 2026-09-30): 600 is the
#: ui-layout-grid step raised from 480 for the Lucide action row; it must stay
#: in sync with LauncherRoot's implicitWidth (pinned by
#: tests/presentation/test_launcher_action_row_width.py).
LAUNCHER_MIN_SIZE = QSize(600, 400)


class GameLauncherContent(IslandDialogMixin, QWidget):
    """The launcher screen: island + controller, host-agnostic.

    Owns the VM, the palette and the island lifecycle (IslandDialogMixin —
    the host schedules the deferred release from its own close route, the
    child panel never gets a closeEvent of its own), the native popups and
    the theme sync. A confirmed game leaves it as ``gameSelected(path)`` —
    the content never closes anything itself.
    """

    # The QSS-``palette`` name is shadowed by Qt Quick Controls, hence
    # ``islandPalette`` (LauncherRoot.qml context contract); the VM binds as
    # ``vm``. Both live in the content-owned context the mixin builds.
    island_context_names = {"vm": "vm"}

    #: A game was chosen (db file path) — «Открыть», Enter, or create/import
    #: auto-open (spec game-launcher); the host acts on it.
    gameSelected = Signal(str)

    def island_source(self) -> str:
        return ROOT_QML

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeRuntime) -> None:
        super().__init__(parent)
        self._theme = theme

        # View model + palette live for the content's whole life and are its
        # children — a context property is a raw pointer, so dropping the
        # Python reference would leave QML holding a null.
        self.vm = LauncherViewModel(parent=self)
        self._palette = _QmlPalette(theme, parent=self)

        layout = QVBoxLayout(self)
        # The island must reach the content's edges: a default layout margin
        # would show the OS palette as a frame around the QML surface (spec
        # ui-theme «Лаунчер без полосы палитры ОС»).
        layout.setContentsMargins(0, 0, 0, 0)

        # The island shares the one process-wide engine (spec qml-shell
        # «Движок один на приложение»); ``setup_qml_shell`` is idempotent,
        # so the launcher shown before ``Application.start()`` is up first.
        # The mixin keeps ``_engine`` referenced so the shared engine never
        # dies under a live island (test isolation resets the shell).
        self._engine = setup_qml_shell(QApplication.instance(), theme)
        self.setup_island()
        layout.addWidget(self.quick)

        self._wire_island()
        self._sync_theme()
        # D1 (NRI-0016): the wrapper C++ object survives the close under its
        # parent while the island under it is already released — the weak
        # subscription alone would keep firing ``_sync_theme`` into half-dead
        # content (the swallowed RuntimeError of the audit). The HOST drops
        # this handle on its ``finished`` (every way its window leaves the
        # screen: accept/reject/close, first-run exec, the switch sheet).
        self._theme_listener = theme.add_listener(self._sync_theme)

    def drop_theme_listener(self) -> None:
        """Unsubscribe from the process-wide runtime when the host closes."""
        self._theme.remove_listener(self._theme_listener)
        self._theme_listener = None

    # ---- island -> controller wiring ----

    def _wire_island(self) -> None:
        self.vm.openRequested.connect(self._on_open_requested)
        self.vm.createRequested.connect(self._on_create_requested)
        self.vm.importRequested.connect(self._on_import_requested)
        self.vm.deleteRequested.connect(self._on_delete_requested)
        self._root.themeToggleRequested.connect(self._on_theme_toggle)

    def _sync_theme(self) -> None:
        """Seed the theme checkbox state from the runtime and re-sync on
        every change — whoever made it (this screen, the main window)."""
        if self._root is not None:
            self._root.setProperty("currentTheme", self._theme.theme)

    # ---- controller handlers (native popups + sync VM calls) ----

    def _on_theme_toggle(self) -> None:
        self._theme.toggle()  # no-op with invalid tokens (D7); palette re-syncs

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # «Открыть» is the default action: Enter on a selected row opens it
        # (spec game-launcher). Without a selection it stays a no-op. An
        # unhandled key from the island propagates up the parent chain to
        # this widget, so one handler serves both hosts.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._open_selected()
            return
        super().keyPressEvent(event)

    def _open_selected(self) -> None:
        path = self.vm.selected_path
        if path is not None:
            self._on_open_requested(path)

    def _on_open_requested(self, path: str) -> None:
        self.gameSelected.emit(path)

    def _on_create_requested(self, _name: str) -> None:
        name, ok = QInputDialog.getText(self, "Новая игра", "Название игры:")
        if not ok or not name.strip():
            return  # empty or cancelled: no-op (spec)
        try:
            path = self.vm.create(name)  # trims; raises FileExistsError on clash
        except FileExistsError:
            QMessageBox.warning(self, "Ошибка", f"Игра '{name.strip()}' уже существует.")
            return  # launcher stays open, list unchanged
        # Success: the fresh game is already re-listed (VM refreshed) and opens
        # through the same selection signal immediately (spec game-launcher).
        self._on_open_requested(path)

    def _on_delete_requested(self, index: int) -> None:
        game = self.vm.games[index]
        reply = QMessageBox.question(
            self,
            "Удаление игры",
            f"Удалить игру \"{game['name']}\"?\nЭто действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # default «Нет» (spec)
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.vm.remove(game["path"])  # removes + refreshes; launcher stays open

    def _on_import_requested(self, _fileName: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт игры", "",
            "NRI архив (*.nri);;Все файлы (*)",
            # L1 (NRI-0014): always the Russian Qt panel, never the native one.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return  # cancelled: no-op
        try:
            meta = self.vm.archive_meta(path)
            game_name = meta.get("game_name", "???")
            exported_at = meta.get("exported_at", "—")
            version = meta.get("version", "—")
            reply = QMessageBox.question(
                self,
                "Импорт игры",
                f"Импортировать игру «{game_name}»?\n\n"
                f"Версия: {version}\n"
                f"Экспортировано: {exported_at}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,  # default «Да» (spec)
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.vm.import_(path)  # adds + refreshes the list
            QMessageBox.information(
                self, "Импорт", f"Игра «{game_name}» успешно импортирована.",
            )
        except FileExistsError:
            QMessageBox.warning(self, "Ошибка", "Игра с таким именем уже существует.")
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except Exception as e:  # an unreadable archive reports its own text
            QMessageBox.critical(self, "Ошибка импорта", str(e))


class GameLauncherDialog(QDialog):
    """The first-run modal chooser (spec game-launcher «Первый экран остаётся
    модальным»): the frame ``main()`` shows with ``exec()`` before the loop
    (and the application) exists — the contract for a choice with no
    application behind it yet.

    The frame contributes the window chrome only; the screen itself is
    :class:`GameLauncherContent`. The external contract for the application
    is unchanged since the widgets dialog — the ``game_selected(path)``
    signal and the ``selected_path`` property.
    """

    game_selected = Signal(str)  # db file path

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeRuntime) -> None:
        super().__init__(parent)
        self.setWindowTitle("Master Workspace — Выбор игры")
        # 600 step of the ui-layout-grid scale for the Lucide action row (F1);
        # the number lives with the content (LAUNCHER_MIN_SIZE).
        self.setMinimumSize(LAUNCHER_MIN_SIZE)
        self._selected_path: str | None = None

        self._content = GameLauncherContent(self, theme=theme)
        layout = QVBoxLayout(self)
        # The content must reach the dialog edges: a default layout margin
        # would show the OS palette as a frame around the QML surface (spec
        # ui-theme «Лаунчер без полосы палитры ОС»).
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._content)

        self._content.gameSelected.connect(self._on_game_chosen)
        # D1 (NRI-0016): the subscription leaves with the frame, whichever
        # way it closed (accept/reject/close, the first-run exec).
        self.finished.connect(self._content.drop_theme_listener)

    @property
    def content(self) -> GameLauncherContent:
        """The launcher screen hosted by this frame (test/user address)."""
        return self._content

    def _on_game_chosen(self, path: str) -> None:
        self._selected_path = path
        self.game_selected.emit(path)
        self.accept()

    def done(self, result: int) -> None:  # noqa: N802 — Qt API name
        # Every way this dialog leaves the screen (accept through the open
        # path, Esc reject, the window-manager close) passes through done().
        # The content is a child widget — closing the frame never reaches a
        # closeEvent of its own — so the frame releases the island here, one
        # loop turn deferred (acceptance Q1: every QML-originated accept —
        # «Открыть» click, row double-click, create-and-open — lands while
        # the island's own ``onClicked`` handler is still on the stack).
        QTimer.singleShot(0, self._content, self._content.release_island)
        super().done(result)

    # ---- external contract (unchanged since the widgets dialog) ----

    @property
    def selected_path(self) -> str | None:
        return self._selected_path


class GameSwitchSheet(SheetFrame):
    """«Сменить игру…» as a sheet of the connector's stack (NRI-0024 task
    4.1, design Д1/Д4/Д6; spec game-launcher «Смена игры открывается
    лаунчером-листом»).

    The same launcher content the first screen shows, riding the sheet
    contract instead of a second window: the header «Сменить игру…» with the
    cancel-equal «Закрыть» closes WITHOUT a choice back into the very same
    game (nothing was touched, the entry just leaves), and while the sheet
    covers the main layer the stack gate keeps every other sheet entry out
    (so the switch is single-instance without the abolished registry, Д2).
    A confirmed choice re-emits ``game_selected`` — the composition root
    owns the guard + rebuild flow (task 4.2), the sheet never rebuilds
    anything itself.

    Default size = the launcher's own surface (Д6 «смена игры — размер
    лаунчера»); sheets never remember placements, so a reopen is always this
    size (spec modal-sheets «Листы не помнят размещение»).
    """

    #: Sheet default (design Д6): the launcher's own 600×400 — at once its
    #: usability floor (the Lucide action-row gate, F1) and its size.
    DEFAULT_SIZE = LAUNCHER_MIN_SIZE

    #: A game was chosen in the content — the same path contract the
    #: first-run dialog's ``game_selected`` carries (the composition root
    #: connects the switch flow to either host unchanged).
    game_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeRuntime) -> None:
        # One windowTitle-threaded value: SheetFrame puts the same caption
        # into the header label and the title slot (spec «текст,
        # соответствующий windowTitle»).
        super().__init__("Сменить игру…", parent, theme)
        self.setMinimumSize(self.DEFAULT_SIZE)
        self.resize(self.DEFAULT_SIZE)

        self.content = GameLauncherContent(self, theme=theme)
        self.add_content(self.content)
        self.content.gameSelected.connect(self.game_selected.emit)
        # D1 (NRI-0016): the content's theme subscription leaves with the
        # sheet — every close route (header «Закрыть»/Esc → reject,
        # accept, the programmatic close of the stack teardown) passes finished.
        self.finished.connect(self._content_finished)

    def _content_finished(self) -> None:
        self.content.drop_theme_listener()

    def done(self, result: int) -> None:  # noqa: N802 — Qt API name
        # The growth/release posture of the other island-hosting sheets
        # (WorldSnapshotWindow): the content is a child widget, the sheet
        # releases its island one loop turn after every close route — never
        # inside the QML handler that confirmed the choice.
        QTimer.singleShot(0, self.content, self.content.release_island)
        super().done(result)
