"""E2E entry points and propagation of the calendar wizard (piece C4, task group 7).

Spec calendar-wizard «Точки входа мастера» / «Первый вход новой игры» /
«Распространение применённого календаря» and spec game-calendar-settings
«Флаг просмотра мастера календаря», driven through the real ``Application``:

* 7.1 — «Настройки → Календарь…» opens the wizard over the main window in
  both games (preset and custom), preselecting the CURRENT calendar key's
  kind and never touching the «seen» flag (an old game stays an old game);
* 7.2 — a freshly seeded game gets the wizard prefilled «Стандартный»; since
  W3/NRI-0015 (task 2.4) it opens deferred OVER THE SHOWN WINDOW (no nested
  exec inside ``Application.start()``); closing without a draft applies the
  preset and writes «показан» once; a live draft keeps the flag at «не
  показан» so the next open calls the wizard back as a flow continuation —
  driven off the live ``Application._calendar_wizard`` reference, pumped by
  the ``wait_for`` fixture;
* 7.3 (design D11) — after a menu application the feed, the «Выбор даты»
  chip and the open detail panel re-speak the new calendar without a
  restart, and the range popup's grids re-read it at their next opening.

The boot fixtures never see a wizard ``exec`` — the first-entry wizard is a
deferred top-level (task 2.4); the shared ``app`` fixture dismisses it after
boot, the 7.2 tests drive the live dialog instance itself.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QSize

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    MonthSpec,
    StandardCalendar,
    current_calendar,
)
from app.infrastructure.calendar_storage import (
    CalendarDraft,
    DRAFT_STAGE_MONTHS,
    encode_calendar,
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
from app.presentation.viewmodels.calendar_wizard_viewmodel import (
    KIND_CUSTOM,
    KIND_STANDARD,
    STEP_CHOICE,
    STEP_MONTHS,
    STEP_REPORT,
)
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from app.presentation.views.main_window import MainWindow

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

#: Three 3-day months — month 1 renames every still-existing coordinate, a
#: Gregorian February 5 cannot survive and lands on the day 3 of month 2,
#: so each D11 surface gets its own provably-new month name.
CUSTOM_MONTHS = ("Светопрел", "Тьмопрест", "Хмарь")


def _settings_rows(db_path: Path) -> dict[str, str]:
    return dict(query_db(db_path, "SELECT key, value FROM game_settings"))


def _visible_wizard(window: MainWindow) -> CalendarWizardDialog | None:
    """The wizard the menu entry opened over the main window, if any."""
    for dialog in window.findChildren(CalendarWizardDialog):
        if dialog.isVisible():
            return dialog
    return None


def _mark_as_pre_c4_game(db_path: Path) -> None:
    """An existing ``game_settings`` table marks the file as created BEFORE
    the C4 seeding (exact ui-suite convention of the calendar lifecycle
    suite) — init_db then opens it as an old, keyless game."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE game_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
    )
    conn.commit()
    conn.close()


