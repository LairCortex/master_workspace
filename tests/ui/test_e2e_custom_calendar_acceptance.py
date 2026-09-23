"""E2E acceptance of the custom calendar (change close-custom-calendar-map).

Spec ui-testing «E2E-приёмка кастомного календаря», design D2–D4: every
calendar element — the day grid, the intercalary chip, the era check box and
the wizard screens — is driven with REAL mouse clicks over the live
``Application`` lifecycle (dark theme, the suite's own), on one fixed custom
spec that matches no preset and no unit-test fixture: an eight-day week
(«Перови»…«Осьми»), three months of lengths 30/29/28, and one intercalary day
«День Пепела» after month 2 (design D4).

Scene 1 (this file's first test) walks a NEW game end to end: the first-entry
wizard opens modally before the window shows (the C4 boot contract, verified
through the ``ModalControl`` seam the offscreen suite uses for true modals),
then the full wizard path runs by clicks — «Кастомный» → «Неделя» → «Месяцы»
→ «Вставные дни» → «Предпросмотр» → «Применить» — and the game lives on the
custom calendar: the range popover speaks the new month and week names, the
feed/detail/world-snapshot captions say «День Пепела 1» (the intercalary day
names itself, no day number) and «… г. до н.э.» for the BC record, and a full
``shutdown()``/``start()`` restart over the same file leaves every caption,
coordinate and key untouched (spec «Мастер до конца и жизнь кастомной игры»).

Scene 2 (the mid-game shorten with the transfer report) lands in this SAME
file as task group 3: the ``custom_spec`` fixture and the
:func:`seed_applied_custom_calendar` promote-style seeder below are its
pre-built entry points (design D2 — no second full wizard walk there).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QWidget,
)

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
)
from app.infrastructure.calendar_storage import (
    CalendarDraft,
    DRAFT_STAGE_MONTHS,
    encode_calendar,
    encode_coord,
    encode_draft,
)
from app.infrastructure.repositories.game_settings_repository import (
    CALENDAR_DRAFT_KEY,
    CALENDAR_SETTINGS_KEY,
    CALENDAR_WIZARD_SEEN_KEY,
)
from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db
from app.main import Application
from app.presentation.theme import ThemeRuntime
from app.presentation.viewmodels.calendar_wizard_viewmodel import (
    KIND_CUSTOM,
    KIND_STANDARD,
    STEP_CHOICE,
    STEP_MONTHS,
    STEP_REPORT,
)
from app.presentation.views.calendar_grid import (
    GameCalendarCell,
    GameCalendarDayName,
    GameCalendarIntercalaryChip,
)
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.main_window import MainWindow

from tests.presentation import qml_helpers
from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

#: The one acceptance spec (design D4). The week is eight days long, the
#: months are 3 × {30, 29, 28}, «День Пепела» is hosted by month 2 — nothing
#: here collides with the presets or with any unit-test fixture.
WEEK_NAMES = (
    "Перови", "Дрови", "Трети", "Четвери",
    "Пятицы", "Шестови", "Седмери", "Осьми",
)
MONTH_NAMES = ("Ведодей", "Пуровеж", "Ледянь")
MONTH_LENGTHS = (30, 29, 28)
INTERCALARY_NAME = "День Пепела"

#: The two clicked records of scene 1: an open-ended event on the intercalary
#: day year 1, and a BC event 13 Ведодей — 20 Пуровеж of year 3.
INTERCALARY_EVENT = "Пепельный шабаш"
BC_EVENT = "Древняя клятва"
INTERCALARY_DAY = IntercalaryDay(1, 0)
BC_START = MonthDay(3, 1, 13)
BC_END = MonthDay(3, 2, 20)

INTERCALARY_CAPTION = f"{INTERCALARY_NAME} 1 — ∞"
BC_CAPTION = (
    "13 Ведодей 3 г. до н.э. — 20 Пуровеж 3 г. до н.э."
)

_EVENT_COLUMNS = (
    "start_date, end_date, start_key, end_key,"
    " start_coord, end_coord, start_bc, end_bc"
)


# ── shared fixtures / seeding (design D2: both scenes read from here) ────────

@pytest.fixture
def custom_spec() -> CalendarSpec:
    """The fixed acceptance spec — scene 1 assembles it in the wizard,
    scene 2 (group 3) seeds the applied calendar straight from it."""
    return CalendarSpec(
        months=tuple(
            MonthSpec(name, length)
            for name, length in zip(MONTH_NAMES, MONTH_LENGTHS)
        ),
        week_names=WEEK_NAMES,
        intercalary=(IntercalarySpec(INTERCALARY_NAME, 2),),
    )


async def seed_applied_custom_calendar(
    db_path: Path, calendar: CustomCalendar
) -> None:
    """Create a game file whose ``game_calendar`` IS the custom calendar
    already (the wizard-entry suite's seeding pattern, design D2).

    Scene 2 (group 3) starts from this instead of a second full wizard walk;
    the wizard-seen flag is seeded «показан» so the boot opens the game
    without the first-entry modal, as for any mid-game calendar edit.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    (db_path.parent / "images").mkdir(exist_ok=True)
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT OR REPLACE INTO game_settings (key, value) VALUES (?, ?)",
                (CALENDAR_SETTINGS_KEY, encode_calendar(calendar)),
            )
            await conn.exec_driver_sql(
                "INSERT OR REPLACE INTO game_settings (key, value) VALUES (?, ?)",
                (CALENDAR_WIZARD_SEEN_KEY, "1"),
            )
    finally:
        await engine.dispose()


