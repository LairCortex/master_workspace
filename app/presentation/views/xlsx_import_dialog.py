"""Dialog for the unified five-sheet .xlsx import — QML island (rework 4.2).

One entry point replaces the five per-type dialogs: no ``entity_type``
parameter, the file filter offers ``.xlsx`` only (openpyxl never read
``.xls``), and the state machine flows inside the island (VM task 4.1).
The column hint is generated from the schema registry (design D1) — the
single source shared with the parser and the template, so the hint can no
longer drift from what is actually read.

The «Скачать шаблон» button emits ``download_template`` (VM) and re-emits it
as a dialog signal; the save--as flow itself is :func:`save_template_as`
(task 5.2) — the wiring attaches it to that signal. Since piece C5 the
template is no longer a static bundle resource (design D8): after the user
confirms a name the workbook is assembled in memory under the game calendar
active at that moment and written out, so the download always speaks the
game's own calendar.
"""
from __future__ import annotations

import io
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
)

from app.application.services import xlsx_schema
from app.application.services.xlsx_template import build_template_workbook
from app.domain.game_calendar import (
    GameCalendar,
    IntercalaryDay,
    MonthDay,
    current_calendar,
)
from app.presentation.qml import setup_qml_shell
from app.presentation.qml.island import QML_IMPORT_PATH, IslandDialogMixin
from app.presentation.qml.island_size import fit_dialog_to_island
from app.presentation.theme import get_default_theme
from app.presentation.utils.date_utils import format_game_date
from app.presentation.viewmodels.xlsx_import_view_model import (
    STATE_DONE,
    STATE_PROBLEMS,
    XlsxImportViewModel,
)

ROOT_QML = str(Path(QML_IMPORT_PATH) / "XlsxImportRoot.qml")

#: Files the import reads (spec: .xls is out of the filter, honest .xlsx only).
XLSX_FILTER = "Файл Excel (*.xlsx)"

#: Default save--as name of the downloaded template (C5 design D8: the name
#: is unchanged from the static-resource era, the content is now generated).
TEMPLATE_FILE_NAME = "import_template.xlsx"


def save_template_as(parent) -> Path | None:
    """Handle «Скачать шаблон»: save--as dialog + generated template (D8).

    Cancelling the save dialog does nothing — and generates nothing (the
    import dialog stays as it was).  After the name is confirmed the workbook
    is built in memory under the calendar active at that moment and written
    to disk; a name without ``.xlsx`` gets the extension appended — the file
    is only ever a valid .xlsx.  A failed generation or write is reported to
    the user instead of failing silently. Returns the written path, or None
    when nothing was written.
    """
    target, _selected_filter = QFileDialog.getSaveFileName(
        parent, "Сохранить шаблон", TEMPLATE_FILE_NAME, XLSX_FILTER,
    )
    if not target:
        return None  # user cancelled — no generation work, nothing written
    dest = Path(target)
    if dest.suffix.lower() != ".xlsx":
        dest = dest.with_name(dest.name + ".xlsx")
    try:
        buffer = io.BytesIO()
        build_template_workbook(current_calendar()).save(buffer)
        dest.write_bytes(buffer.getvalue())
    except Exception as exc:  # disk failure or a broken generator — report, never crash the dialog
        QMessageBox.critical(
            parent, "Скачать шаблон", f"Не удалось сохранить шаблон: {exc}",
        )
        return None
    return dest

# Labels of the primary button per state (also mirrored by the island QML).
PRIMARY_TEXT_ANALYZE = "Проверить…"
PRIMARY_TEXT_IMPORT = "Импортировать"
PRIMARY_TEXT_CLOSE = "Закрыть"


# ── Calendar-aware «Даты» hint (piece C5, design D9) ──────────────────────

#: Year the custom-calendar examples carry — the same 44 the preset wording
#: already quotes, so both branches of the hint tell the same story.
_EXAMPLE_YEAR = 44

#: The preset «Даты» block, kept verbatim from before C5 — the preset answer
#: of the hint must stay word-for-word (spec «Подсказка о колонках в диалоге»).
_PRESET_DATE_HINT = (
    "Даты: нативная ячейка Excel или текст YYYY-MM-DD — это наша эра;",
    "до н.э. — текст «5 марта 44 г. до н.э.» или знаковое ISO -0044-03-05.",
)

