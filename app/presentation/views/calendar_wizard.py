"""The calendar wizard modal (roadmap piece C4, task group 6, designs D5/D6).

A thin widgets view over :class:`~app.presentation.viewmodels.calendar_wizard_viewmodel.CalendarWizardViewModel`:
it renders the frozen :class:`~app.presentation.viewmodels.calendar_wizard_viewmodel.CalendarWizardState`
snapshots it is handed and forwards clicks/edits as intents — all flow,
validation, draft and apply rules live in the view model (the repo's review
rule: no business logic in the view).  A ``QStackedWidget`` carries the screens
«выбор → неделя → месяцы → вставные дни → предпросмотр» plus the «отчёт»
screen reached through «Применить», and the right-hand panel is the live
preview: the very :class:`~app.presentation.views.calendar_grid.GameCalendarGrid`
the date popups use, in its inert look (``interactive=False``,
``show_era=False``) — no clickable cells, no era switch, month/year navigation
alive (spec «Живой предпросмотр сеткой»).

The preview opens on the CURRENT game date: «today» projected into game
coordinates through ``as_game_coord`` (the same «сегодня, н.э.» reading the
world-snapshot view model uses, the app stores no other now); when the
assembled calendar does not contain that coordinate (its month count or month
lengths refuse it) the grid simply stays on year 1 — the spec's «текущая
игровая дата, иначе год 1», with the grid's own un-prefill semantics doing the
fallback (no page jump, no crash).  After that opening placement the preview
only repaints pages on valid form edits, so the user's own month/year
navigation is never yanked back.

Skinning (task 6.4) is the widget catalog's, not bespoke QSS: the dialog root
is attached through ``attach_theme`` (becoming a ``[uiRole="chrome"]``
container whose push buttons, spin boxes and combo popups the generated sheet
skins), labels come from the catalog's ``title``/``hint`` factories, every
input carries the ``field`` role, the report table the ``list`` role and the
problems readout ``status-error``.  The only style-FACING class names the
wizard itself puts on screen are the grid's quartet — ``GameCalendarGrid``,
``GameCalendarCell``, ``GameCalendarIntercalaryChip`` and
``GameCalendarDayName`` — skinned by the application-wide popup sheet
(``compile_popup_qss``, design D4); they are owned by
:mod:`app.presentation.views.calendar_grid` and rename only together with that
sheet.  Invalid tokens (theme off) leave everything on the OS palette while the
flow stays alive (design D7).

Async convention copies the :class:`~app.presentation.views.event_types_dialog.EventTypesDialog`
facade: coroutines are fired through an injected ``run`` (``ensure_future`` by
default, so tests drive a bare loop) and :meth:`wait_idle` is the await seam.
Group 7 owns the entry points (menu item, first-entry modal) and constructs
the view model; this dialog loads the draft when told to (:meth:`begin`) and
closes itself on a successful application (``accept``), so the ``exec()``
caller learns the outcome from the dialog result.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.game_calendar import (
    MIN_YEAR,
    as_game_coord,
    current_calendar,
    set_current_calendar,
)
from app.presentation.theme import get_default_theme
from app.presentation.theme.catalog import attach_theme, hint, set_role, title
from app.presentation.viewmodels.calendar_wizard_viewmodel import (
    KIND_CUSTOM,
    KIND_STANDARD,
    STEP_CHOICE,
    STEP_INTERCALARY,
    STEP_MONTHS,
    STEP_PREVIEW,
    STEP_REPORT,
    STEP_WEEK,
    CalendarWizardState,
    CalendarWizardViewModel,
)
from app.presentation.views.calendar_grid import GameCalendarGrid

# Spin bounds the screens offer.  The week's 2…168 is fixed by spec («Неделя
# короче двух»: длина 1 просто «недоступна»); the month bounds are NOT domain
# caps (the validator knows none — «нет продуктовых ограничений на размер») —
# a QSpinBox just needs one, and the product's own year scale (1…9999, the
# grid's) is the natural ceiling for a month length.
WEEK_LENGTH_MIN = 2
WEEK_LENGTH_MAX = 168
MONTH_LENGTH_MIN = 1
MONTH_LENGTH_MAX = 9999
MONTH_COUNT_MIN = 1
MONTH_COUNT_MAX = 99

#: Window title of the wizard.
WIZARD_TITLE = "Настройка календаря"
#: Title of the apply-failure window: the view model hands over the
#: displayable reason, the dialog only shows it (spec «Ошибки применения…»
#: leaves it open on the report/preview screen).
APPLY_ERROR_TITLE = "Применение календаря"


def _bind_spin(spin: QSpinBox, value: int) -> None:
    """``setValue`` without echoing the value-changed intent back into the
    view model; Qt's own range clamp keeps an out-of-range prefilled draft
    harmless."""
    spin.blockSignals(True)
    spin.setValue(value)
    spin.blockSignals(False)


def _set_text(edit: QLineEdit, value: str) -> None:
    """``setText`` only when it actually changes — rewriting the same text
    under the user's cursor would only move it to the end."""
    if edit.text() != value:
        edit.setText(value)