def _settings_rows(db_path: Path) -> dict[str, str]:
    return dict(query_db(db_path, "SELECT key, value FROM game_settings"))


def _visible_wizard(window: MainWindow) -> CalendarWizardDialog | None:
    """The wizard the menu entry opened over the main window, if any."""
    for dialog in window.findChildren(CalendarWizardDialog):
        if dialog.isVisible():
            return dialog
    return None


# ── click helpers (design D3: real input on the existing anchors only) ───────

def _week_name_labels(grid: QWidget) -> list[str]:
    return [
        label.text()
        for label in grid.findChildren(GameCalendarDayName)
    ]


def _month_combo_names(grid: QWidget) -> list[str]:
    combo = grid._month_combo
    return [combo.itemText(i) for i in range(combo.count())]


def _day_cell(grid: QWidget, day: int) -> GameCalendarCell:
    return next(
        cell
        for cell in grid.findChildren(GameCalendarCell)
        if cell.text() == str(day)
    )


def _intercalary_chip(grid: QWidget) -> GameCalendarIntercalaryChip:
    chips = grid.findChildren(GameCalendarIntercalaryChip)
    assert chips, "the page shows no intercalary chip"
    return chips[0]


def _click(qtbot, widget: QWidget) -> None:
    """One real mouse click on a widgets control: press + release mouse
    events with the buttons spelled out explicitly — the same spontaneous
    input recipe ``timeline_probe._send_mouse`` established for the island
    (``QTest.mouseClick`` consults the process-global button/window state
    the offscreen platform leaves stale and then silently drops the hit).

    Check boxes and radios are hit through their style indicator rect: the
    offscreen QFusion hit region of ``QCheckBox``/``QRadioButton`` is the
    indicator itself, and the center of such a wide row widget is its label,
    which ``hitButton`` refuses exactly like it does without a click.
    """
    if isinstance(widget, QRadioButton | QCheckBox):
        option = QStyleOptionButton()
        widget.initStyleOption(option)
        subElement = (
            QStyle.SubElement.SE_RadioButtonIndicator
            if isinstance(widget, QRadioButton)
            else QStyle.SubElement.SE_CheckBoxIndicator
        )
        pos: QPoint = widget.style().subElementRect(subElement, option, widget).center()
    else:
        pos = widget.rect().center()
    global_pos = widget.mapToGlobal(pos)
    for kind, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(widget, QMouseEvent(
            kind, QPointF(pos), global_pos,
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier,
        ))
        QApplication.processEvents()  # let the button's state machine tick
    qtbot.wait(2)


def _step_months(qtbot, grid: QWidget, clicks: int) -> None:
    """Navigate with real clicks on the grid's own ▶ button."""
    for _ in range(clicks):
        _click(qtbot, grid._next_btn)


async def _tap_qml(qtbot, widget, object_name: str) -> None:
    """A synthetic mouse click on the island item behind ``object_name``."""
    qml_helpers.click_item(widget, qml_helpers.find_item(widget, object_name))
    qtbot.wait(10)  # let the TapHandler press/release cycle settle


# ── scene 1: the wizard to the end and the life of a custom game ─────────────