async def _make_old_custom_game(db_path: Path) -> None:
    """A pre-C4 game whose ``game_calendar`` holds a full custom spec — the
    C4-era state a custom game has when the user reaches the menu entry."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    (db_path.parent / "images").mkdir(exist_ok=True)
    _mark_as_pre_c4_game(db_path)
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO game_settings (key, value) VALUES (?, ?)",
                (
                    CALENDAR_SETTINGS_KEY,
                    encode_calendar(
                        CustomCalendar(
                            CalendarSpec(
                                months=tuple(MonthSpec(name, 30) for name in CUSTOM_MONTHS),
                                week_names=(
                                    "Буд", "Ведь", "Творец",
                                    "Грозник", "Светлай", "Прочь", "Хмарник",
                                ),
                            )
                        )
                    ),
                ),
            )
    finally:
        await engine.dispose()


# ── 7.1: «Настройки → Календарь…» in both games, flag untouched ─────────────


async def test_menu_entry_preselects_preset_and_leaves_seen_flag(app, wait_for):
    """Preset game: the wizard opens modally over the window, preselecting
    the standard kind; neither the flag nor the calendar change from here."""
    application, window = app
    db_path = Path(application._db_path)
    # The fresh game ran its first entry during boot (the close semantics):
    # the flag reads «показан» before the menu was ever touched.
    assert _settings_rows(db_path)[CALENDAR_WIZARD_SEEN_KEY] == "1"

    window.calendar_wizard_action.trigger()
    await wait_for(lambda: _visible_wizard(window) is not None)
    wizard = _visible_wizard(window)
    assert wizard.parent() is window  # «поверх главного окна»
    await helpers.wait_until_settled()  # the draft-continuation read finished

    state = wizard._vm.state
    assert state.kind == KIND_STANDARD  # preselection of the CURRENT key
    assert state.step == STEP_CHOICE
    assert wizard._standard_radio.isChecked()

    # A second trigger reuses the wizard that is already open (no second
    # modal is stacked over the same game).
    window.calendar_wizard_action.trigger()
    assert len(window.findChildren(CalendarWizardDialog)) == 1
    assert _visible_wizard(window) is wizard

    # Spec «Флаг просмотра мастера календаря»: the menu entry is not a first
    # entry — it neither reads nor writes the flag, before or after closing.
    wizard.reject()
    await wait_for(lambda: application._calendar_wizard is None)
    assert _settings_rows(db_path)[CALENDAR_WIZARD_SEEN_KEY] == "1"
    assert CALENDAR_DRAFT_KEY not in _settings_rows(db_path)


async def test_menu_entry_preselects_custom_and_old_game_stays_old(
    qapp, llm_client, tmp_llm_config, modal_qdialog, tmp_path, wait_for
):
    """Custom game created before the wizard existed: never an auto-show,
    the menu preselects «Кастомный» and the flag key never appears."""
    db_path = tmp_path / "Custom" / "game.db"
    await _make_old_custom_game(db_path)

    application = Application(qapp, http=llm_client)
    execs_before_open = len(modal_qdialog.executed)
    window = await application.start(str(db_path))
    try:
        # Scenario «Старая игра не видит мастера» — the open showed no wizard.
        booted = modal_qdialog.executed[execs_before_open:]
        assert not any(isinstance(d, CalendarWizardDialog) for d in booted)

        window.calendar_wizard_action.trigger()
        await wait_for(lambda: _visible_wizard(window) is not None)
        wizard = _visible_wizard(window)
        await helpers.wait_until_settled()

        state = wizard._vm.state
        assert state.kind == KIND_CUSTOM  # preselects the current key's kind
        assert isinstance(state.preview_calendar, CustomCalendar)
        assert wizard._custom_radio.isChecked()
        wizard.reject()
        await wait_for(lambda: application._calendar_wizard is None)
    finally:
        window.close()
        await application.shutdown()

    # Using the menu did not make this an automatic-wizard game anywhere:
    # the flag key is still absent, before AND after a second regular open.
    assert CALENDAR_WIZARD_SEEN_KEY not in _settings_rows(db_path)
    execs_before_reopen = len(modal_qdialog.executed)
    window2 = await application.start(str(db_path))
    try:
        reopened = modal_qdialog.executed[execs_before_reopen:]
        assert not any(isinstance(d, CalendarWizardDialog) for d in reopened)
    finally:
        window2.close()
        await application.shutdown()
    assert CALENDAR_WIZARD_SEEN_KEY not in _settings_rows(db_path)


# ── NRI-0014 5.2: the menu wizard's window format (D6) ───────────────────────


async def test_menu_wizard_is_application_modal_without_parent_geometry_jump(
    app, wait_for
):
    """The «Календарь…» wizard is its own application-modal top-level, not a
    parent-attached sheet (spec qml-shell «Формат диалогов задан точкой
    входа»: the entry is modal; design D5/D6): ``open()`` under the parent set
    WindowModal and macOS drew it as a title-less sheet attached to the main
    window — wider than the window, moving it on open and back on close (D6).
    The format check: ``windowModality()`` is ApplicationModal, and the main
    window's geometry does not budge while the wider wizard is open."""
    application, window = app
    window.setGeometry(140, 120, 1100, 700)
    await helpers.wait_until_settled()
    geometry_before = window.geometry()

    window.calendar_wizard_action.trigger()
    await wait_for(lambda: _visible_wizard(window) is not None)
    wizard = _visible_wizard(window)
    await helpers.wait_until_settled()

    assert wizard.windowModality() == Qt.WindowModality.ApplicationModal
    assert wizard.isModal()
    # An own window, not an attached sheet: the wizard itself is its window.
    assert wizard.window() is wizard
    # D6: opening something wider than the parent must not shove the parent.
    assert window.geometry() == geometry_before

    wizard.reject()
    await wait_for(lambda: application._calendar_wizard is None)
    assert window.geometry() == geometry_before


