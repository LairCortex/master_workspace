"""The calendar wizard sheet (roadmap piece C4, task group 6; sheet format
since nri-0024 task 3.1, design Д6).

A thin widgets view over :class:`~app.presentation.viewmodels.calendar_wizard_viewmodel.CalendarWizardViewModel`:
it renders the frozen :class:`~app.presentation.viewmodels.calendar_wizard_viewmodel.CalendarWizardState`
snapshots it is handed and forwards clicks/edits as intents — all flow,
validation, draft and apply rules live in the view model (the repo's review
rule: no business logic in the view).  A step stack (a
:class:`~PySide6.QtWidgets.QStackedLayout` on a plain widget — see
:class:`_StepStack`, which is what keeps a short step as short as its own
content) carries the screens
«выбор → неделя → месяцы → вставные дни → сутки → предпросмотр» plus the «отчёт»
screen reached through «Применить», and the right-hand panel is the live
preview: the very :class:`~app.presentation.views.calendar_grid.GameCalendarGrid`
the date popups use, in its inert look (``interactive=False``,
``show_era=False``) — no clickable cells, no era switch, month/year navigation
alive (spec «Живой предпросмотр сеткой»).

The container (task 3.1): a :class:`~app.presentation.views.sheet_frame.SheetFrame`
sheet — header «Настройка календаря» + «Закрыть» (one cancel path with Esc),
shown by ``ApplicationWiring.open_sheet`` as an attached native sheet over
the main window (Qt.Sheet, NonModal at Qt level — PR-012).
The wizard content is the frame's scrolling body: the sheet is a compact
block sized by its own content (owner ruling 2026-10-06, retiring the task
3.1 «широкий контент — на всю ширину главного окна» law — the spec's line is
amended by the next stage): both dimensions are frozen once at construction
— the width from the body's content formula (step column + preview at its
natural width + chrome, on the 40 step), the height from the content fit —
and the host window only rides them DOWN: a narrower window narrows the sheet
back, and whatever it cannot show is reached by the body's scroll («не влезшее
— прокруткой»).  The flow, the validations and the apply points are untouched
by the container move.

The preview opens on the CURRENT game date: «today» projected into game
coordinates through ``as_game_coord`` (the same «сегодня, н.э.» reading the
world-snapshot view model uses, the app stores no other now); when the
assembled calendar does not contain that coordinate (its month count or month
lengths refuse it) the grid simply stays on year 1 — the spec's «текущая
игровая дата, иначе год 1», with the grid's own un-prefill semantics doing the
fallback (no page jump, no crash).  After that opening placement the preview
only repaints pages on valid form edits, so the user's own month/year
navigation is never yanked back.

Skinning (task 6.4) is the catalog's, not bespoke QSS: the SheetFrame root is
attached by the frame itself (becoming a ``[uiRole="chrome"]`` container whose
push buttons, spin boxes and combo popups the generated sheet skins — it also
applies immediately, the QA 2026-09-30 F3 rule), labels come from the
catalog's ``title``/``hint`` factories, every input carries the ``field``
role, the report table the ``list`` role and the problems readout
``status-error``.  The only style-FACING class names the wizard itself puts on
screen are the grid's quartet — ``GameCalendarGrid``, ``GameCalendarCell``,
``GameCalendarIntercalaryChip`` and ``GameCalendarDayName`` — skinned by the
application-wide popup sheet (``compile_popup_qss``, design D4); they are
owned by :mod:`app.presentation.views.calendar_grid` and rename only together
with that sheet.  Invalid tokens (theme off) leave everything on the OS
palette while the flow stays alive (design D7).

Async convention copies the :class:`~app.presentation.views.event_types_dialog.EventTypesDialog`
facade: coroutines are fired through an injected ``run`` (``ensure_future`` by
default, so tests drive a bare loop) and :meth:`wait_idle` is the await seam.
Group 7 owns the entry points (menu item, first-entry sheet) and constructs
the view model; this dialog loads the draft when told to (:meth:`begin`) and
closes itself on a successful application (``accept``), so the ``finished``
listeners learn the outcome from the dialog result.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Callable

from PySide6.QtCore import QEvent, QSize
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedLayout,
    QStyle,
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
from app.presentation.layout_grid import ceil_to_width_step
from app.presentation.theme import get_default_theme
from app.presentation.theme.catalog import hint, set_role, title
from app.presentation.viewmodels.calendar_wizard_viewmodel import (
    KIND_CUSTOM,
    KIND_STANDARD,
    STEP_CHOICE,
    STEP_DAY,
    STEP_INTERCALARY,
    STEP_MONTHS,
    STEP_PREVIEW,
    STEP_REPORT,
    STEP_WEEK,
    CalendarWizardState,
    CalendarWizardViewModel,
)
from app.presentation.views.calendar_grid import GameCalendarGrid
from app.presentation.views.lucide_icons import lucide_icon
from app.presentation.views.sheet_frame import SheetFrame

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

# The «Сутки» spin bounds (NRI-0023 task 4.1).  The FLOOR of 0 is deliberate,
# not sloppiness: the spec scenario «Ноль не проходит» requires the 0 to be
# typeable so the stage answers with the inactive «Далее» and the Russian
# reason — a spin minimum of 1 would hide the very misuse the scenario pins
# (the domain gate ``*_below_min`` is what refuses it).  The ceiling is a
# widget need, not a domain cap — the validator knows none («нет продуктовых
# ограничений», валидация спеки ядра), the product's own 9999-scale of the
# month-length spin is reused as the numeric ceiling here too.
DAY_SIZE_MIN = 0
DAY_SIZE_MAX = 9999

#: Window title of the wizard.
WIZARD_TITLE = "Настройка календаря"
#: Title of the apply-failure window: the view model hands over the
#: displayable reason, the dialog only shows it (spec «Ошибки применения…»
#: leaves it open on the report/preview screen).
APPLY_ERROR_TITLE = "Применение календаря"

#: NRI-0018 Д7 cap on the content-sized step column: past it the row lists
#: (which already carry their own scroll rows) concede the width to the live
#: preview, «излишек — предпросмотру». The step of 40 this cap and the
#: column/minimum rounding climb along lives once in
#: :mod:`app.presentation.layout_grid` (the wizard imports its ceil).
STEP_COLUMN_MAX_WIDTH = 520
#: The minimum height of the compact W4 layout (NRI-0015); Д7 recounted the
#: WIDTH from the new column sum and left the height alone.
WIZARD_MIN_HEIGHT = 620

#: Fallback of the preview panel's right/bottom inner inset — the number
#: tokens.json itself carries for ``space.xs``; only an off-skin sheet
#: (design D7) ever reads it (the SheetFrame fallback pattern).
PREVIEW_EDGE_FALLBACK_PX = 4

#: The short steps — a block of fields with nothing scrollable in it («Выбор
#: типа», «Сутки», «Предпросмотр»).  For these the step stack stops eating the
#: column's vertical slack: the slack moves BELOW the footer, so the footer
#: reads right under its own content instead of riding the bottom of the sheet
#: across an empty band.  Every other step («Неделя», «Месяцы», «Вставные дни»,
#: «Отчёт») carries a scroll list or a table, where the stretch is the point.
COMPACT_STEPS = frozenset({STEP_CHOICE, STEP_DAY, STEP_PREVIEW})


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


class _StepStack(QWidget):
    """The step stack: a stacked layout that speaks the HEIGHT of the step on
    screen.

    Qt's stock stacked answer to both size hints is the maximum over ALL pages
    — and that maximum is also what its layout's minimum pins the widget to
    inside a parent layout, so not even a widget-level ``sizeHint`` override
    gets under it (measured on PySide 6.10: the short steps stayed exactly as
    tall as the tallest one).  A compact step therefore needs the stacked
    layout itself to follow the current page, which is why the stack is a plain
    widget carrying :class:`_CurrentStepLayout` (the same installation pattern
    the table desk's players box uses).  The width keeps the widest-page hint —
    the step column is sized from it (NRI-0018 Д7); only the height follows the
    step on screen, and it does so live: no pinned number can go stale when a
    caption or a wrap changes.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps = _CurrentStepLayout(self)

    def addWidget(self, page: QWidget) -> None:  # noqa: N802 — Qt API name
        self._steps.addWidget(page)

    def currentWidget(self) -> QWidget | None:  # noqa: N802 — Qt API name
        return self._steps.currentWidget()

    def setCurrentWidget(self, page: QWidget) -> None:  # noqa: N802 — Qt API name
        self._steps.setCurrentWidget(page)


class _CurrentStepLayout(QStackedLayout):
    """Stacked layout that speaks the current page in every height channel.

    The stock answer is the maximum over ALL pages — in ``sizeHint``, in
    ``minimumSize`` and, decisively, in ``heightForWidth``: the word-wrapped
    descriptions make the stack a height-for-width item, and a box layout takes
    that number instead of the size hint, so overriding the hint alone changes
    nothing (measured on PySide 6.10).  Delegating all three to the page on
    screen is what lets a compact step occupy exactly its own height — and it
    stays true live: a longer caption or a re-wrap moves the height with it,
    no pinned number to go stale.
    """

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — Qt API
        return self.currentWidget().hasHeightForWidth()

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — Qt API
        return self.currentWidget().heightForWidth(width)

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt API
        hint = super().sizeHint()
        hint.setHeight(self.currentWidget().sizeHint().height())
        return hint

    def minimumSize(self) -> QSize:  # noqa: N802 — Qt API
        hint = super().minimumSize()
        hint.setHeight(self.currentWidget().minimumSizeHint().height())
        return hint


class CalendarWizardDialog(SheetFrame):
    """Widgets shell of the calendar wizard: state out, intents in.

    The view model arrives ready-made (group 7 builds it over the game's
    session, service and ``first_entry`` flag); the dialog shows, asks and
    closes.  ``theme`` injects a :class:`ThemeRuntime` (default: the process
    one), ``run`` the coroutine launcher.

    Since nri-0024 task 3.1 the shell is a :class:`SheetFrame` sheet: the
    frame owns the header («Настройка календаря» + «Закрыть» — one cancel path
    with Esc), the stack scrim and the chrome skin, while the wizard screens
    live in the frame's scrolling body.  The sheet is a compact block sized by
    its own content (owner ruling 2026-10-06): width and height freeze once at
    construction — the width from the body's content formula on the 40 step,
    the height from the content fit — and the host window only rides them
    down; what a narrower window cannot show the body's scroll answers (spec
    «не влезшее — прокруткой»).
    """

    #: Usability floor of the sheet itself (the WorldSnapshotWindow rule): a
    #: shorter host window still gets this much wizard; below the body's own
    #: floor it is the vertical scroll that answers, not a taller sheet.
    MIN_SHEET_HEIGHT = 320
    #: The growth rule's breathing room under the host window's height.
    HEIGHT_INSET = 40

    def __init__(
        self,
        vm: CalendarWizardViewModel,
        parent: QWidget | None = None,
        theme=None,
        run: Callable | None = None,
    ) -> None:
        self._vm = vm
        self._run = run if run is not None else asyncio.ensure_future
        self._task: asyncio.Future | None = None
        # The calendar currently painted into the preview panel; repaints are
        # skipped while the preview calendar object has not changed.
        self._preview_shown: object | None = None

        # One windowTitle-threaded value: SheetFrame puts «Настройка
        # календаря» into the header caption and the title slot at once, and
        # attaches AND applies the chrome catalog right here — the frame's
        # skin already reaches the widgets built below (the QA 2026-09-30 F3
        # rule the old constructor hand-rolled mid-build).
        super().__init__(
            WIZARD_TITLE,
            parent,
            theme if theme is not None else get_default_theme(),
        )

        body = QWidget()
        # NRI-0018 Д7 retired the static 880 floor group 5 pinned (its own
        # comment reserved the recount for Д7): the width floor is now the
        # sum of the NEW columns — the content-sized step column plus the
        # live preview at its own minimum — climbed to the nearest step of 40
        # upwards, so the width never leaves the scale and the preview grid
        # fits whole at the minimum (spec «Предпросмотр не сжат»).  Since
        # task 3.1 the floor belongs to the scrolling BODY, not to the sheet:
        # the sheet tracks the host window and lets the scroll take the rest.
        # See the setMinimumSize call at the tail of the layout build.
        root = QHBoxLayout(body)
        left = QVBoxLayout()
        right = QVBoxLayout()

        self._stack = _StepStack()
        self._pages = {
            STEP_CHOICE: self._build_choice_page(),
            STEP_WEEK: self._build_week_page(),
            STEP_MONTHS: self._build_months_page(),
            STEP_INTERCALARY: self._build_intercalary_page(),
            STEP_DAY: self._build_day_page(),
            STEP_PREVIEW: self._build_preview_page(),
            STEP_REPORT: self._build_report_page(),
        }
        for page in self._pages.values():
            self._stack.addWidget(page)
        # Where the column's vertical slack goes is a per-step switch (see
        # COMPACT_STEPS): the stack itself (the scroll steps) or the parking
        # strip below the footer (the short ones).  Both seats are in the
        # layout from the start; _render_state only moves the stretch factors,
        # so no widget is ever pulled out of or pushed into the layout.
        self._stack_index = left.count()
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
        # QML ThemeButton parity: the compiled sheet paints the ordinary face
        # on every chrome button; only the wizard's forward actions opt into
        # the primary face («Далее», «Применить»).  Dismissal («Отменить»,
        # «Назад») stays plain — one accent per row, not three.
        set_role(self._next_button, "primary")
        set_role(self._apply_button, "primary")
        # W4 (spec «Кнопки мастера — одна строка…», the row half this package
        # leaves untouched): one row, the dismissal at the OPPOSITE edge from
        # its content group.  With the old order the cancel sat at the far
        # right, flush against the preview panel on a wide window, and read
        # as the preview's own button.
        footer_row.addWidget(self._cancel_button)
        footer_row.addStretch()
        footer_row.addWidget(self._back_button)
        footer_row.addWidget(self._next_button)
        footer_row.addWidget(self._apply_button)
        left.addWidget(self._footer)

        # The short step's parking strip: normally inert (stretch 0), it takes
        # the whole column slack the moment a compact step becomes current —
        # under the footer, so the empty canvas ends up at the bottom of the
        # sheet instead of between the content and its buttons.
        self._steps_layout = left
        self._parking_index = left.count()
        left.addStretch()

        # Catalog skin: the SheetFrame attached and applied the chrome sheet
        # on its root in super().__init__ — the generated rules reach the
        # widgets below through the widget-parent chain (QA 2026-09-30 F3:
        # the runtime pushes the chrome QSS in apply() only; doing it before
        # any hint read is what keeps the Д7 geometry below honest).

        # The sheet's body (task 3.1, spec «не влезшее — прокруткой»): the
        # whole wizard layout in one vertically scrolling area under the
        # header.  NoFrame: like the QML island sheets the body wears the
        # sheet canvas, not a sunken panel.  Seating the body into the styled
        # tree happens with setWidget below, BEFORE the Д7 hint reads, for
        # the same reason the old build attached the skin first: outside the
        # chrome sheet the buttons report their unskinned box metrics.
        self._body = body
        self._body_scroll = QScrollArea(self)
        self._body_scroll.setObjectName("calendarWizardBody")
        self._body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body_scroll.setWidgetResizable(True)
        self.add_content(self._body_scroll, stretch=1)
        self._body_scroll.setWidget(body)

        # Д7 (spec «Левая колонка мастера широка ровно по содержимому»): the
        # old fixed 3:2 share is gone.  The column is exactly as wide as its
        # widest natural content — the step stack (its WIDTH is still the
        # maximum over all pages, see _StepStack) or the one-row buttons,
        # plus the column's own insets (without them the 40-step rounding
        # would let the padding eat the content's room) — rounded UP to the
        # 40 step and capped; the width then stays fixed so the step forms
        # neither drift with the window nor grow a dead zone («справа от
        # шага нет широкой мёртвой зоны»).  The sums are read from the
        # widgets directly, not from the layouts: a layout of a dialog that
        # was never shown reports its items as empty (Qt hides-until-polished
        # semantics), while a widget's own sizeHint is valid right here.
        self._step_column = QWidget()
        self._step_column.setLayout(left)
        # The hint reads happen with the column already added to the styled
        # tree: outside it the dialog's chrome sheet does not reach the
        # buttons yet and they report their unskinned box metrics (QA
        # 2026-09-30 F3 follow-up — the same sheet the F3 fix now pushes at
        # construction moves the footer's hint by a whole button's width).
        root.addWidget(self._step_column)
        margins = left.contentsMargins()
        column_natural = (
            max(
                self._stack.sizeHint().width(),
                self._problems_label.sizeHint().width(),
                self._footer.sizeHint().width(),
            )
            + margins.left()
            + margins.right()
        )
        self._step_column.setFixedWidth(
            min(ceil_to_width_step(column_natural), STEP_COLUMN_MAX_WIDTH)
        )

        right.addWidget(title("Предпросмотр"))
        # The live preview: the same grid class the date popups embed, inert
        # (STYLE-FACING class names skinned by the popup sheet — see module).
        # W1 (spec «Экран-предпросмотр собран плотно и читаемо»): the grid
        # keeps its own height — the day-name header was already the grid's
        # first row, a stretched second header slot is what tore the names
        # away from the numbers; every slack pixel belongs to the trailing
        # stretch below the grid, never between the header and the cells.
        self._preview = GameCalendarGrid(interactive=False, show_era=False)
        # Live audit 2026-10-06: a vertically growable grid took any slack the
        # right column ever showed and inflated its week rows past their natural
        # height (measured ~55 px cells against the natural ~30).  This SEAT
        # pins the vertical to the grid's own live sizeHint — the number still
        # recounts when the month or a long-week page repaints — and leaves the
        # trailing stretch as the only place the slack can park.  The grid class
        # stays untouched: the date popups keep their native seat.
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        # Live audit 2026-10-06: the grid's root layout insets its content by
        # 2 px, so «Воскресенье» ended ~1 pt from the panel's inner frame and
        # the frame closed ~1–2 pt under the last week.  The frame is painted
        # on the grid widget itself (the ``GameCalendarGrid`` QSS), so the one
        # door between the content and that frame — without touching
        # :mod:`calendar_grid` (the date popups keep their native seat) — is
        # THIS instance's root layout, set here at the usage site: the right
        # and bottom edges breathe by ``space.xs``, the cells shift inward by
        # the same amount while the nav band's own left seat stays put.
        preview_margins = self._preview.layout().contentsMargins()
        preview_edge = self._token_px("space.xs", PREVIEW_EDGE_FALLBACK_PX)
        preview_margins.setRight(preview_edge)
        preview_margins.setBottom(preview_edge)
        self._preview.layout().setContentsMargins(preview_margins)
        right.addWidget(self._preview)
        right.addStretch(1)
        # Every pixel the fixed step column does not need belongs to the
        # preview panel (Д7: «излишек — предпросмотру») — the leftover goes
        # to the right column with a single stretch, not to a 40 % cap.
        root.addLayout(right, 1)

        # The recounted minimum (see the note over the layout build) is
        # composed after the first render below — a fresh preview answers its
        # FIRST minimumSizeHint cold under the chrome sheet (measured
        # 2026-10-01: 448 at construction, 458 once the style metrics have
        # been walked; the retired bold base rule used to warm them earlier),
        # and the on-screen layout enforces the warmed value.
        self._back_button.clicked.connect(self._vm.go_back)
        self._next_button.clicked.connect(lambda: self._start(self._vm.try_advance()))
        self._apply_button.clicked.connect(lambda: self._start(self._vm.apply()))
        self._cancel_button.clicked.connect(self._on_cancel)
        self._transfer_apply_button.clicked.connect(
            lambda: self._start(self._vm.confirm_transfer())
        )
        self._transfer_cancel_button.clicked.connect(self._vm.cancel_report)
        # W2 (spec «Выбор пресета работает через доступность»): the radios' AX
        # action toggles the check mark through ``setChecked`` — the old
        # ``clicked`` handler never fired and the model stayed on the
        # preselect (the tick moved, «Далее» never did).  The choice hangs on
        # ``toggled`` now; the recursion through the view model's repaint of
        # the very radios is fenced by the existing blockSignals contour in
        # :meth:`_render`.
        self._standard_radio.toggled.connect(
            lambda checked: self._on_kind_toggled(KIND_STANDARD, checked)
        )
        self._custom_radio.toggled.connect(
            lambda checked: self._on_kind_toggled(KIND_CUSTOM, checked)
        )
        self._week_length_spin.valueChanged.connect(self._vm.set_week_length)
        self._month_count_spin.valueChanged.connect(self._vm.set_month_count)
        self._day_hours_spin.valueChanged.connect(self._vm.set_day_hours)
        self._minutes_per_hour_spin.valueChanged.connect(
            self._vm.set_minutes_per_hour
        )
        self._rule_add_button.clicked.connect(self._on_add_rule)

        self._vm.state_changed.connect(self._render)
        self._vm.apply_succeeded.connect(self.accept)
        self._vm.apply_failed.connect(self._show_apply_error)

        self._render()
        # Spec «отображаемая дата — текущая игровая дата, иначе год 1»: ONE
        # placement per opened preview state — later repaints keep whatever
        # page the user navigated to («навигация по месяцам и годам работает»).
        self._place_preview()
        # The recounted minimum (see the note over the layout build): fixed
        # column + the preview at its own minimum + the root layout's own
        # chrome, climbed to the next step of 40.  Since task 3.1 this floor
        # belongs to the scrolling BODY: the sheet itself shrinks with the
        # host window and the vertical scroll takes what does not fit, while
        # the body is never squeezed below the compact floor («минимальная
        # высота тела из контента widest-шага» — design Д6 risk).  Composed
        # from the widget hints explicitly because — as above — the body's
        # own minimumSizeHint() is still empty this early in construction.
        # The style metric stands in for the unresolved (-1) layout spacing
        # the cocoa style reports.  It stands HERE, after the first render,
        # for the same reason: the render walk warms the chrome sheet's
        # metrics of the preview's nav widgets, and only the warmed hint is
        # what the on-screen layout will enforce (2026-10-01: 448 cold vs
        # 458 warm).
        style_spacing = self.style().pixelMetric(QStyle.PM_LayoutHorizontalSpacing)
        spacing = root.spacing() if root.spacing() >= 0 else style_spacing
        root_margins = root.contentsMargins()
        chrome = (
            root_margins.left()
            + root_margins.right()
            + spacing
        )
        # The body's own scroll bar, in pixels: both frozen numbers below pay
        # for its seat up front (live audit 2026-10-06 follow-up).  The header
        # draws taller than its sizeHint under the live sheet (42 pt drawn vs
        # 41 hinted), the exact content sums froze the sheet ~1 pt short, the
        # vertical bar stood permanently over a fully visible content — and
        # then ate ~13.5 pt out of the frozen width until the horizontal bar
        # joined the parade.  One scroll extent is the conservative margin:
        # whatever the live font metrics add on top of the hints, the bar's
        # seat is already paid for and neither bar appears at live metrics.
        scroll_extent = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        body.setMinimumSize(
            ceil_to_width_step(
                self._step_column.maximumWidth()
                + self._preview.minimumSizeHint().width()
                + chrome
            ),
            WIZARD_MIN_HEIGHT,
        )

        # The sheet's default height is frozen ONCE here: the first render above
        # walked the chrome sheet and warmed the preview's metrics (the 448-cold
        # vs 458-warm note stands just above), and the body's floor is set.  The
        # live re-read of ``_default_sheet_height`` is what inflated the sheet:
        # under the body's ``setWidgetResizable`` scroll area the estimate chased
        # the layout's own geometry (the «height → hint → height» loop, re-run on
        # every host Resize through the filter below), so a tall host window
        # landed the sheet at exactly «host − HEIGHT_INSET» and the preview rows
        # swelled with it (live audit 2026-10-06).  The frozen number is the
        # growth rule's CAP only: the height still follows the host DOWN
        # (floor MIN_SHEET_HEIGHT included), and since the owner ruling below
        # the width does the same from its own frozen content number.
        self._frozen_default_height = self._default_sheet_height()

        # The sheet's default WIDTH freezes the same way (owner ruling
        # 2026-10-06, retiring the task-3.1 «широкий контент — на всю ширину
        # главного окна» law — the spec line is amended by the next stage):
        # the body's content formula — the fixed step column + the preview at
        # its own NATURAL width (the warmed sizeHint, the same warmed-metrics
        # rule the height reads above) + the root layout's chrome + the seat of
        # the body's vertical scroll bar — climbed to the 40 step, so the
        # frozen number itself stays on the width scale
        # (test_window_width_scale).  The extent term is what keeps a vertical
        # bar from ever forcing a horizontal one at the frozen width: the
        # viewport is the sheet minus the bar, and content + chrome still fit
        # inside it, so the preview panel never presses its frame against the
        # bar (the root layout's right margin survives).  Live audit 2026-10-06
        # follow-up: without it the live 984 px of content froze at 1000, the
        # vertical bar took 13.5 of those and the horizontal bar followed.  A
        # wide host therefore gets the sheet as a compact block, not a strip:
        # the right column never receives the window's surplus and the grid's
        # cells never inflate past their natural width.  The parent-less probe
        # below opens at the body's floor instead — the narrowest content
        # shape, unchanged.
        self._frozen_default_width = ceil_to_width_step(
            self._step_column.maximumWidth()
            + self._preview.sizeHint().width()
            + chrome
            + scroll_extent
        )

        # Sheet geometry (owner ruling 2026-10-06 «компактный лист по
        # контенту»): both dimensions are the numbers frozen at this point,
        # the host window only riding them down — a narrower window narrows
        # the sheet back (the body keeps its own floor and its scroll answers
        # the squeeze), never a pixel WIDER than the parent.  The growth
        # filter dies with the sheet in done() below.
        if parent is not None:
            parent.installEventFilter(self)
            self.resize(self._sheet_size_for(parent))
        else:
            # A parent-less offscreen probe opens content-sized — the shape
            # the old top-level took at its own minimum.
            self.resize(self._body.minimumWidth(), self._frozen_default_height)

    # ── sheet geometry (content-frozen size, host rides it down, scroll) ────

    def _default_sheet_height(self) -> int:
        """The sheet's content-fit default: the body floor plus the header plus
        one scroll bar's extent as the live-chrome margin.

        Read ONCE into :attr:`_frozen_default_height` at the end of the
        constructor (the live value is geometry-sensitive under the body's
        ``setWidgetResizable`` scroll area: the stretch steps grow the body
        hint with whatever height the layout handed it, which let a tall host
        window pull the estimate — and with it the sheet — to «host − inset»
        and let the preview rows swell in the freed space; live audit
        2026-10-06).  After the freeze only the frozen number caps growth.

        The extent term answers the same audit's follow-up: the header draws
        taller than its sizeHint under the live sheet (42 pt drawn vs 41
        hinted), the exact hint sum froze the sheet ~1 pt short, and a ~13.5 pt
        vertical bar stood permanently over a fully visible content.  Rather
        than chase the drawn height through a re-freeze on first show (a second
        cap the repeated showEvents could move), the hint sum conservatively
        pays for the bar's own seat: whatever the live font metrics add on top
        of the hints, it stays under one scroll extent and no bar appears.
        """
        return (
            max(self._body.sizeHint().height(), self._body.minimumHeight())
            + self.header.sizeHint().height()
            + self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        )

    def _sheet_size_for(self, host: QWidget) -> QSize:
        """The growth rule at this host size: the width frozen at construction
        capped by the host (the sheet is a compact content block, never wider
        than its parent; a host narrower than the frozen width narrows the
        sheet back and the body's floor + horizontal scroll answer the
        squeeze — the narrowing task 3.1 pinned, preserved), plus the
        window-following height between the floor and the FROZEN content cap
        (never the live estimate — see :meth:`_default_sheet_height`)."""
        return QSize(
            min(self._frozen_default_width, host.width()),
            min(
                self._frozen_default_height,
                max(self.MIN_SHEET_HEIGHT, host.height() - self.HEIGHT_INSET),
            ),
        )

    def _fit_to_parent(self) -> None:
        """Track the host window while the sheet is open; a parent-less
        sheet (the offscreen probes) keeps the size it opened at."""
        host = self.parentWidget()
        if host is None:
            return
        self.resize(self._sheet_size_for(host))

    def showEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().showEvent(event)
        self._fit_to_parent()

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._fit_to_parent()
        return super().eventFilter(watched, event)

    def done(self, result: int) -> None:  # noqa: N802 — Qt API name
        # Every way this sheet leaves the screen passes done(); the growth
        # filter leaves with it — a closed layer has no business chasing
        # window resizes anymore (the WorldSnapshotWindow rule).
        host = self.parentWidget()
        if host is not None:
            host.removeEventFilter(self)
        super().done(result)

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
        page, layout = _step_page()
        layout.addWidget(title("Стандартный или свой календарь?"))
        kind_hint = hint(
            "Стандартный — привычные 12 григорианских месяцев. Кастомный — "
            "своё число месяцев, их имена и длины, своя неделя и вставные дни."
        )
        kind_hint.setWordWrap(True)
        layout.addWidget(kind_hint)
        self._standard_radio = QRadioButton("Стандартный")
        self._custom_radio = QRadioButton("Кастомный")
        # NRI-0018 Д7 revised the per-item clause of W4 (spec RENAMED:
        # «шаг прижат к тексту»): no per-control centering any more — in the
        # column layout each switch fills its cell, so both indicators start
        # on the single left border shared with the title and the hint no
        # matter what text width each switch carries.  (The one-row button
        # clause of that spec — the footer above — this package deliberately
        # does not touch.)
        layout.addWidget(self._standard_radio)
        layout.addWidget(self._custom_radio)
        # No tail stretch on a compact step: its own bottom edge is the content,
        # the parking strip under the footer owns the column's slack.
        return page

    def _build_week_page(self) -> QWidget:
        # Fields are one per week day, so the length spin is what adds the
        # empty tail / drops the tail names (spec «Экран „Неделя“»).
        page, layout = _step_page()
        layout.addWidget(title("Неделя"))
        self._week_length_spin = self._spin_row(layout, "Длина недели:")
        self._week_length_spin.setRange(WEEK_LENGTH_MIN, WEEK_LENGTH_MAX)
        self._week_box = _row_box()
        layout.addWidget(_wrap_scroll(self._week_box), 1)
        self._week_fields: list[QLineEdit] = []
        return page

    def _build_months_page(self) -> QWidget:
        page, layout = _step_page()
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
        page, layout = _step_page()
        layout.addWidget(title("Вставные дни"))
        rules_hint = hint(
            "Порядок списка значим: правила одного месяца-хозяина занимают "
            "его последовательные позиции."
        )
        rules_hint.setWordWrap(True)  # wraps inside the content-sized step column
        layout.addWidget(rules_hint)
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
        # The compiled sheet paints this button with the ordinary chrome face
        # (canvas fill, primary ink), so the glyph wears the default caption
        # ink — an accent-tinted glyph would speak the primary-button ink.
        self._rule_add_button.setIcon(lucide_icon("plus"))
        add_row.addWidget(self._rule_name_edit, 1)
        add_row.addWidget(self._rule_month_combo)
        add_row.addWidget(self._rule_add_button)
        layout.addLayout(add_row)
        return page

    def _build_day_page(self) -> QWidget:
        # NRI-0023 task 4.1 (spec «Экран „Сутки“»): two number fields and no
        # name fields — the screen sizes the day, it never names its hours or
        # minutes; the year grid preview is independent of the day size.
        page, layout = _step_page()
        layout.addWidget(title("Сутки"))
        day_hint = hint(
            "Насколько длинен день этого мира: часов в сутках и минут в часе. "
            "Земная норма — 24 и 60; нездешний мир живёт и своими числами."
        )
        day_hint.setWordWrap(True)
        layout.addWidget(day_hint)
        self._day_hours_spin = self._spin_row(layout, "Часов в сутках:")
        self._day_hours_spin.setRange(DAY_SIZE_MIN, DAY_SIZE_MAX)
        self._minutes_per_hour_spin = self._spin_row(layout, "Минут в часе:")
        self._minutes_per_hour_spin.setRange(DAY_SIZE_MIN, DAY_SIZE_MAX)
        return page

    def _build_preview_page(self) -> QWidget:
        page, layout = _step_page()
        # The right-hand panel already owns the «Предпросмотр» caption over the
        # grid; a second one here was the double header (W1) — this step only
        # carries its summary block.
        layout.addWidget(title("Сводка"))
        # «сводка (число месяцев, длина недели, число вставных дней, часы в
        # сутках и минуты в часе)» — the grid itself lives in the right-hand
        # panel next to every screen.  Word wrap like every other description
        # of the step column (NRI-0018 Д7 «описания держат ширину колонки»):
        # with the day size named in it (NRI-0023 task 4.1) the line is wider
        # than the column and must wrap into it, not stretch the stack's
        # sizeHint past the width the column was sized from.
        self._summary_label = hint("")
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)
        grid_hint = hint("Слева — сводка, справа — сетка будущего календаря. «Применить» — внизу.")
        grid_hint.setWordWrap(True)
        layout.addWidget(grid_hint)
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
        # Same face split as the footer: the applying action is primary, the
        # going-back «Отменить» stays plain.
        set_role(self._transfer_apply_button, "primary")
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

    def _move_step_slack(self, step: str) -> None:
        """One switch, two seats: the scroll steps keep stretching the stack
        (the list owns the column's height), the short steps hand the very
        slack to the strip below the footer, which lifts the footer right behind
        the step's content.  ``setStretch`` keeps every widget in place and
        revalidates the layout itself."""
        compact = step in COMPACT_STEPS
        self._steps_layout.setStretch(self._stack_index, 0 if compact else 1)
        self._steps_layout.setStretch(self._parking_index, 1 if compact else 0)

    def _render_state(self, state: CalendarWizardState) -> None:
        self._stack.setCurrentWidget(self._pages[state.step])
        self._move_step_slack(state.step)

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
        _bind_spin(self._day_hours_spin, state.day_hours)
        _bind_spin(self._minutes_per_hour_spin, state.minutes_per_hour)

        self._summary_label.setText(
            f"Месяцев: {len(state.months)} · "
            f"Длина недели: {len(state.week_names)} · "
            f"Вставных дней: {len(state.intercalary)} · "
            # NRI-0023 task 4.1 (spec «Сводка называет сутки»): the preview
            # summary names the day size next to the other parameters.
            f"Часов в сутках: {state.day_hours} · "
            f"Минут в часе: {state.minutes_per_hour}"
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
            # Plain chrome face (canvas fill, primary ink): the glyph shares
            # the caption's default ink, no accent tint (F2 re-read after the
            # 2026-10-01 face split).
            remove_button.setIcon(lucide_icon("trash"))
            # Icon-only arrows: the Russian accessible names carry the meaning
            # the glyph cannot speak (the widgets-side a11y rule).
            up_button = QPushButton()
            up_button.setIcon(lucide_icon("arrow-up"))
            up_button.setAccessibleName("Поднять правило")
            down_button = QPushButton()
            down_button.setIcon(lucide_icon("arrow-down"))
            down_button.setAccessibleName("Опустить правило")
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

    def _on_kind_toggled(self, kind: str, checked: bool) -> None:
        """The radio's ``toggled`` is both the mouse and the accessibility
        channel (W2): only becoming-checked is a choice — the auto-exclusive
        uncheck of the other radio must not reach the view model, and the
        state re-render's own ``setChecked`` pass is fenced by its
        blockSignals pair."""
        if checked:
            self._vm.choose_kind(kind)

    def _on_cancel(self) -> None:
        """Footer «Отменить»: the view model keeps the draft by contract (spec
        «Черновик мастера»), the dialog simply closes."""
        self._vm.cancel()
        self.reject()

    def _show_apply_error(self, reason: str) -> None:
        """Spec «Ошибки применения… окно с причиной»: reason verbatim from the
        view model (it is already a displayable string), wizard stays open."""
        QMessageBox.warning(self, APPLY_ERROR_TITLE, reason)


def _step_page() -> tuple[QWidget, QVBoxLayout]:
    """Content column of a build step.  Since NRI-0018 Д7 the step carries no
    per-item centering at all: the page stretches in the content-sized step
    column and every control starts on that column's single left border; the
    descriptions keep the full column width for their word wrap and the row
    lists for their scroll rows."""
    page = QWidget()
    return page, QVBoxLayout(page)


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
