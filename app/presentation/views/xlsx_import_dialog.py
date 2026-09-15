"""Dialog for the unified five-sheet .xlsx import — QML island (rework 4.2).

One entry point replaces the five per-type dialogs: no ``entity_type``
parameter, the file filter offers ``.xlsx`` only (openpyxl never read
``.xls``), and the state machine flows inside the island (VM task 4.1).
The column hint is generated from the schema registry (design D1) — the
single source shared with the parser and the template, so the hint can no
longer drift from what is actually read.

The «Скачать шаблон» button emits ``download_template`` (VM) and re-emits it
as a dialog signal; the save--as flow itself is :func:`save_template_as`
(task 5.2) — the wiring attaches it to that signal. The template is a static
bundle resource (design D9): the bundled file is copied byte-for-byte, never
regenerated at runtime, so what the user downloads is exactly what the tests
validated.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import shiboken6
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

from app.application.services import xlsx_schema
from app.presentation.bundle_resources import bundle_resource_path
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island, release_island
from app.presentation.qml.island_size import fit_dialog_to_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.xlsx_import_view_model import (
    STATE_DONE,
    STATE_PROBLEMS,
    XlsxImportViewModel,
)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "XlsxImportRoot.qml")

#: Files the import reads (spec: .xls is out of the filter, honest .xlsx only).
XLSX_FILTER = "Файл Excel (*.xlsx)"

#: Bundled template resource (design D9): shipped by nri_manager.spec as
#: ``resources/import_template.xlsx`` — also the default save-as name.
TEMPLATE_DIR = "resources"
TEMPLATE_FILE_NAME = "import_template.xlsx"


def import_template_source() -> Path:
    """Path of the bundled template file (dev checkout or PyInstaller bundle).

    Same dev-vs-frozen resolver as the docs viewers (design D9), pointed at
    the ``resources/import_template.xlsx`` datas entry.
    """
    return bundle_resource_path(TEMPLATE_DIR, TEMPLATE_FILE_NAME)


def save_template_as(parent) -> Path | None:
    """Handle «Скачать шаблон»: save--as dialog + byte copy of the resource.

    Cancelling the save dialog does nothing (the import dialog stays as it
    was). A name without ``.xlsx`` gets the extension appended — the copy is
    only ever a valid .xlsx. A missing resource or a failed copy is reported
    to the user instead of failing silently. Returns the written path, or
    None when nothing was written.
    """
    source = import_template_source()
    if not source.is_file():
        QMessageBox.warning(
            parent, "Скачать шаблон",
            f"Файл шаблона не найден в установе: {source}",
        )
        return None
    target, _selected_filter = QFileDialog.getSaveFileName(
        parent, "Сохранить шаблон", TEMPLATE_FILE_NAME, XLSX_FILTER,
    )
    if not target:
        return None  # user cancelled — nothing is written
    dest = Path(target)
    if dest.suffix.lower() != ".xlsx":
        dest = dest.with_name(dest.name + ".xlsx")
    try:
        shutil.copyfile(source, dest)
    except OSError as exc:
        QMessageBox.critical(
            parent, "Скачать шаблон", f"Не удалось сохранить шаблон: {exc}",
        )
        return None
    return dest

# Labels of the primary button per state (also mirrored by the island QML).
PRIMARY_TEXT_ANALYZE = "Проверить…"
PRIMARY_TEXT_IMPORT = "Импортировать"
PRIMARY_TEXT_CLOSE = "Закрыть"


def build_format_text() -> str:
    """Full column hint for all five sheets from the schema registry (D1).

    Continuity of the old per-type hint texts lives on: the descriptions in
    the registry carry exactly those wordings («Ссылка на музыкальную тему»,
    the image-format note); the date-column wording additionally names the
    BC forms accepted since add-era-aware-dates.
    """
    lines = [
        "Один файл — все пять листов; импортируются только присутствующие",
        "знакомые листы (имена без учёта регистра). Заголовки ищутся по",
        "первой строке, порядок колонок произвольный, лишние колонки",
        "игнорируются; старые английские заголовки читаются как алиасы.",
        "",
        "Даты: нативная ячейка Excel или текст YYYY-MM-DD — это наша эра;",
        "до н.э. — текст «5 марта 44 г. до н.э.» или знаковое ISO -0044-03-05.",
        f"Связи в ячейке — имена через «{xlsx_schema.LINK_SEPARATOR}».",
        "Строки с проблемами пред-анализа пропускаются, остальные импортируются.",
    ]
    for sheet in xlsx_schema.all_sheets():
        lines.append("")
        lines.append(f"Лист «{sheet.sheet_name}»")
        for column in xlsx_schema.all_headers(sheet):
            if isinstance(column, xlsx_schema.LinkColumnSpec):
                alias = ""
            else:
                alias = (
                    " (алиасы: " + ", ".join(column.aliases) + ")"
                    if column.aliases else ""
                )
            required = "да " if getattr(column, "required", False) else "нет"
            lines.append(
                f"  {column.label:<22} | {required} | {column.description}{alias}"
            )
    image_note = (
        "Для колонок «Изображение» допустимы форматы: PNG, JPG, BMP, GIF, WebP."
    )
    lines += ["", image_note]
    return "\n".join(lines)


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

    def isVisible(self) -> bool:  # noqa: N802
        return self._vm.progressVisible


class _ImportButton:
    """Mirror of the island's primary button contract."""

    def __init__(self, dialog: "XlsxImportDialog") -> None:
        self._dialog = dialog

    def click(self) -> None:
        self._dialog._on_primary_clicked()

    def isEnabled(self) -> bool:  # noqa: N802
        return self._dialog.vm.canImport or self._dialog.vm.state == STATE_DONE

    def text(self) -> str:
        state = self._dialog.vm.state
        if state == STATE_DONE:
            return PRIMARY_TEXT_CLOSE
        if state == STATE_PROBLEMS:
            return PRIMARY_TEXT_IMPORT
        return PRIMARY_TEXT_ANALYZE