# ── 7.2: first entry of a newly created game ────────────────────────────────


async def test_first_entry_close_applies_preset_and_marks_seen_once(
    qapp, llm_client, tmp_llm_config, tmp_path, wait_for
):
    """Scenarios «Крест = Стандартный» and «Вход из меню доступен всегда»'s
    flag twin on the W3 contour (task 2.4): start() completes and the window
    shows FIRST, prefilled «Стандартный» wizard opens over it deferred;
    closing it applies the preset, writes «показан» — and the next open gets
    no wizard at all."""
    db_path = tmp_path / "New" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()

    application = Application(qapp, http=llm_client)
    window = await application.start(str(db_path))
    # The window proper is what start() handed over; the wizard is not even
    # constructed yet — no nested modal loop wrapped the startup coroutine.
    assert window.isVisible()
    assert application._calendar_wizard is None
    try:
        await wait_for(lambda: application._calendar_wizard is not None)
        wizard = application._calendar_wizard
        await helpers.wait_until_settled()  # the prefilled draft read done
        state = wizard._vm.state
        assert state.kind == KIND_STANDARD
        assert state.step == STEP_CHOICE

        # The close the cross button gives: preset applies, «показан» flips.
        wizard.reject()
        await helpers.wait_until_settled()  # the service close step committed
    finally:
        window.close()
        await application.shutdown()

    rows = _settings_rows(db_path)
    assert rows[CALENDAR_WIZARD_SEEN_KEY] == "1"  # «показан»
    assert rows[CALENDAR_SETTINGS_KEY] == encode_calendar(StandardCalendar())
    assert CALENDAR_DRAFT_KEY not in rows

    # Next opening of the same game: no wizard until someone summons it —
    # the deferred hook takes its turn and steps past the shown flag.
    window2 = await application.start(str(db_path))
    try:
        await asyncio.sleep(0)  # the loop turn the deferred call needed
        assert application._calendar_wizard is None
    finally:
        window2.close()
        await application.shutdown()


async def test_abandoned_draft_calls_the_wizard_back(
    qapp, llm_client, tmp_llm_config, tmp_path, wait_for
):
    """Scenario «Брошенный черновик зовёт обратно» on the W3 contour: a draft
    wizard closed without applying keeps the flag at «не показан», the game
    lives on the preset the whole time, and every following open resumes the
    deferred wizard at the saved stage with the saved week."""
    db_path = tmp_path / "Drafty" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    # The game was created by this version (init_db seeds the two keys), a
    # week stage was completed, and the wizard closed on «Месяцы» — the
    # draft row is exactly what that close left behind.
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        draft = CalendarDraft(
            spec=CalendarSpec(
                months=tuple(MonthSpec(name, 30) for name in CUSTOM_MONTHS),
                week_names=("Понедельник", "Вторник", "Среда"),
            ),
            stage=DRAFT_STAGE_MONTHS,
        )
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO game_settings (key, value) VALUES (?, ?)",
                (CALENDAR_DRAFT_KEY, encode_draft(draft)),
            )
    finally:
        await engine.dispose()

    application = Application(qapp, http=llm_client)

    async def _boot_resume_and_close() -> dict:
        """One open: the deferred wizard resumes on the draft and is then
        closed the way the cross does — draft left behind, flag untouched."""
        window = await application.start(str(db_path))
        try:
            await wait_for(lambda: application._calendar_wizard is not None)
            wizard = application._calendar_wizard
            await helpers.wait_until_settled()
            state = wizard._vm.state
            resumed = {
                "kind": state.kind,
                "step": state.step,
                "week": tuple(state.week_names),
            }
            # The draft-wizard opens over the window and lives on the preset —
            # the game itself was never moved.
            assert isinstance(current_calendar(), StandardCalendar)
            wizard.reject()
            await helpers.wait_until_settled()  # service close step done
            return resumed
        finally:
            window.close()
            await application.shutdown()

    resumption = await _boot_resume_and_close()
    # Continuation, not a restart: the saved stage, prefilled by the draft.
    assert resumption == {
        "kind": KIND_CUSTOM,
        "step": STEP_MONTHS,
        "week": ("Понедельник", "Вторник", "Среда"),
    }

    rows = _settings_rows(db_path)
    assert rows[CALENDAR_WIZARD_SEEN_KEY] == "0"  # flag NOT set (spec)
    assert CALENDAR_DRAFT_KEY in rows  # draft survived for the next open
    assert rows[CALENDAR_SETTINGS_KEY] == encode_calendar(StandardCalendar())

    # Reopen: the wizard calls the player back — same stage, same week, and
    # the flag still refuses to flip while the draft lives.
    reopening = await _boot_resume_and_close()
    assert reopening == resumption
    assert _settings_rows(db_path)[CALENDAR_WIZARD_SEEN_KEY] == "0"


