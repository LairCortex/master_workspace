"""Game launcher dialog — choose, create or delete a game on startup.

Q1 (change add-qml-shell-launcher-pilot-q1, design D6): the frame and the
Esc/close stay native (``QDialog``), but the whole content (invitation title,
game list, «Новая игра»/«Импорт»/«Удалить»/«Открыть», theme toggle) is a
``QQuickWidget`` island loading ``app/presentation/qml/LauncherRoot.qml``.
The widgets content and the QSS attachment for it are gone: the content is
skinned by the token palette, never by QSS (spec ui-theme «Область применения
QSS»). The external contract for the application is unchanged — the
``game_selected(path)`` signal and the ``selected_path`` property.

Division of labour (design D5):

* the island binds to :class:`LauncherViewModel` (``vm``) and reads colors
  from :class:`QmlPalette` (``islandPalette``) — never the catalog service,
  never an async entry (spec qml-shell «Контракт биндингов»);
* the controller — this dialog — listens for the VM's ``*Requested`` signals,
  raises the *native* popups (``QInputDialog``/``QMessageBox``/``QFileDialog``),
  calls the sync VM method and, on success, emits ``game_selected``/closes.
  Popup choices stay out of QML.
* the island marks «Открыть» as the default action (root ``defaultButton``);
  the wrapper answers Enter through the same open path.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox, QVBoxLayout, QWidget,
)

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.viewmodels.launcher_viewmodel import LauncherViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "LauncherRoot.qml")


class GameLauncherDialog(QDialog):
    game_selected = Signal(str)  # db file path

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeRuntime) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("НРИ Сценарий Менеджер — Выбор игры")
        self.setMinimumSize(480, 400)
        self._selected_path: str | None = None

        # View model + palette live for the dialog's whole life and are its
        # children — a context property is a raw pointer, so dropping the
        # Python reference would leave QML holding a null.
        self.vm = LauncherViewModel(parent=self)
        self._palette = QmlPalette(theme, parent=self)

        layout = QVBoxLayout(self)
        # The island must reach the dialog edges: a default layout margin
        # would show the OS palette as a frame around the QML surface (spec
        # ui-theme «Лаунчер без полосы палитры ОС»).
        layout.setContentsMargins(0, 0, 0, 0)

        # The island shares the one process-wide engine (spec qml-shell
        # «Движок один на приложение»); ``setup_qml_shell`` is idempotent,
        # so the launcher shown before ``Application.start()`` is up first.
        engine = setup_qml_shell(QApplication.instance(), theme)
        # Keep a reference so the shared engine never dies under a live island
        # (test isolation resets the shell singleton between tests).
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty("vm", self.vm)
        # The QSS-``palette`` name is shadowed by Qt Quick Controls, hence
        # ``islandPalette`` (see the LauncherRoot.qml context contract).
        self.quick.rootContext().setContextProperty("islandPalette", self._palette)
        self.quick.setSource(QUrl.fromLocalFile(ROOT_QML))
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)

        self._root = self.quick.rootObject()
        self._wire_island()
        self._sync_theme()
        theme.add_listener(self._sync_theme)

    # ---- island -> controller wiring ----

    def _wire_island(self) -> None:
        self.vm.openRequested.connect(self._on_open_requested)
        self.vm.createRequested.connect(self._on_create_requested)
        self.vm.importRequested.connect(self._on_import_requested)
        self.vm.deleteRequested.connect(self._on_delete_requested)
        self._root.themeToggleRequested.connect(self._on_theme_toggle)

    def _sync_theme(self) -> None:
        """Seed the toggle's target-theme label from the runtime and re-sync
        on every change — whoever made it (this dialog, the main window)."""
        if self._root is not None:
            self._root.setProperty("currentTheme", self._theme.theme)

    # ---- controller handlers (native popups + sync VM calls) ----

    def _on_theme_toggle(self) -> None:
        self._theme.toggle()  # no-op with invalid tokens (D7); palette re-syncs

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # «Открыть» is the default action: Enter on a selected row opens it
        # (spec game-launcher). Without a selection it stays a no-op.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._open_selected()
            return
        super().keyPressEvent(event)

    def _open_selected(self) -> None:
        path = self.vm.selected_path
        if path is not None:
            self._on_open_requested(path)

    def _on_open_requested(self, path: str) -> None:
        self._selected_path = path
        self.game_selected.emit(path)
        self.accept()

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
            self.vm.remove(game["path"])  # removes + refreshes; dialog stays open

    def _on_import_requested(self, _fileName: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт игры", "",
            "NRI архив (*.nri);;Все файлы (*)",
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

    # ---- external contract (unchanged since the widgets dialog) ----

    @property
    def selected_path(self) -> str | None:
        return self._selected_path

    def _release_island(self) -> None:
        self.quick.setSource(QUrl())

    def done(self, result: int) -> None:  # QDialog API: accept/reject/close-event
        """Release the island against its VM/palette before the dialog dies.

        ``QDialog.closeEvent`` calls ``reject()`` and both accept/reject
        funnel through ``done()``. Clearing the QML source tears the island
        down while ``vm``/``_palette`` (children of the dialog) are still
        alive, so its bindings never observe a half-destroyed context.

        The release is deferred one loop turn (acceptance Q1): every
        QML-originated accept — «Открыть» click, row double-click, create-and-
        open — lands here while the island's own ``onClicked`` handler is
        still on the stack, and destroying the scene synchronously there is
        fatal («Object destroyed while one of its QML signal handlers is in
        progress»). The one-shot is bound to ``self``: it runs when the JS
        stack has unwound and never after the dialog is gone.
        """
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)

