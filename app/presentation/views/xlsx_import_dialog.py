"""Dialog for importing entities from .xlsx — QML island (R3 pack 1)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
)

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island, release_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.xlsx_import_view_model import XlsxImportViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "XlsxImportRoot.qml")

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


class _PathEdit:
    def __init__(self, vm: XlsxImportViewModel) -> None:
        self._vm = vm

    def text(self) -> str:
        return self._vm.path

    def setText(self, value: str) -> None:  # noqa: N802
        self._vm.path = value


class _ProgressBar:
    def __init__(self, vm: XlsxImportViewModel) -> None:
        self._vm = vm

    def value(self) -> int:
        return self._vm.progress


class _ImportButton:
    def __init__(self, dialog: "XlsxImportDialog") -> None:
        self._dialog = dialog

    def click(self) -> None:
        self._dialog._on_import_clicked()

    def isEnabled(self) -> bool:  # noqa: N802
        return self._dialog.vm.importEnabled

    def text(self) -> str:
        return "Проверить и импортировать"


class _FormatText:
    def __init__(self, vm: XlsxImportViewModel) -> None:
        self._vm = vm

    def toPlainText(self) -> str:  # noqa: N802
        return self._vm.formatText

    def isReadOnly(self) -> bool:  # noqa: N802
        return True


class XlsxImportDialog(QDialog):
    import_requested = Signal(str)

    def __init__(self, entity_type: str, parent=None, theme=None):
        super().__init__(parent)
        self._entity_type = entity_type
        self._theme = theme if theme is not None else get_default_theme()
        self._path: str = ""
        self.setWindowTitle(f"Импорт {ENTITY_LABELS.get(entity_type, entity_type)} из .xlsx")
        self.setMinimumSize(580, 480)

        self.vm = XlsxImportViewModel(FORMAT_TEXTS.get(entity_type, ""), parent=self)
        self.path_edit = _PathEdit(self.vm)
        self.progress_bar = _ProgressBar(self.vm)
        self.import_btn = _ImportButton(self)
        self.format_text = _FormatText(self.vm)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._theme, parent=self)
        # Dialog-owned context (never the shared engine root): a name written
        # there is nulled for every other island when this dialog dies.
        self._context = island_context(
            engine, self, xlsxImportVm=self.vm, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
        self._component = load_island(self.quick, self._context, ROOT_QML)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)
        self._root = self.quick.rootObject()
        self.vm.browseRequested.connect(self._on_browse)
        self.vm.importRequested.connect(self._on_import_from_vm)
        self._root.cancelRequested.connect(self.reject)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            marker = self._root.property("defaultButton") if self._root is not None else None
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return
        super().keyPressEvent(event)

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл",
            "",
            "Excel (*.xlsx *.xls);;Все файлы (*)",
        )
        if path:
            self.vm.path = path
            self._path = path

    def _on_import_from_vm(self, path: str) -> None:
        self._on_import_clicked()

    def _on_import_clicked(self) -> None:
        self._path = self.vm.path.strip()
        if not self._path:
            QMessageBox.warning(self, "Ошибка", "Выберите файл.")
            return
        self.vm.begin_import()
        self.import_requested.emit(self._path)

    def get_path(self) -> str:
        return self._path or self.vm.path.strip()

    def set_progress(self, current: int, total: int) -> None:
        self.vm.set_progress(current, total)
        QApplication.processEvents()

    def entity_type(self) -> str:
        return self._entity_type

    def _release_island(self) -> None:
        release_island(self.quick)

    def done(self, result: int) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)