# ── 7.3: propagation of an applied calendar (design D11) ────────────────────


async def test_applied_calendar_repaints_feed_chip_detail_and_popup(
    app, wait_for
):
    """Scenario «Таймлайн за календарь-секунду» + the detail/table rebuild:
    applying a custom calendar through the menu re-speaks the feed, the chip
    and the OPEN detail panel without a restart; the range popup's grids
    read the new calendar at their next opening."""
    application, window = app

    # January 2020-01-02 survives the 3-day first month untouched (the FEED
    # name change must come from the calendar, not a shifted date); the Feb
    # 5 end cannot exist and clamps to 03 of the renamed second month.
    await helpers.create_event_via_ui(
        window, wait_for, "Парад Теней",
        start_date=date(1200, 1, 2), end_date=date(1200, 2, 5),
    )
    helpers.click_timeline_event(window, "Парад Теней")
    await wait_for(lambda: "02 Январь" in window.detail_panel.vm.dateText)
    window.timeline_widget.window_changed.emit(
        date(1200, 1, 1), date(1200, 1, 3)
    )
    await helpers.wait_until_settled()
    assert "Январь" in timeline_probe.chip_caption(window)

    # The menu wizard, walked like a user: custom → default week → 3×3-day
    # months → no intercalary days → preview → apply → transfer report.
    window.calendar_wizard_action.trigger()
    await wait_for(lambda: _visible_wizard(window) is not None)
    wizard = _visible_wizard(window)
    await helpers.wait_until_settled()

    wizard._custom_radio.click()
    wizard._next_button.click()
    await wizard.wait_idle()  # → «Неделя» on the valid defaults
    wizard._next_button.click()
    await wizard.wait_idle()  # → «Месяцы»
    wizard._month_count_spin.setValue(3)
    for index, (name, length) in enumerate(
        ((name, 3) for name in CUSTOM_MONTHS)
    ):
        name_edit, length_spin = wizard._month_rows[index]
        name_edit.setText(name)
        length_spin.setValue(length)
    wizard._next_button.click()
    await wizard.wait_idle()  # → «Вставные дни» (empty list is valid)
    wizard._next_button.click()
    await wizard.wait_idle()  # → «Предпросмотр»

    assert wizard._apply_button.isEnabled()
    wizard._apply_button.click()
    await wizard.wait_idle()
    assert wizard._stack.currentWidget() is wizard._pages[STEP_REPORT]
    report = [
        [wizard._report_table.item(row, column).text() for column in range(4)]
        for row in range(wizard._report_table.rowCount())
    ]
    assert any(
        line[0] == "Парад Теней"
        and line[1] == "конец"
        and line[2] == "05 Февраль 1200"
        and line[3] == "03 Тьмопрест 1200"
        for line in report
    )

    wizard._transfer_apply_button.click()
    await wizard.wait_idle()
    # The success closes the modal and the wiring forgets it.
    await wait_for(lambda: application._calendar_wizard is None)
    await helpers.wait_until_settled()  # the D11 reload task finished

    # Feed: the untouched coordinate reads with the NEW month name.
    canvas = timeline_probe.tape(window)
    await wait_for(
        lambda: any(
            "02 Светопрел 1200" in row.caption for row in canvas.rows
        )
    )
    # Chip: the active window re-captioned through the active calendar.
    assert "Светопрел" in timeline_probe.chip_caption(window)
    # Detail panel (open since the click): rebuilt with the shifted end.
    assert "03 Тьмопрест 1200" in window.detail_panel.vm.dateText

    # Reopening the range popup shows the NEW calendar's month pages.
    popup = window.timeline_widget.window_popup
    popup.open_at(QRect(QPoint(200, 200), QSize(20, 20)))
    combo = popup.start_calendar._month_combo
    assert [combo.itemText(i) for i in range(combo.count())] == list(CUSTOM_MONTHS)
    popup.close()

    # Storage side: the applied spec, no draft, and — menu applications do
    # not close a first entry — the flag text stays exactly as it was.
    rows = _settings_rows(Path(application._db_path))
    assert "Светопрел" in rows[CALENDAR_SETTINGS_KEY]
    assert CALENDAR_DRAFT_KEY not in rows
    assert rows[CALENDAR_WIZARD_SEEN_KEY] == "1"

    # The D11 chain also reaches an OPEN table host panel, and a calendar
    # that shifts nothing skips the report screen outright (spec «Пустой
    # отчёт не плодит экран» — instant close on «Применить»).
    window.table_host_action.trigger()
    assert application._table_host_panel is not None

    window.calendar_wizard_action.trigger()
    await wait_for(lambda: _visible_wizard(window) is not None)
    wizard = _visible_wizard(window)
    await helpers.wait_until_settled()
    # The key changed, so this wizard preselects the OTHER kind already.
    assert wizard._vm.state.kind == KIND_CUSTOM

    wizard._next_button.click()
    await wizard.wait_idle()  # → «Неделя» (custom flow opened on the defaults)
    wizard._next_button.click()
    await wizard.wait_idle()  # → «Месяцы»
    wizard._month_count_spin.setValue(3)
    for index, (name, length) in enumerate((
        (name, 3) for name in CUSTOM_MONTHS
    )):
        name_edit, length_spin = wizard._month_rows[index]
        name_edit.setText(name)
        length_spin.setValue(length)
    wizard._next_button.click()
    await wizard.wait_idle()  # → «Вставные дни»
    wizard._next_button.click()
    await wizard.wait_idle()  # → «Предпросмотр»
    wizard._apply_button.click()
    await wizard.wait_idle()

    # No shifts were found: the dialog closed without ever showing the
    # report page, and the reload ran over the panel too.
    assert application._calendar_wizard is None
    assert wizard._stack.currentWidget() is not wizard._pages[STEP_REPORT]
    await helpers.wait_until_settled()
    assert any(
        "02 Светопрел 1200" in row.caption for row in timeline_probe.rows(window)
    )

    # A wizard still OPEN when the game closes must not outlive its session —
    # teardown (shutdown) closes it; triggering it once more proves it is the
    # live one and the app survives going down with it.
    window.calendar_wizard_action.trigger()
    await wait_for(lambda: _visible_wizard(window) is not None)


# ── Defensive guards around the entry (zero-state application) ────────────────


async def test_wizard_entry_and_reload_are_noop_before_any_session(
    qapp, llm_client, tmp_llm_config
):
    """The menu signal and the D11 reload are wired into live signals, but
    both first check the zero state: with no session yet the entry builds no
    wizard and touches nothing; with no window yet the reload returns
    instead of dereferencing absent surfaces."""
    application = Application(qapp, http=llm_client)
    application._on_calendar_wizard()  # no service/session: no-op
    assert application._calendar_wizard is None
    await application._reload_after_calendar_change()  # no window: no-op
