"""Game launcher dialog — choose, create or delete a game on startup."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app.infrastructure.db.game_manager import (
    create_game, delete_game, import_game, list_games, read_archive_meta,
)
from app.presentation.theme.catalog import attach_theme, title


class GameLauncherDialog(QDialog):
    game_selected = Signal(str)  # db file path

    def __init__(self, parent: QWidget | None = None, theme=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("НРИ Сценарий Менеджер — Выбор игры")
        self.setMinimumSize(480, 400)
        self._selected_path: str | None = None
        self._init_ui()
        self._apply_theme()
        self._refresh_list()

    def _apply_theme(self) -> None:
        """Scope the generated QSS to the chrome container only (design D4)."""
        if self._theme is not None:
            # W2a: the role property replaces the objectName style hook.
            attach_theme(self.chrome, self._theme)
            # The toggle label follows the runtime, whoever changed the theme
            # (this dialog, the main window menu, …).
            self._theme.add_listener(self._sync_theme_toggle_text)
            self._theme.apply()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        # The chrome has to reach the dialog edges: the default layout margin
        # (~11 px) would draw the OS palette as a frame around it (design D4).
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # W1 chrome container, W2a role chrome: the only widget in this dialog
        # whose subtree the compiled QSS is set on. The objectName is a test
        # identifier now, not a style hook.
        self.chrome = QWidget()
        self.chrome.setObjectName("themeChrome")
        layout.addWidget(self.chrome)
        chrome_layout = QVBoxLayout(self.chrome)
        chrome_layout.setContentsMargins(8, 8, 8, 8)
        chrome_layout.setSpacing(8)

        # W1 remnants (bold-16 inline sheet) → catalog title-xl: same 16px bold
        # from the tokens, margin-bottom replaced by the layout spacing (8px).
        chrome_layout.addWidget(title("Выберите игру или создайте новую", size="xl"))

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_open)
        chrome_layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        self.open_button = QPushButton("Открыть")
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self._on_open)

        self.new_button = QPushButton("Новая игра")
        self.new_button.clicked.connect(self._on_new)

        self.delete_button = QPushButton("Удалить")
        self.delete_button.clicked.connect(self._on_delete)

        self.import_button = QPushButton("Импорт")
        self.import_button.clicked.connect(self._on_import)

        btn_row.addWidget(self.new_button)
        btn_row.addWidget(self.import_button)

        # Theme toggle on the chrome (design D5): with invalid tokens the
        # runtime's toggle is a no-op, so QSS never appears (D7).
        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setVisible(self._theme is not None)
        self._sync_theme_toggle_text()
        self.theme_toggle_button.clicked.connect(self._on_theme_toggle)
        btn_row.addWidget(self.theme_toggle_button)

        btn_row.addStretch()
        btn_row.addWidget(self.delete_button)
        btn_row.addWidget(self.open_button)
        chrome_layout.addLayout(btn_row)

    def _sync_theme_toggle_text(self) -> None:
        """Label offers the theme you would switch *to*; the runtime notifies us."""
        light = self._theme is not None and self._theme.theme == "light"
        self.theme_toggle_button.setText("Тёмная тема" if light else "Светлая тема")

    def _on_theme_toggle(self) -> None:
        if self._theme is not None:
            self._theme.toggle()  # no-op with invalid tokens (D7)

    def _refresh_list(self) -> None:
        self.list_widget.clear()
        for game in list_games():
            text = f"{game['name']}    ({game['modified'].strftime('%Y-%m-%d %H:%M')})"
            item = QListWidgetItem(text)
            item.setData(256, game["path"])
            self.list_widget.addItem(item)

    def _on_open(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._selected_path = item.data(256)
        self.game_selected.emit(self._selected_path)
        self.accept()

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "Новая игра", "Название игры:")
        if not ok or not name.strip():
            return
        try:
            path = create_game(name.strip())
        except FileExistsError:
            QMessageBox.warning(self, "Ошибка", f"Игра '{name.strip()}' уже существует.")
            return
        self._refresh_list()
        # Select and open the newly created game
        self._selected_path = str(path)
        self.game_selected.emit(self._selected_path)
        self.accept()

    def _on_delete(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        path = item.data(256)
        name = item.text().split("    (")[0]
        reply = QMessageBox.question(
            self,
            "Удаление игры",
            f'Удалить игру "{name}"?\nЭто действие необратимо.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_game(path)
            self._refresh_list()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт игры", "",
            "NRI архив (*.nri);;Все файлы (*)",
        )
        if not path:
            return
        try:
            meta = read_archive_meta(path)
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
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            import_game(path)
            self._refresh_list()
            QMessageBox.information(
                self, "Импорт", f"Игра «{game_name}» успешно импортирована.",
            )
        except FileExistsError:
            QMessageBox.warning(self, "Ошибка", "Игра с таким именем уже существует.")
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    @property
    def selected_path(self) -> str | None:
        return self._selected_path