async def test_custom_calendar_from_wizard_to_every_caption_and_restart(
    qapp, llm_client, tmp_llm_config, modal_qdialog, tmp_path, qtbot,
    wait_for, custom_spec,
):
    application = Application(
        qapp,
        http=llm_client,
        # The suite's own dark theme, isolated inside tmp_path like in every
        # other e2e file (design D4: one theme for the acceptance).
        theme=ThemeRuntime(prefs=_ui_prefs(tmp_path)),
    )
    db_path = tmp_path / "custom" / "game.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    (db_path.parent / "images").mkdir(exist_ok=True)

    # ── A. a NEW game: the first-entry wizard really precedes the window ────
    # Offscreen true modals are observed through ModalControl (the C4 suite's
    # convention): the dialog is constructed by start() and its close
    # semantics run whole («Крест = Стандартный» applies the preset once).
    first_entry: dict = {}

    def _record_first_entry(dlg) -> None:
        assert application._window is None  # before MainWindow.show()
        assert not [
            w for w in qapp.topLevelWidgets()
            if isinstance(w, MainWindow) and w.isVisible()
        ]
        first_entry["type"] = type(dlg)
        first_entry["kind"] = dlg._vm.state.kind
        first_entry["step"] = dlg._vm.state.step

    modal_qdialog.on_exec(_record_first_entry)
    window = await application.start(str(db_path))
    assert first_entry == {
        "type": CalendarWizardDialog,
        "kind": KIND_STANDARD,
        "step": STEP_CHOICE,
    }
    try:
        rows = _settings_rows(db_path)
        assert rows[CALENDAR_WIZARD_SEEN_KEY] == "1"  # the boot close applied the preset once

        # ── B. the full wizard path, clicked: custom → … → «Применить» ──────
        window.calendar_wizard_action.trigger()
        await wait_for(lambda: _visible_wizard(window) is not None)
        wizard = _visible_wizard(window)
        await helpers.wait_until_settled()

        # Step «выбор»: a real click on «Кастомный», then «Далее».
        _click(qtbot, wizard._custom_radio)
        assert wizard._vm.state.kind == "custom"
        _click(qtbot, wizard._next_button)
        await wizard.wait_idle()  # → «Неделя»

        # Step «Неделя»: length 8, then all eight names typed into the rows
        # the screen grew for.
        assert len(wizard._week_fields) == 7  # the standard prefill
        wizard._week_length_spin.setValue(8)
        assert len(wizard._week_fields) == 8
        for edit, name in zip(wizard._week_fields, WEEK_NAMES):
            edit.setText(name)
        _click(qtbot, wizard._next_button)
        await wizard.wait_idle()  # → «Месяцы»

        # Step «Месяцы»: three «имя | длина» rows.
        wizard._month_count_spin.setValue(3)
        assert len(wizard._month_rows) == 3
        for (name_edit, length_spin), (name, length) in zip(
            wizard._month_rows, zip(MONTH_NAMES, MONTH_LENGTHS)
        ):
            name_edit.setText(name)
            length_spin.setValue(length)
        _click(qtbot, wizard._next_button)
        await wizard.wait_idle()  # → «Вставные дни»

        # Step «Вставные дни»: one chip after month 2 («Пуровеж»), added with
        # a real click on «Добавить».
        wizard._rule_name_edit.setText(INTERCALARY_NAME)
        combo = wizard._rule_month_combo
        combo.setCurrentIndex(combo.findData(2))
        _click(qtbot, wizard._rule_add_button)
        assert wizard._rule_rows[0][0].text() == (
            f"{INTERCALARY_NAME} → {MONTH_NAMES[1]}"
        )
        _click(qtbot, wizard._next_button)
        await wizard.wait_idle()  # → «Предпросмотр»

        # Step «Предпросмотр»: the summary line AND the live preview grid
        # (the same GameCalendarGrid class the popups embed) speak the spec.
        assert wizard._summary_label.text() == (
            "Месяцев: 3 · Длина недели: 8 · Вставных дней: 1"
        )
        assert _week_name_labels(wizard._preview) == list(WEEK_NAMES)
        assert _month_combo_names(wizard._preview) == list(MONTH_NAMES)

        assert wizard._apply_button.isEnabled()
        _click(qtbot, wizard._apply_button)
        await wizard.wait_idle()
        # A fresh, empty game shifts nothing: «Применить» closes the wizard
        # without ever raising the report screen (spec «Пустой отчёт не плодит
        # экран»).
        await wait_for(lambda: application._calendar_wizard is None)

        rows = _settings_rows(db_path)
        assert rows[CALENDAR_SETTINGS_KEY] == encode_calendar(
            CustomCalendar(custom_spec)
        )
        assert CALENDAR_DRAFT_KEY not in rows

        # Шкала без перезапуска: the «Выбор даты» popover, opened with a real
        # island click, already speaks the new calendar; its two taps pick a
        # window and the chip re-captions live.
        timeline_probe.click_object(window, "windowChip")
        range_popup = window.timeline_widget.window_popup
        await wait_for(range_popup.isVisible)
        assert _month_combo_names(range_popup.start_calendar) == list(MONTH_NAMES)
        assert _week_name_labels(range_popup.start_calendar) == list(WEEK_NAMES)
        grid = range_popup.start_calendar
        _click(qtbot, _day_cell(grid, 5))
        _click(qtbot, _day_cell(grid, 9))
        await wait_for(lambda: not range_popup.isVisible())
        assert timeline_probe.chip_caption(window) == (
            "05 Ведодей 1 — 09 Ведодей 1 ▾"
        )
        timeline_probe.click_object(window, "windowChip")
        await wait_for(range_popup.isVisible)
        _click(qtbot, range_popup.reset_button)
        await wait_for(lambda: timeline_probe.chip_caption(window) == "Все дни ▾")
        await helpers.wait_until_settled()

        # ── C. an open-ended event ON THE INTERCALARY DAY (all clicks) ──────
        # Field entry waits until every date bound is the custom calendar's
        # own: while the dialog still carries the «сегодня» default the QML
        # `valid` chain reads an era key of a coordinate the 3-month calendar
        # does not contain, and the click-taps below fix all bounds first —
        # a real user picking dates before typing does exactly the same.
        dialog_a = await _open_event_dialog(window, wait_for)
        await _tap_qml(qtbot, dialog_a.quick, "eventStartDateField")
        popup_a = dialog_a.date_popup
        await wait_for(popup_a.isVisible)
        assert _month_combo_names(popup_a.calendar) == list(MONTH_NAMES)
        # «Ведодей» (1) ▶ «Пуровеж» (2): the chip row lives under its host.
        _step_months(qtbot, popup_a.calendar, 1)
        chip = _intercalary_chip(popup_a.calendar)
        assert chip.text() == INTERCALARY_NAME
        assert not chip.selected
        _click(qtbot, chip)
        await wait_for(lambda: not popup_a.isVisible())
        assert dialog_a.vm._start_date == INTERCALARY_DAY
        # Open-ended: the «Бессрочно» check box answers with a real QML tap.
        await _tap_qml(qtbot, dialog_a.quick, "eventNoEndCheck")
        assert dialog_a.vm._no_end
        dialog_a.name_input.setText(INTERCALARY_EVENT)
        dialog_a.characteristics_input.setContent(
            "Обряд переживает только пепел"
        )
        await wait_for(lambda: dialog_a.vm.valid)
        await _tap_qml(qtbot, dialog_a.quick, "eventSaveButton")
        await wait_for(
            lambda: helpers.has_event_named(window, INTERCALARY_EVENT)
        )
        await helpers.wait_until_settled()

        # Лента without a restart — the intercalary day names itself, with no
        # day number anywhere in the row caption (spec «Вставной день в
        # строке»).
        tape = timeline_probe.tape(window)
        row = next(r for r in tape.rows if r.name == INTERCALARY_EVENT)
        assert row.caption == f"{INTERCALARY_CAPTION} · {INTERCALARY_EVENT}"
        helpers.click_timeline_event(window, INTERCALARY_EVENT)
        await wait_for(lambda: window.detail_panel.vm.title == INTERCALARY_EVENT)
        assert window.detail_panel.vm.dateText == INTERCALARY_CAPTION

        # ── D. a BC event: grid cells + the era check box, by clicks ────────
        # Dates first, the name after — same reason as in scene C.
        dialog_b = await _open_event_dialog(window, wait_for)
        await _tap_qml(qtbot, dialog_b.quick, "eventStartDateField")
        popup_b = dialog_b.date_popup
        await wait_for(popup_b.isVisible)
        _step_months(qtbot, popup_b.calendar, 6)  # (1,1) → (3,1) «Ведодей»
        _click(qtbot, popup_b.calendar._bc_check)
        assert popup_b.calendar.is_bc()
        _click(qtbot, _day_cell(popup_b.calendar, 13))
        await wait_for(lambda: not popup_b.isVisible())
        assert dialog_b.vm._start_date == BC_START
        assert dialog_b.vm._start_bc
        # The end bound: the same popup re-opens clean (« era — чистый флаг»),
        # one month ahead, BC again, day 20 of «Пуровеж».
        await _tap_qml(qtbot, dialog_b.quick, "eventEndDateField")
        await wait_for(popup_b.isVisible)
        assert not popup_b.calendar.is_bc()
        _step_months(qtbot, popup_b.calendar, 1)  # (3,1) → (3,2)
        _click(qtbot, popup_b.calendar._bc_check)
        _click(qtbot, _day_cell(popup_b.calendar, 20))
        await wait_for(lambda: not popup_b.isVisible())
        assert dialog_b.vm._end_date == BC_END
        assert dialog_b.vm._end_bc
        dialog_b.name_input.setText(BC_EVENT)
        dialog_b.characteristics_input.setContent(
            "Сказана до первого Ведодея трёхлетки"
        )
        await wait_for(lambda: dialog_b.vm.valid)
        await _tap_qml(qtbot, dialog_b.quick, "eventSaveButton")
        await wait_for(lambda: helpers.has_event_named(window, BC_EVENT))
        await helpers.wait_until_settled()

        tape = timeline_probe.tape(window)
        row = next(r for r in tape.rows if r.name == BC_EVENT)
        assert row.caption == f"{BC_CAPTION} · {BC_EVENT}"
        helpers.click_timeline_event(window, BC_EVENT)
        await wait_for(lambda: window.detail_panel.vm.title == BC_EVENT)
        assert window.detail_panel.vm.dateText == BC_CAPTION

        # ── E. the world snapshot: intercalary name + the «г. до н.э.» suffix ─
        snapshot = window.world_snapshot
        await _tap_qml(qtbot, snapshot.quick, "snapshotDateField")
        await wait_for(snapshot.date_popup.isVisible)
        _step_months(qtbot, snapshot.date_popup.calendar, 1)  # chip on month 2
        snap_chip = _intercalary_chip(snapshot.date_popup.calendar)
        assert not snap_chip.selected  # the stored «today» is no chip
        _click(qtbot, snap_chip)
        await wait_for(lambda: not snapshot.date_popup.isVisible())
        assert snapshot.vm.dateDisplay == f"{INTERCALARY_NAME} 1"
        assert snapshot.vm.dateIso == encode_coord(INTERCALARY_DAY)
        await _tap_qml(qtbot, snapshot.quick, "snapshotShowButton")
        await helpers.wait_until_settled()
        assert snapshot.vm.statsText.startswith(f"Дата: {INTERCALARY_NAME} 1")
        assert "Событий: 1" in snapshot.vm.statsText
        snapshot.vm.toggleSection("events")  # the section starts collapsed
        event_rows = _snapshot_event_rows(snapshot)
        assert [r["displayText"] for r in event_rows] == [
            f"{INTERCALARY_CAPTION}  |  {INTERCALARY_EVENT}"
        ]

        await _tap_qml(qtbot, snapshot.quick, "snapshotDateField")
        await wait_for(snapshot.date_popup.isVisible)
        # The popup pre-fills the intercalary chip page; five ▶ reach (3,1).
        _step_months(qtbot, snapshot.date_popup.calendar, 5)
        _click(qtbot, snapshot.date_popup.calendar._bc_check)
        _click(qtbot, _day_cell(snapshot.date_popup.calendar, 13))
        await wait_for(lambda: not snapshot.date_popup.isVisible())
        assert snapshot.vm.dateDisplay == "13 Ведодей 3 г. до н.э."
        await _tap_qml(qtbot, snapshot.quick, "snapshotShowButton")
        await helpers.wait_until_settled()
        assert snapshot.vm.statsText.startswith("Дата: 13 Ведодей 3 г. до н.э.")
        assert "Событий: 1" in snapshot.vm.statsText
        event_rows = _snapshot_event_rows(snapshot)
        assert [r["displayText"] for r in event_rows] == [
            f"{BC_CAPTION}  |  {BC_EVENT}"
        ]

        # ── F. the storage side of the two clicked records ──────────────────
        cal = CustomCalendar(custom_spec)
        row_a = _event_row(db_path, INTERCALARY_EVENT)
        assert row_a[4:6] == (encode_coord(INTERCALARY_DAY), None)
        assert row_a[2:4] == (cal.to_key(INTERCALARY_DAY), None)
        assert row_a[6:8] == (0, 0)
        row_b = _event_row(db_path, BC_EVENT)
        assert row_b[4:6] == (encode_coord(BC_START), encode_coord(BC_END))
        assert row_b[2:4] == (
            cal.to_key(BC_START, True), cal.to_key(BC_END, True),
        )
        assert row_b[2] < 0 and row_b[3] < 0  # the BC half of the key scale
        assert row_b[6:8] == (1, 1)
    finally:
        # ── G. restart on the same file: captions, coords and keys identical ─
        settings_before = _settings_rows(db_path)
        stored_before = {
            name: _event_row(db_path, name)
            for name in (INTERCALARY_EVENT, BC_EVENT)
        }
        window.close()
        await helpers.wait_until_settled()
        await application.shutdown()

    window2 = await application.start(str(db_path))
    try:
        await wait_for(
            lambda: helpers.has_event_named(window2, INTERCALARY_EVENT)
            and helpers.has_event_named(window2, BC_EVENT)
        )
        await helpers.wait_until_settled()
        tape2 = timeline_probe.tape(window2)
        assert next(r for r in tape2.rows if r.name == INTERCALARY_EVENT).caption == (
            f"{INTERCALARY_CAPTION} · {INTERCALARY_EVENT}"
        )
        assert next(r for r in tape2.rows if r.name == BC_EVENT).caption == (
            f"{BC_CAPTION} · {BC_EVENT}"
        )
        assert timeline_probe.chip_caption(window2) == "Все дни ▾"

        helpers.click_timeline_event(window2, BC_EVENT)
        await wait_for(lambda: window2.detail_panel.vm.title == BC_EVENT)
        assert window2.detail_panel.vm.dateText == BC_CAPTION

        assert _settings_rows(db_path) == settings_before
        for name, stored in stored_before.items():
            assert _event_row(db_path, name) == stored
    finally:
        window2.close()
        await helpers.wait_until_settled()
        await application.shutdown()