class _FormatText:
    def __init__(self, vm: XlsxImportViewModel) -> None:
        self._vm = vm

    def toPlainText(self) -> str:  # noqa: N802
        return self._vm.formatText

    def isReadOnly(self) -> bool:  # noqa: N802
        return True


class XlsxImportDialog(QDialog):
    analyze_requested = Signal(str)
    confirm_import = Signal()
    download_template = Signal()

    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self._theme = theme if theme is not None else get_default_theme()
        self._plan = None
        self.setWindowTitle("Импорт из .xlsx")
        self.setMinimumSize(620, 520)

        self.vm = XlsxImportViewModel(build_format_text(), parent=self)
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
        fit_dialog_to_island(self, self._root, floor=(620, 520))
        self.vm.browseRequested.connect(self._on_browse)
        self.vm.analyze_requested.connect(self.analyze_requested.emit)
        self.vm.confirm_import.connect(self.confirm_import.emit)
        self.vm.download_template.connect(self.download_template.emit)
        self._root.cancelRequested.connect(self.reject)

    # ── plan ownership (design D2: the analyzed plan is applied as is) ─────

    def set_plan(self, plan) -> None:
        self._plan = plan

    @property
    def plan(self):
        return self._plan

    # ── result delivery from the wiring's deferred tasks ──────────────────
    # The wiring runs analyze/confirm as detached tasks; the user can close
    # the dialog while one of them is still awaiting («finished →
    # deleteLater» destroys the C++ side together with the child VM). The
    # deferred callback then meets a deleted C++ object — the very failure
    # mode the island release guards against in app/presentation/qml/
    # engine.py (a RuntimeError inside the Qt loop, charged to whatever runs
    # next). The import itself is session-locked and unaffected, so every
    # post-await touch of the dialog checks liveness first: the report of an
    # invisible dialog is simply dropped.

    def publish_analysis(self, plan) -> None:
        """Adopt the analyzed plan and move the state machine to problems."""
        if not shiboken6.isValid(self):
            return
        self._plan = plan
        self.vm.on_analyzed(plan)

    def publish_analysis_failure(self, message: str) -> None:
        if not shiboken6.isValid(self):
            return
        self.vm.on_analyze_failed(message)

    def publish_report(self, report) -> None:
        if not shiboken6.isValid(self):
            return
        self.vm.on_report(report)

    def publish_import_failure(self, message: str) -> None:
        if not shiboken6.isValid(self):
            return
        self.vm.on_import_failed(message)

    # ── island/keyboard contract ────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            marker = self._root.property("defaultButton") if self._root is not None else None
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return
        super().keyPressEvent(event)

    def _on_primary_clicked(self) -> None:
        """Python mirror of the island button's onClicked branch."""
        state = self.vm.state
        if state == STATE_DONE:
            self.reject()
        elif state == STATE_PROBLEMS:
            self.vm.requestConfirmImport()
        else:
            self.vm.requestAnalyze()

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл",
            "",
            XLSX_FILTER,
        )
        if path:
            self.vm.path = path

    def get_path(self) -> str:
        return self.vm.path.strip()

    def set_progress(self, current: int, total: int) -> None:
        # Deferred task callback: after deleteLater the island is gone, but
        # the apply pass may still be ticking — dropping the tick must not
        # touch the deleted child VM (see publish_* above).
        if not shiboken6.isValid(self):
            return
        self.vm.set_progress(current, total)
        QApplication.processEvents()

    # ── island lifecycle ───────────────────────────────────────────────────

    def _release_island(self) -> None:
        release_island(self.quick)

    def done(self, result: int) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)
