"""Dialog for importing entities from .xlsx with format description and progress bar."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

FORMAT_TEXTS: dict[str, str] = {
    "event": (
        "Первая строка файла — заголовки столбцов (порядок не важен).\n"
        "Столбцы ищутся по имени.\n\n"
        "Столбец            | Обяз. | Описание\n"
        "name               | да    | Название события\n"
        "start_date         | да    | Дата начала (YYYY-MM-DD или дата Excel)\n"
        "end_date           | нет   | Дата конца\n"
        "characteristics    | нет   | Описание / характеристики\n"
        "backstory          | нет   | Предыстория"
    ),
    "character": (
        "Первая строка файла — заголовки столбцов (порядок не важен).\n"
        "Столбцы ищутся по имени.\n\n"
        "Столбец            | Обяз. | Описание\n"
        "name               | да    | Имя персонажа\n"
        "start_date         | да    | Дата начала (YYYY-MM-DD или дата Excel)\n"
        "end_date           | нет   | Дата конца\n"
        "characteristics    | нет   | Описание / характеристики\n"
        "backstory          | нет   | Предыстория\n"
        "personality        | нет   | Личность\n"
        "tasks              | нет   | Задачи\n"
        "music_url          | нет   | Ссылка на музыкальную тему\n"
        "image              | нет   | Путь к изображению (относит. или абс.)\n"
        "\nДля image допустимы форматы: PNG, JPG, BMP, GIF, WebP.\n"
        "Альтернативное имя столбца: «изображение»."
    ),
    "location": (
        "Первая строка файла — заголовки столбцов (порядок не важен).\n"
        "Столбцы ищутся по имени.\n\n"
        "Столбец            | Обяз. | Описание\n"
        "name               | да    | Название локации\n"
        "start_date         | да    | Дата начала (YYYY-MM-DD или дата Excel)\n"
        "end_date           | нет   | Дата конца\n"
        "characteristics    | нет   | Описание / характеристики\n"
        "backstory          | нет   | Предыстория\n"
        "tasks              | нет   | Задачи\n"
        "music_url          | нет   | Ссылка на музыкальную тему\n"
        "image              | нет   | Путь к изображению (относит. или абс.)\n"
        "\nДля image допустимы форматы: PNG, JPG, BMP, GIF, WebP.\n"
        "Альтернативное имя столбца: «изображение»."
    ),
    "organization": (
        "Первая строка файла — заголовки столбцов (порядок не важен).\n"
        "Столбцы ищутся по имени.\n\n"
        "Столбец            | Обяз. | Описание\n"
        "name               | да    | Название организации\n"
        "start_date         | да    | Дата начала (YYYY-MM-DD или дата Excel)\n"
        "end_date           | нет   | Дата конца\n"
        "characteristics    | нет   | Описание / характеристики\n"
        "backstory          | нет   | Предыстория\n"
        "tasks              | нет   | Задачи\n"
        "music_url          | нет   | Ссылка на музыкальную тему\n"
        "image              | нет   | Путь к изображению (относит. или абс.)\n"
        "\nДля image допустимы форматы: PNG, JPG, BMP, GIF, WebP.\n"
        "Альтернативное имя столбца: «изображение»."
    ),
    "item": (
        "Первая строка файла — заголовки столбцов (порядок не важен).\n"
        "Столбцы ищутся по имени.\n\n"
        "Столбец            | Обяз. | Описание\n"
        "name               | да    | Название предмета\n"
        "start_date         | да    | Дата начала (YYYY-MM-DD или дата Excel)\n"
        "end_date           | нет   | Дата конца\n"
        "characteristics    | нет   | Описание / характеристики\n"
        "backstory          | нет   | Предыстория\n"
        "music_url          | нет   | Ссылка на музыкальную тему"
    ),
}

ENTITY_LABELS: dict[str, str] = {
    "event": "события",
    "character": "персонажи",
    "location": "локации",
    "organization": "организации",
    "item": "предметы",
}


class XlsxImportDialog(QDialog):
    """Dialog to select .xlsx file and run import with progress."""
    import_requested = Signal(str)  # path

    def __init__(self, entity_type: str, parent=None):
        super().__init__(parent)
        self._entity_type = entity_type
        self._path: str = ""
        self.setWindowTitle(f"Импорт {ENTITY_LABELS.get(entity_type, entity_type)} из .xlsx")
        self.setMinimumSize(580, 480)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        format_label = QLabel("Требования к файлу:")
        format_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(format_label)

        self.format_text = QTextEdit()
        self.format_text.setReadOnly(True)
        self.format_text.setMaximumHeight(260)
        self.format_text.setStyleSheet("QTextEdit { font-family: monospace; font-size: 12px; }")
        self.format_text.setPlainText(FORMAT_TEXTS.get(self._entity_type, ""))
        layout.addWidget(self.format_text)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Файл:"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Выберите .xlsx файл…")
        path_row.addWidget(self.path_edit, 1)
        browse_btn = QPushButton("Обзор…")
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.import_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_btn.setText("Проверить и импортировать")
        self.import_btn.clicked.connect(self._on_import_clicked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл",
            "",
            "Excel (*.xlsx *.xls);;Все файлы (*)",
        )
        if path:
            self.path_edit.setText(path)
            self._path = path

    def _on_import_clicked(self) -> None:
        self._path = self.path_edit.text().strip()
        if not self._path:
            QMessageBox.warning(self, "Ошибка", "Выберите файл.")
            return
        self.import_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.import_requested.emit(self._path)

    def get_path(self) -> str:
        return self._path or self.path_edit.text().strip()

    def set_progress(self, current: int, total: int) -> None:
        if total > 0:
            self.progress_bar.setValue(int(100 * current / total))
        else:
            self.progress_bar.setValue(0)
        QApplication.processEvents()

    def entity_type(self) -> str:
        return self._entity_type