# ── small scene-1 drivers (kept next to the test; reused later) ──────────────

def _ui_prefs(tmp_path: Path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager

    return UiPrefsManager(tmp_path / "ui.json")


def _snapshot_event_rows(snapshot) -> list[dict]:
    return [
        row
        for row in snapshot.vm._model.rows
        if row["rowKind"] == "entityRow" and row["sectionKey"] == "events"
    ]


def _event_row(db_path: Path, name: str) -> tuple:
    return query_db(
        db_path,
        f"SELECT {_EVENT_COLUMNS} FROM events WHERE name = ?",
        (name,),
    )[0]


async def _open_event_dialog(window, wait_for):
    """Real «+» island tap → the visible EventDialog with its entity loads
    drained (the race discipline of helpers.create_event_via_ui)."""
    timeline_probe.click_object(window, "addButton")
    await wait_for(
        lambda: any(d.isVisible() for d in window.findChildren(EventDialog))
    )
    dialog = next(
        d for d in window.findChildren(EventDialog) if d.isVisible()
    )
    load_done = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(load_done) == 4)
    return dialog


# ── scene 2: mid-game shorten with the transfer report (design D2) ───────────

#: Scene 2 shortens «Ледянь» from 28 to 21 days on the draft-resumed «Месяцы»
#: screen, so its days 21…28 stop existing: the two Ледянь records below are
#: the задеваемые ones (three shifted fields in total), while the record on
#: «Ведодей»/«Пуровеж» proves an untouched row stays out of the report and
#: keeps its exact bytes through the promotion.
SHORTENED_LENGTH = 21
NEW_MONTH_LENGTHS = (MONTH_LENGTHS[0], MONTH_LENGTHS[1], SHORTENED_LENGTH)
SHIFTED_RANGE_EVENT = "Засолка капусты"
SHIFTED_OPEN_EVENT = "Отлёт журавлей"
CALM_EVENT = "Тихий вечер"