#: Registry keys of the two date columns — their hint descriptions are the
#: only ones the dialog renders calendar-aware (the registry itself keeps the
#: static preset constant; header matching reads ``label``, not ``description``).
_DATE_COLUMN_KEYS = ("start_date", "end_date")


def _game_date_examples(calendar: GameCalendar) -> tuple[str, str | None]:
    """Game-wording examples for a custom calendar, both BC-captioned the way
    every game date in the app is (``format_game_date`` — D9).  The month
    example is a *valid* coordinate: the first month at day
    ``min(3, его длина)``.  The second item is the first declared intercalary
    rule's caption, or None when the calendar declares no intercalary day."""
    day = min(3, calendar.month_length(_EXAMPLE_YEAR, 1))
    month_example = format_game_date(MonthDay(_EXAMPLE_YEAR, 1, day), is_bc=True)
    if not calendar.spec.intercalary:
        return month_example, None
    return month_example, format_game_date(IntercalaryDay(_EXAMPLE_YEAR, 0), is_bc=True)


def date_formats_hint(calendar: GameCalendar) -> str:
    """The «Даты» block of the dialog hint for one calendar (task 5.1).

    The «Стандартный» preset answers with the two hint lines of before C5,
    word for word (continuity, spec «Подсказка о колонках в диалоге»).  A
    custom calendar keeps those lines and gains one naming the game wording
    the parser branch accepts, spelled with the calendar's own names — and its
    intercalary day when it declares one (both forms the C5 parser reads).
    """
    if getattr(calendar, "spec", None) is None:
        return "\n".join(_PRESET_DATE_HINT)
    month_example, intercalary_example = _game_date_examples(calendar)
    game = (
        "Календарь игры — игровая форма "
        f"«{month_example}»; без хвоста «г. до н.э.» — та же дата нашей эры"
    )
    if intercalary_example is not None:
        game += f"; вставной день — «{intercalary_example}»"
    return "\n".join((*_PRESET_DATE_HINT, game + "."))


def _date_column_description(column: xlsx_schema.ColumnSpec, calendar: GameCalendar) -> str:
    """Hint description of one column, calendar-aware for the two date ones.

    Under the preset every description is the registry constant as written.
    Under a custom calendar the «Дата начала» line additionally names the game
    wording with a valid example — the same form set that branch's parser
    accepts (spec «подпись колонки „Дата начала“ описывает тот же набор форм,
    что и парсер этой ветки»); «Дата конца» is phrased relatively, and
    «форматы те же, что у даты начала» stays true in either branch.
    """
    # LinkColumnSpec has no ``key`` at all — only scalar columns can be dates.
    if getattr(column, "key", None) not in _DATE_COLUMN_KEYS or getattr(calendar, "spec", None) is None:
        return column.description
    if column.key != "start_date":
        return column.description
    month_example, intercalary_example = _game_date_examples(calendar)
    game = f", игровая форма «{month_example}»"
    if intercalary_example is not None:
        game += f" (вставной день — «{intercalary_example}»)"
    return column.description + game


def build_format_text(calendar: GameCalendar | None = None) -> str:
    """Full column hint for all five sheets from the schema registry (D1).

    Continuity of the old per-type hint texts lives on: the descriptions in
    the registry carry exactly those wordings («Ссылка на музыкальную тему»,
    the image-format note); the date-column wording additionally names the
    BC forms accepted since add-era-aware-dates.  Since C5 the «Даты» block
    and the date-column descriptions are calendar-aware (D9): without an
    explicit argument the hint speaks for the calendar active right now.
    """
    active = current_calendar() if calendar is None else calendar
    lines = [
        "Один файл — все пять листов; импортируются только присутствующие",
        "знакомые листы (имена без учёта регистра). Заголовки ищутся по",
        "первой строке, порядок колонок произвольный, лишние колонки",
        "игнорируются; старые английские заголовки читаются как алиасы.",
        "",
        *date_formats_hint(active).splitlines(),
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
            description = _date_column_description(column, active)
            lines.append(
                f"  {column.label:<22} | {required} | {description}{alias}"
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


class XlsxImportDialog(IslandDialogMixin, QDialog):
    island_context_names = {"xlsxImportVm": "vm"}

    def island_source(self) -> str:
        return ROOT_QML
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

        self._engine = setup_qml_shell(QApplication.instance(), self._theme)
        # Dialog-owned context and scene — IslandDialogMixin.
        self.setup_island()
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

    # ── island lifecycle — IslandDialogMixin (context, deferred release) ──