class CalendarWizardDialog(QDialog):
    """Widgets shell of the calendar wizard: state out, intents in.

    The view model arrives ready-made (group 7 builds it over the game's
    session, service and ``first_entry`` flag); the dialog shows, asks and
    closes.  ``theme`` injects a :class:`ThemeRuntime` (default: the process
    one), ``run`` the coroutine launcher.
    """

    def __init__(
        self,
        vm: CalendarWizardViewModel,
        parent: QWidget | None = None,
        theme=None,
        run: Callable | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._theme = theme if theme is not None else get_default_theme()
        self._run = run if run is not None else asyncio.ensure_future
        self._task: asyncio.Future | None = None
        # The calendar currently painted into the preview panel; repaints are
        # skipped while the preview calendar object has not changed.
        self._preview_shown: object | None = None

        self.setWindowTitle(WIZARD_TITLE)
        self.setMinimumSize(860, 620)

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, 3)
        root.addLayout(right, 2)

        self._stack = QStackedWidget()
        self._pages = {
            STEP_CHOICE: self._build_choice_page(),
            STEP_WEEK: self._build_week_page(),
            STEP_MONTHS: self._build_months_page(),
            STEP_INTERCALARY: self._build_intercalary_page(),
            STEP_PREVIEW: self._build_preview_page(),
            STEP_REPORT: self._build_report_page(),
        }
        for page in self._pages.values():
            self._stack.addWidget(page)
        left.addWidget(self._stack, 1)

        # Why «Далее» is disabled, in Russian (the spec scenarios quote the
        # dictionary phrase verbatim — this label is where it appears).
        self._problems_label = QLabel("")
        self._problems_label.setWordWrap(True)
        set_role(self._problems_label, "status-error")
        left.addWidget(self._problems_label)

        self._footer = QWidget()
        footer_row = QHBoxLayout(self._footer)
        footer_row.setContentsMargins(0, 0, 0, 0)
        self._back_button = QPushButton("Назад")
        self._next_button = QPushButton("Далее")
        self._apply_button = QPushButton("Применить")
        self._cancel_button = QPushButton("Отменить")
        footer_row.addWidget(self._back_button)
        footer_row.addWidget(self._next_button)
        footer_row.addWidget(self._apply_button)
        footer_row.addStretch()
        footer_row.addWidget(self._cancel_button)
        left.addWidget(self._footer)

        right.addWidget(title("Предпросмотр"))
        # The live preview: the same grid class the date popups embed, inert
        # (STYLE-FACING class names skinned by the popup sheet — see module).
        self._preview = GameCalendarGrid(interactive=False, show_era=False)
        right.addWidget(self._preview, 1)

        # Catalog skin: chrome root for the generated sheet's button/field
        # rules, roles stamped on the individual widgets above.
        attach_theme(self, self._theme)

        self._back_button.clicked.connect(self._vm.go_back)
        self._next_button.clicked.connect(lambda: self._start(self._vm.try_advance()))
        self._apply_button.clicked.connect(lambda: self._start(self._vm.apply()))
        self._cancel_button.clicked.connect(self._on_cancel)
        self._transfer_apply_button.clicked.connect(
            lambda: self._start(self._vm.confirm_transfer())
        )
        self._transfer_cancel_button.clicked.connect(self._vm.cancel_report)
        self._standard_radio.clicked.connect(lambda: self._vm.choose_kind(KIND_STANDARD))
        self._custom_radio.clicked.connect(lambda: self._vm.choose_kind(KIND_CUSTOM))
        self._week_length_spin.valueChanged.connect(self._vm.set_week_length)
        self._month_count_spin.valueChanged.connect(self._vm.set_month_count)
        self._rule_add_button.clicked.connect(self._on_add_rule)

        self._vm.state_changed.connect(self._render)
        self._vm.apply_succeeded.connect(self.accept)
        self._vm.apply_failed.connect(self._show_apply_error)

        self._render()
        # Spec «отображаемая дата — текущая игровая дата, иначе год 1»: ONE
        # placement per opened preview state — later repaints keep whatever
        # page the user navigated to («навигация по месяцам и годам работает»).
        self._place_preview()

    # ── async seams (the EventTypesDialog facade convention) ────────────────

    async def begin(self) -> None:
        """Read the stored draft: continue position + prefill (spec
        «Черновик мастера» — the view model owns the semantics).

        A resumed draft repoints the preview at the draft's own assembled
        calendar, so the opening placement of «current game date, else year 1»
        is re-evaluated against it here.
        """
        await self._vm.begin()
        self._place_preview()

    def _start(self, coro) -> None:
        self._task = self._run(coro)

    async def wait_idle(self) -> None:
        """Await the in-flight intent — the seam that makes a fire-and-read
        button click observable for tests (and the app's loop)."""
        while self._task is not None:
            task, self._task = self._task, None
            await task

    # ── screens (built once; state re-syncs their widgets) ──────────────────

    def _build_choice_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(title("Стандартный или свой календарь?"))
        layout.addWidget(
            hint(
                "Стандартный — привычные 12 григорианских месяцев. Кастомный — "
                "своё число месяцев, их имена и длины, своя неделя и вставные дни."
            )
        )
        self._standard_radio = QRadioButton("Стандартный")
        self._custom_radio = QRadioButton("Кастомный")
        layout.addWidget(self._standard_radio)
        layout.addWidget(self._custom_radio)
        layout.addStretch()
        return page

    def _build_week_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(title("Неделя"))
        # Fields are one per week day, so the length spin is what adds the
        # empty tail / drops the tail names (spec «Экран „Неделя“»).
        self._week_length_spin = self._spin_row(layout, "Длина недели:")
        self._week_length_spin.setRange(WEEK_LENGTH_MIN, WEEK_LENGTH_MAX)
        self._week_box = _row_box()
        layout.addWidget(_wrap_scroll(self._week_box), 1)
        self._week_fields: list[QLineEdit] = []
        return page

    def _build_months_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(title("Месяцы"))
        # Rows «имя | длина» live in a scroll area (spec «строки „имя | длина“
        # со скроллом»).
        self._month_count_spin = self._spin_row(layout, "Число месяцев:")
        self._month_count_spin.setRange(MONTH_COUNT_MIN, MONTH_COUNT_MAX)
        self._months_box = _row_box()
        layout.addWidget(_wrap_scroll(self._months_box), 1)
        self._month_rows: list[tuple[QLineEdit, QSpinBox]] = []
        return page

    def _build_intercalary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(title("Вставные дни"))
        layout.addWidget(
            hint(
                "Порядок списка значим: правила одного месяца-хозяина занимают "
                "его последовательные позиции."
            )
        )
        self._rules_box = _row_box()
        layout.addWidget(_wrap_scroll(self._rules_box), 1)
        self._rule_rows: list[tuple[QLabel, QPushButton, QPushButton, QPushButton]] = []
        add_row = QHBoxLayout()
        self._rule_name_edit = QLineEdit()
        self._rule_name_edit.setPlaceholderText("Название вставного дня")
        set_role(self._rule_name_edit, "field")
        self._rule_month_combo = QComboBox()
        set_role(self._rule_month_combo, "field")
        self._rule_add_button = QPushButton("Добавить")
        add_row.addWidget(self._rule_name_edit, 1)
        add_row.addWidget(self._rule_month_combo)
        add_row.addWidget(self._rule_add_button)
        layout.addLayout(add_row)
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(title("Предпросмотр"))
        # «сводка (число месяцев, длина недели, число вставных дней)» — the
        # grid itself lives in the right-hand panel next to every screen.
        self._summary_label = hint("")
        layout.addWidget(self._summary_label)
        layout.addWidget(hint("Слева — сводка, справа — сетка будущего календаря. «Применить» — внизу."))
        layout.addStretch()
        return page

    def _build_report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(title("Перенос дат"))
        self._report_hint = hint("")
        layout.addWidget(self._report_hint)
        self._report_table = QTableWidget(0, 4)
        self._report_table.setHorizontalHeaderLabels(["Запись", "Поле", "Было", "Станет"])
        self._report_table.verticalHeader().setVisible(False)
        self._report_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._report_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._report_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        set_role(self._report_table, "list")
        layout.addWidget(self._report_table, 1)
        # The report's own pair (spec «Предпросмотр и применение»): «Перенести
        # и применить» / «Отменить» — the latter RETURNS to the previous
        # screen, it does not close the wizard (the footer's «Отменить» does).
        buttons = QHBoxLayout()
        self._transfer_apply_button = QPushButton("Перенести и применить")
        self._transfer_cancel_button = QPushButton("Отменить")
        buttons.addStretch()
        buttons.addWidget(self._transfer_cancel_button)
        buttons.addWidget(self._transfer_apply_button)
        layout.addLayout(buttons)
        return page

    def _spin_row(self, layout: QVBoxLayout, caption: str) -> QSpinBox:
        """«caption + spin + stretch» row; returns the catalog-field spin."""
        row = QHBoxLayout()
        row.addWidget(hint(caption))
        spin = QSpinBox()
        set_role(spin, "field")
        row.addWidget(spin)
        row.addStretch()
        layout.addLayout(row)
        return spin

    # ── rendering (state → widgets, nothing else) ────────────────────────────

    def _render(self) -> None:
        self._render_state(self._vm.state)

    def _render_state(self, state: CalendarWizardState) -> None:
        self._stack.setCurrentWidget(self._pages[state.step])

        self._standard_radio.blockSignals(True)
        self._custom_radio.blockSignals(True)
        self._standard_radio.setChecked(state.kind == KIND_STANDARD)
        self._custom_radio.setChecked(state.kind == KIND_CUSTOM)
        self._standard_radio.blockSignals(False)
        self._custom_radio.blockSignals(False)

        self._back_button.setEnabled(state.can_go_back)
        self._next_button.setEnabled(state.can_advance)
        self._apply_button.setEnabled(state.can_apply)
        # The footer (Назад/Далее/Применить/Отменить) belongs to the build
        # flow; the report screen carries its own pair instead.
        self._footer.setVisible(state.step != STEP_REPORT)

        self._problems_label.setText(
            "\n".join(state.problem_phrases)
            if state.problems and state.step != STEP_REPORT
            else ""
        )

        _bind_spin(self._week_length_spin, len(state.week_names))
        self._sync_week_fields(state)
        _bind_spin(self._month_count_spin, len(state.months))
        self._sync_month_rows(state)
        self._sync_rule_rows(state)

        self._summary_label.setText(
            f"Месяцев: {len(state.months)} · "
            f"Длина недели: {len(state.week_names)} · "
            f"Вставных дней: {len(state.intercalary)}"
        )
        self._render_report(state)
        self._paint_preview(state.preview_calendar)

    def _render_report(self, state: CalendarWizardState) -> None:
        self._report_hint.setText(
            f"Новый календарь сдвигает дату в {len(state.report_lines)} полях записей:"
            if state.report is not None
            else ""
        )
        self._report_table.setRowCount(len(state.report_lines))
        for row, line in enumerate(state.report_lines):
            for column, text in enumerate(
                (line.record, line.field, line.old_date, line.new_date)
            ):
                self._report_table.setItem(row, column, QTableWidgetItem(text))

    def _sync_week_fields(self, state: CalendarWizardState) -> None:
        box_layout = self._week_box.layout()
        while len(self._week_fields) < len(state.week_names):
            index = len(self._week_fields)
            edit = QLineEdit()
            set_role(edit, "field")
            edit.textChanged.connect(
                lambda text, i=index: self._vm.set_week_name(i, text)
            )
            box_layout.insertWidget(box_layout.count() - 1, edit)
            self._week_fields.append(edit)
        while len(self._week_fields) > len(state.week_names):
            edit = self._week_fields.pop()
            box_layout.removeWidget(edit)
            edit.deleteLater()
        for index, name in enumerate(state.week_names):
            _set_text(self._week_fields[index], name)

    def _sync_month_rows(self, state: CalendarWizardState) -> None:
        box_layout = self._months_box.layout()
        while len(self._month_rows) < len(state.months):
            index = len(self._month_rows)
            holder = QWidget()
            row_layout = QHBoxLayout(holder)
            row_layout.setContentsMargins(0, 0, 0, 0)
            name_edit = QLineEdit()
            set_role(name_edit, "field")
            name_edit.textChanged.connect(
                lambda text, i=index: self._vm.set_month_name(i, text)
            )
            length_spin = QSpinBox()
            length_spin.setRange(MONTH_LENGTH_MIN, MONTH_LENGTH_MAX)
            set_role(length_spin, "field")
            length_spin.valueChanged.connect(
                lambda length, i=index: self._vm.set_month_length(i, length)
            )
            row_layout.addWidget(name_edit, 1)
            row_layout.addWidget(length_spin)
            box_layout.insertWidget(box_layout.count() - 1, holder)
            self._month_rows.append((name_edit, length_spin))
        while len(self._month_rows) > len(state.months):
            name_edit, _spin = self._month_rows.pop()
            holder = name_edit.parentWidget()
            box_layout.removeWidget(holder)
            holder.deleteLater()
        for index, month in enumerate(state.months):
            _set_text(self._month_rows[index][0], month.name)
            _bind_spin(self._month_rows[index][1], month.length)

    def _sync_rule_rows(self, state: CalendarWizardState) -> None:
        box_layout = self._rules_box.layout()
        while len(self._rule_rows) < len(state.intercalary):
            index = len(self._rule_rows)
            holder = QWidget()
            row_layout = QHBoxLayout(holder)
            row_layout.setContentsMargins(0, 0, 0, 0)
            caption = QLabel("")
            set_role(caption, "hint")
            remove_button = QPushButton("Удалить")
            up_button = QPushButton("↑")
            down_button = QPushButton("↓")
            remove_button.clicked.connect(
                lambda _c=False, i=index: self._vm.remove_intercalary(i)
            )
            up_button.clicked.connect(
                lambda _c=False, i=index: self._vm.move_rule(i, -1)
            )
            down_button.clicked.connect(
                lambda _c=False, i=index: self._vm.move_rule(i, 1)
            )
            row_layout.addWidget(caption, 1)
            row_layout.addWidget(remove_button)
            row_layout.addWidget(up_button)
            row_layout.addWidget(down_button)
            box_layout.insertWidget(box_layout.count() - 1, holder)
            self._rule_rows.append((caption, remove_button, up_button, down_button))
        while len(self._rule_rows) > len(state.intercalary):
            caption, _removed, _up, _down = self._rule_rows.pop()
            holder = caption.parentWidget()
            box_layout.removeWidget(holder)
            holder.deleteLater()
        month_names = {number: month.name for number, month in enumerate(state.months, 1)}
        for index, rule in enumerate(state.intercalary):
            # A rule whose host month the user trimmed away stays listed,
            # captioned by number — «чужие правила молча НЕ удаляются», the
            # user resolves them right here (spec «Экран „Месяцы“»).
            host = month_names.get(rule.after_month, f"месяц №{rule.after_month}")
            self._rule_rows[index][0].setText(f"{rule.name or '«без названия»'} → {host}")

        # The combo is reseeded from the live month list every render.  Its
        # preselection is the LAST month (spec «предвыбором последнего
        # месяца»); a month the user already picked (the preselection on the
        # very first fill) is restored by its host number, and a host whose
        # month was trimmed away falls back to the last entry.
        previous_host = self._rule_month_combo.currentData()
        self._rule_month_combo.blockSignals(True)
        self._rule_month_combo.clear()
        for number, month in enumerate(state.months, 1):
            self._rule_month_combo.addItem(month.name, number)
        if self._rule_month_combo.count():
            index = self._rule_month_combo.findData(previous_host)
            if index < 0:
                index = self._rule_month_combo.count() - 1
            self._rule_month_combo.setCurrentIndex(index)
        self._rule_month_combo.blockSignals(False)

    def _paint_preview(self, calendar) -> None:
        """Paint the view model's ``calendar`` (the last-valid form assembly)
        into the live preview grid.

        The grid paints the ACTIVE calendar by its own spec («Сетка показывает
        активный календарь»), while the wizard must preview the assembled,
        not-yet-applied one — so the global is swapped to the preview only
        around the synchronous ``refresh()`` and restored straight away.
        Nothing between the two calls reads the global: ``refresh()`` neither
        navigates nor emits (its nav signals are blocked), and afterwards the
        grid keeps painting its stored calendar even though the process-global
        is back to the game's — the running game is never observably moved.
        """
        if calendar is self._preview_shown:
            return
        self._preview_shown = calendar
        saved = current_calendar()
        set_current_calendar(calendar)
        try:
            self._preview.refresh()
        finally:
            set_current_calendar(saved)

    def _place_preview(self) -> None:
        """Put the preview on the CURRENT game date — «today» projected into
        game coordinates through ``as_game_coord`` (the app stores no other
        now; the world-snapshot view model reads «сегодня» the same way).
        When the assembled preview calendar has no such day (its months or
        lengths refuse it), the grid keeps no selection and the panel lands
        on year 1 instead — the spec's «текущая игровая дата, иначе год 1».
        """
        coord = as_game_coord(date.today())
        self._preview.set_selection(coord)
        if self._preview.selection() is None:
            self._preview.set_page(MIN_YEAR, 1)

    # ── widget-side intent handlers ──────────────────────────────────────────

    def _on_add_rule(self) -> None:
        # The host is the combo's selected month; with the list empty (or no
        # month selected) the data is ``None`` and the view model hosts the
        # rule on its own last month (spec «предвыбором последнего месяца»).
        self._vm.add_intercalary(self._rule_name_edit.text(), self._rule_month_combo.currentData())
        _set_text(self._rule_name_edit, "")

    def _on_cancel(self) -> None:
        """Footer «Отменить»: the view model keeps the draft by contract (spec
        «Черновик мастера»), the dialog simply closes."""
        self._vm.cancel()
        self.reject()

    def _show_apply_error(self, reason: str) -> None:
        """Spec «Ошибки применения… окно с причиной»: reason verbatim from the
        view model (it is already a displayable string), wizard stays open."""
        QMessageBox.warning(self, APPLY_ERROR_TITLE, reason)


def _row_box() -> QWidget:
    """Growing container for a dynamically filled row list; the trailing
    stretch keeps rows top-aligned as they are added before it."""
    box = QWidget()
    box_layout = QVBoxLayout(box)
    box_layout.setContentsMargins(0, 0, 0, 0)
    box_layout.addStretch()
    return box


def _wrap_scroll(box: QWidget) -> QScrollArea:
    """Scroll area around a row box (weeks/months/rules lists are scrollable —
    spec «строки „имя | длина“ со скроллом»)."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(box)
    return scroll