RANGE_START = MonthDay(2, 3, 24)
RANGE_END = MonthDay(2, 3, 28)
OPEN_START = MonthDay(2, 3, 26)
CALM_START = MonthDay(1, 1, 5)
CALM_END = MonthDay(1, 2, 12)
CLAMPED_DAY = MonthDay(2, 3, SHORTENED_LENGTH)

_LEDYAN = MONTH_NAMES[2]
RANGE_CAPTION_OLD = f"24 {_LEDYAN} 2 — 28 {_LEDYAN} 2"
RANGE_CAPTION_NEW = f"{SHORTENED_LENGTH:02d} {_LEDYAN} 2 — {SHORTENED_LENGTH:02d} {_LEDYAN} 2"
OPEN_CAPTION_OLD = f"26 {_LEDYAN} 2 — ∞"
OPEN_CAPTION_NEW = f"{SHORTENED_LENGTH:02d} {_LEDYAN} 2 — ∞"
CALM_CAPTION = f"05 {MONTH_NAMES[0]} 1 — 12 {MONTH_NAMES[1]} 1"

#: The legacy ``start_date`` a custom-calendar row carries past the NOT NULL
#: gate on INSERT (``coord_mapping._INSERT_DATE_PLACEHOLDER``); while the
#: coordinate column holds the truth no reader ever looks at it.
_REPO_INSERT_DATE = "0001-01-01"


async def _seed_shift_scene(
    db_path: Path, calendar: CustomCalendar, draft: CalendarDraft
) -> None:
    """The mid-game state of scene 2, written straight into the seeder-made
    file — no second wizard walk anywhere (design D2):

    * the wizard draft left by a flow closed on «Месяцы» — the applied spec
      itself, so the menu wizard resumes on that screen prefilled with the
      lengths AS THEY ARE, and the test's spin edit is a user-visible
      shortening rather than a re-assembly;
    * three dated event rows the way the repositories write them on a custom
      calendar: the coordinate columns hold the truth, only the insert-date
      placeholder sits in the legacy ``start_date``, and the keys are the
      calendar's own — here, and re-derived unchanged by the open sweep.
    """
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT OR REPLACE INTO game_settings (key, value) VALUES (?, ?)",
                (CALENDAR_DRAFT_KEY, encode_draft(draft)),
            )
            for name, start, end in (
                (SHIFTED_RANGE_EVENT, RANGE_START, RANGE_END),
                (SHIFTED_OPEN_EVENT, OPEN_START, None),
                (CALM_EVENT, CALM_START, CALM_END),
            ):
                await conn.exec_driver_sql(
                    "INSERT INTO descriptions (characteristics, backstory)"
                    " VALUES (?, NULL)",
                    (f"запись срединной правки «{name}»",),
                )
                desc_id = (
                    await conn.exec_driver_sql("SELECT last_insert_rowid()")
                ).scalar()
                await conn.exec_driver_sql(
                    "INSERT INTO events (name, description_id, start_date,"
                    " end_date, start_key, end_key, start_coord, end_coord,"
                    " start_bc, end_bc)"
                    f" VALUES (?, ?, '{_REPO_INSERT_DATE}', NULL,"
                    " ?, ?, ?, ?, 0, 0)",
                    (
                        name,
                        desc_id,
                        calendar.to_key(start),
                        None if end is None else calendar.to_key(end),
                        encode_coord(start),
                        None if end is None else encode_coord(end),
                    ),
                )
    finally:
        await engine.dispose()


async def test_custom_calendar_midgame_shorten_shows_shift_report(
    qapp, llm_client, tmp_llm_config, modal_qdialog, tmp_path, qtbot,
    wait_for, custom_spec,
):
    """Spec «Правка календаря в середине игры с отчётом о переносе», design D2.

    The game opens ON the accepted custom calendar with a wizard draft parked
    on «Месяцы» (no second full wizard walk, spec «Черновик мастера»
    continuation); the menu wizard resumes there prefilled with the live
    month rows, shortening «Ледянь» 28 → 21 opens the report screen that
    lists the names of exactly the задеваемые records, «Перенести и применить»
    transfers them atomically, and the tape and the detail panel re-speak the
    clamped dates without any restart (spec «Правка… с отчётом о переносе»).
    """
    cal = CustomCalendar(custom_spec)
    db_path = tmp_path / "midgame" / "game.db"
    await seed_applied_custom_calendar(db_path, cal)
    await _seed_shift_scene(
        db_path, cal,
        CalendarDraft(spec=custom_spec, stage=DRAFT_STAGE_MONTHS),
    )

    application = Application(
        qapp,
        http=llm_client,
        # The suite's own dark theme, a mid-game open shows no first-entry modal.
        theme=ThemeRuntime(prefs=_ui_prefs(tmp_path)),
    )
    window = await application.start(str(db_path))
    try:
        # The seeded «показан» flag kept the wizard out of the boot — this is
        # an ordinary game open, the user summons the editor from the menu.
        assert not any(
            isinstance(d, CalendarWizardDialog) for d in modal_qdialog.executed
        )

        await wait_for(
            lambda: all(
                helpers.has_event_named(window, name)
                for name in (SHIFTED_RANGE_EVENT, SHIFTED_OPEN_EVENT, CALM_EVENT)
            )
        )
        await helpers.wait_until_settled()

        def captions() -> dict[str, str]:
            return {
                row.name: row.caption
                for row in timeline_probe.tape(window).rows
            }

        assert captions() == {
            SHIFTED_RANGE_EVENT: f"{RANGE_CAPTION_OLD} · {SHIFTED_RANGE_EVENT}",
            SHIFTED_OPEN_EVENT: f"{OPEN_CAPTION_OLD} · {SHIFTED_OPEN_EVENT}",
            CALM_EVENT: f"{CALM_CAPTION} · {CALM_EVENT}",
        }
        calm_before = _event_row(db_path, CALM_EVENT)

        # The detail of the both-bounds-moving record is open BEFORE the
        # application — design D11 re-speaks its header in place afterwards.
        helpers.click_timeline_event(window, SHIFTED_RANGE_EVENT)
        await wait_for(
            lambda: window.detail_panel.vm.title == SHIFTED_RANGE_EVENT
        )
        assert window.detail_panel.vm.dateText == RANGE_CAPTION_OLD

        # ── the menu wizard picks the draft up on «Месяцы» ───────────────────
        window.calendar_wizard_action.trigger()
        await wait_for(lambda: _visible_wizard(window) is not None)
        wizard = _visible_wizard(window)
        await helpers.wait_until_settled()  # the draft-continuation read finished

        state = wizard._vm.state
        assert state.kind == KIND_CUSTOM  # the menu preselects the current kind
        assert state.step == STEP_MONTHS  # …and the draft resumes the edit here
        assert [
            (name_edit.text(), length_spin.value())
            for name_edit, length_spin in wizard._month_rows
        ] == list(zip(MONTH_NAMES, MONTH_LENGTHS))
        assert [edit.text() for edit in wizard._week_fields] == list(WEEK_NAMES)
        assert wizard._rule_rows[0][0].text() == (
            f"{INTERCALARY_NAME} → {MONTH_NAMES[1]}"
        )
        assert _month_combo_names(wizard._preview) == list(MONTH_NAMES)

        # The shortening itself: «Ледянь» 28 → 21 on the row the draft grew —
        # every Ледянь day past 21 now refuses to exist in the applied calendar.
        length_spin = wizard._month_rows[2][1]
        assert length_spin.value() == MONTH_LENGTHS[2]
        length_spin.setValue(SHORTENED_LENGTH)
        assert wizard._vm.state.can_advance  # shorter, yet still a valid spec

        _click(qtbot, wizard._next_button)
        await wizard.wait_idle()  # → «Вставные дни», host «Пуровеж» intact
        _click(qtbot, wizard._next_button)
        await wizard.wait_idle()  # → «Предпросмотр»
        assert wizard._apply_button.isEnabled()

        # «Применить» = the dry run: the report page lists exactly the three
        # задеваемые fields, old dates in the still-active calendar, new ones
        # in the calendar being applied (design D10 captions).
        _click(qtbot, wizard._apply_button)
        await wizard.wait_idle()
        assert wizard._stack.currentWidget() is wizard._pages[STEP_REPORT]
        assert {
            tuple(
                wizard._report_table.item(row, column).text()
                for column in range(4)
            )
            for row in range(wizard._report_table.rowCount())
        } == {
            (SHIFTED_RANGE_EVENT, "начало", f"24 {_LEDYAN} 2",
             f"{SHORTENED_LENGTH} {_LEDYAN} 2"),
            (SHIFTED_RANGE_EVENT, "конец", f"28 {_LEDYAN} 2",
             f"{SHORTENED_LENGTH} {_LEDYAN} 2"),
            (SHIFTED_OPEN_EVENT, "начало", f"26 {_LEDYAN} 2",
             f"{SHORTENED_LENGTH} {_LEDYAN} 2"),
        }
        assert wizard._report_hint.text() == (
            "Новый календарь сдвигает дату в 3 полях записей:"
        )
        # …while the check itself changed nothing: the main key and the
        # untouched record's storage are still their pre-wizard bytes.
        assert _settings_rows(db_path)[CALENDAR_SETTINGS_KEY] == (
            encode_calendar(cal)
        )
        assert _event_row(db_path, CALM_EVENT) == calm_before

        # «Перенести и применить» — the one atomic promote (design D9).
        _click(qtbot, wizard._transfer_apply_button)
        await wizard.wait_idle()
        await wait_for(lambda: application._calendar_wizard is None)
        await helpers.wait_until_settled()  # the D11 reload task finished

        # Лента without a restart: clamped dates for the задеваемые, the record
        # on untouched months re-spoken exactly as before.
        await wait_for(
            lambda: captions().get(SHIFTED_RANGE_EVENT)
            == f"{RANGE_CAPTION_NEW} · {SHIFTED_RANGE_EVENT}"
        )
        assert captions() == {
            SHIFTED_RANGE_EVENT: f"{RANGE_CAPTION_NEW} · {SHIFTED_RANGE_EVENT}",
            SHIFTED_OPEN_EVENT: f"{OPEN_CAPTION_NEW} · {SHIFTED_OPEN_EVENT}",
            CALM_EVENT: f"{CALM_CAPTION} · {CALM_EVENT}",
        }
        # Detailная: the panel that stayed open rebuilt with the clamped pair…
        assert window.detail_panel.vm.title == SHIFTED_RANGE_EVENT
        assert window.detail_panel.vm.dateText == RANGE_CAPTION_NEW
        # …and freshly clicking the open-ended record shows its new half-window.
        helpers.click_timeline_event(window, SHIFTED_OPEN_EVENT)
        await wait_for(
            lambda: window.detail_panel.vm.title == SHIFTED_OPEN_EVENT
        )
        assert window.detail_panel.vm.dateText == OPEN_CAPTION_NEW

        # The storage side of the transfer: coordinate columns clamped and
        # keyed by the APPLIED calendar, the draft consumed by the promote,
        # the untouched row byte-identical (its months 1–2 kept their lengths).
        shortened = CustomCalendar(CalendarSpec(
            months=tuple(
                MonthSpec(name, length)
                for name, length in zip(MONTH_NAMES, NEW_MONTH_LENGTHS)
            ),
            week_names=custom_spec.week_names,
            intercalary=custom_spec.intercalary,
        ))
        clamped_text = encode_coord(CLAMPED_DAY)
        row_range = _event_row(db_path, SHIFTED_RANGE_EVENT)
        assert row_range[2:4] == (shortened.to_key(CLAMPED_DAY),) * 2
        assert row_range[4:6] == (clamped_text, clamped_text)
        row_open = _event_row(db_path, SHIFTED_OPEN_EVENT)
        assert row_open[2:4] == (shortened.to_key(CLAMPED_DAY), None)
        assert row_open[4:6] == (clamped_text, None)
        assert _event_row(db_path, CALM_EVENT) == calm_before

        rows = _settings_rows(db_path)
        assert rows[CALENDAR_SETTINGS_KEY] == encode_calendar(shortened)
        assert CALENDAR_DRAFT_KEY not in rows  # the promote consumed the draft
        assert rows[CALENDAR_WIZARD_SEEN_KEY] == "1"  # a menu entry is no first entry
    finally:
        window.close()
        await helpers.wait_until_settled()
        await application.shutdown()
