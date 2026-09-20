"""Piece C3a, task 6.2: the standard game must not notice coordinate storage.

Automated stand-in for the manual acceptance check (the interactive desktop
session itself is not available in CI, so this suite drives the SAME flows
through the REAL application — offscreen, but through real dialogs, real
ViewModel/wiring and a real SQLite file):

* creation and editing of records (event dialog create → edit, entity card
  create → link → edit) leave the standard game in its pre-C3a shape: plain
  ISO dates in the legacy date columns, chronological keys equal to the
  pre-dispatch preset numbers (the AD ordinal), and every coordinate column
  of all six dated tables still NULL (spec «Стандартная игра не видит нового
  хранилища»);
* the captions are the pre-C3a strings bit-for-bit: timeline row captions
  («дд Месяц год — ... · имя», the ``∞`` of the open-ended row), the detail
  header, the «Выбор даты» chip after two taps in the window popup, and the
  world snapshot stats/rows («Дата: дд Месяц год», the «all events» mode);
* opening the same game file twice changes nothing in it (spec «Идемпотентный
  старт»): after a full open → data → close → open → close cycle the database
  dump AND the file bytes are identical to the state after the first open —
  the startup sweep is a no-op on a standard calendar, so no rows, keys or
  settings are touched.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from PySide6.QtCore import QDate

from app.main import Application
from app.presentation.theme import ThemeRuntime
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

#: The six dated tables migrated with start_coord/end_coord in C3a.
ERA_TABLES = ("events", "organizations", "characters", "items", "locations", "ratings")


def _db_dump(db_path) -> str:
    """The logical content of the whole database (stable table/row order)."""
    conn = sqlite3.connect(str(db_path))
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def _assert_no_coordinates_stored(db_path) -> None:
    """Every row of every dated table lives in the legacy date columns."""
    for table in ERA_TABLES:
        stored = query_db(
            db_path,
            f"SELECT COUNT(*) FROM {table}"
            " WHERE start_coord IS NOT NULL OR end_coord IS NOT NULL",
        )[0][0]
        assert stored == 0, f"{table}: coordinate columns are not empty"


async def test_standard_game_behaves_and_captions_as_before_c3a(
    app, wait_for, menu_qmenu, modal_qdialog
):
    application, window = app
    db_path = application._db_path

    # ── 1. Creation through the event dialog (date proxies take coordinates,
    # a plain date is the same-numbers MonthDay — design D4). ──
    await helpers.create_event_via_ui(
        window, wait_for, "Долгая зима",
        start_date=date(1200, 3, 3), end_date=date(1200, 3, 10),
    )
    await helpers.create_event_via_ui(
        window, wait_for, "Открытая граница",
        start_date=date(1200, 6, 1), open_ended=True,
    )
    await helpers.create_event_via_ui(
        window, wait_for, "До зимы",
        start_date=date(1200, 2, 1), end_date=date(1200, 2, 2),
    )
    await helpers.wait_until_settled()

    # ── 2. Timeline captions are the pre-C3a strings (spec «Год до нашей
    # эры в строке»/flat list acceptance formats, here: the AD preset). ──
    tape = timeline_probe.tape(window)
    winter_id = helpers.find_event_id(window, "Долгая зима")
    assert tape.rows[tape.index_for_event(winter_id)].caption == (
        "03 Март 1200 — 10 Март 1200 · Долгая зима"
    )
    open_id = helpers.find_event_id(window, "Открытая граница")
    assert tape.rows[tape.index_for_event(open_id)].caption == (
        "01 Июнь 1200 — ∞ · Открытая граница"
    )

    # ── 3. Detail panel header line (the same caption format). ──
    helpers.click_timeline_event(window, "Долгая зима")
    await wait_for(lambda: window.detail_panel.vm.title == "Долгая зима")
    assert window.detail_panel.vm.dateText == "03 Март 1200 — 10 Март 1200"

    # ── 4. Editing through the same dialog: only legacy columns move, the
    # keys stay the plain preset numbers, coordinates stay NULL. ──
    helpers.double_click_timeline_event(window, "Долгая зима")
    await wait_for(lambda: [d for d in window.findChildren(EventDialog) if d.isVisible()])
    edit_dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    assert edit_dialog.windowTitle() == "Редактировать событие"
    edit_dialog.end_date_input.setDate(date(1200, 3, 20))
    edit_dialog.save_button.click()
    await wait_for(lambda: query_db(
        db_path, "SELECT COUNT(*) FROM events WHERE name = ? AND end_date = ?",
        ("Долгая зима", "1200-03-20"),
    )[0][0] == 1)
    await helpers.wait_until_settled()
    row = query_db(
        db_path,
        "SELECT start_date, end_date, start_key, end_key, start_coord, end_coord"
        " FROM events WHERE name = 'Долгая зима'",
    )[0]
    assert row[:4] == (
        "1200-03-03", "1200-03-20",
        date(1200, 3, 3).toordinal(), date(1200, 3, 20).toordinal(),
    )
    assert row[4:] == (None, None)
    tape = timeline_probe.tape(window)
    assert tape.rows[tape.index_for_event(winter_id)].caption == (
        "03 Март 1200 — 20 Март 1200 · Долгая зима"
    )

    # ── 5. Entity: create via the «+» menu, link to the edited event,
    # edit through the detail panel card. ──
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "Генерал Вард",
        characteristics="Опытный стратег",
    )
    char_table = helpers.ENTITY_TABLES["character"]
    await wait_for(lambda: query_db(
        db_path, "SELECT COUNT(*) FROM characters WHERE name = 'Генерал Вард'",
    )[0][0] == 1)
    await helpers.wait_until_settled()
    char_id = query_db(
        db_path, "SELECT id FROM characters WHERE name = 'Генерал Вард'",
    )[0][0]

    # (Edit-dialog opens after the previous flows have already pumped the
    # available-entity loads of this dialog class — same driver sequence as
    # test_e2e_crud, where the picker is populated by exec time.)
    helpers.double_click_timeline_event(window, "Долгая зима")
    await wait_for(lambda: [d for d in window.findChildren(EventDialog) if d.isVisible()])
    link_dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    await helpers.link_existing_entity_in_tab(
        modal_qdialog, link_dialog.char_tab, "Генерал Вард",
    )
    await wait_for(lambda: any(
        "Генерал Вард" in link_dialog.char_tab.list_widget.item(i).text()
        for i in range(link_dialog.char_tab.list_widget.count())
    ))
    link_dialog.save_button.click()
    await wait_for(lambda: query_db(
        db_path, "SELECT COUNT(*) FROM event_character WHERE character_id = ?",
        (char_id,),
    )[0][0] == 1)
    await helpers.wait_until_settled()

    helpers.click_timeline_event(window, "Долгая зима")
    characters_model = window.detail_panel.vm.characters
    await wait_for(lambda: "Генерал Вард" in helpers.detail_panel_names(characters_model))
    window.detail_panel.vm.activate(
        "character", helpers.detail_panel_entity_id(characters_model, "Генерал Вард"),
    )
    await wait_for(lambda: [
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == "Генерал Вард"
    ])
    card = next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == "Генерал Вард"
    )
    card.name_input.setText("Генерал Старый Вард")
    card.save_button.click()
    await wait_for(lambda: query_db(
        db_path, "SELECT COUNT(*) FROM characters WHERE name = 'Генерал Старый Вард'",
    )[0][0] == 1)
    await helpers.wait_until_settled()
    assert char_table  # the entity table the flows above wrote through

    # ── 6. The whole database is still a pre-C3a standard database: empty
    # coordinate columns everywhere, preset keys, ISO legacy columns. ──
    # The card VM pre-fills both bounds with «today, н.э.» (unchanged default,
    # design D4: a plain date is the equal month-day coordinate) — in a
    # standard game it lands in the legacy columns as today's ISO + ordinal.
    today = date.today()
    assert query_db(
        db_path,
        "SELECT start_date, end_date, start_key, end_key, start_coord, end_coord"
        " FROM characters WHERE name = 'Генерал Старый Вард'",
    )[0] == (
        today.isoformat(), today.isoformat(),
        today.toordinal(), today.toordinal(),
        None, None,
    )
    _assert_no_coordinates_stored(db_path)
    winter_keys = query_db(
        db_path,
        "SELECT start_key, end_key FROM events WHERE name = 'Открытая граница'",
    )[0]
    assert winter_keys[0] == date(1200, 6, 1).toordinal()  # open end: no key

    # ── 7. «Выбор даты»: the chip opens the popup, two taps filter by the
    # intersection rule, the chip caption is the standard caption. ──
    timeline_probe.click_object(window, "windowChip")
    popup = window.timeline_widget.window_popup
    await wait_for(lambda: popup.isVisible())
    popup.start_calendar.clicked.emit(QDate(1200, 3, 5))
    popup.start_calendar.clicked.emit(QDate(1200, 3, 25))
    await helpers.wait_until_settled()
    assert timeline_probe.chip_caption(window) == "05 Март 1200 — 25 Март 1200 ▾"
    # Intersection rule: «До зимы» closed before the window, the open-ended
    # event starts after it — only the crossing winter event stays visible.
    assert {event.name for event in timeline_probe.tape(window).events} == {
        "Долгая зима",
    }
    popup.reset_button.click()
    await helpers.wait_until_settled()
    assert timeline_probe.chip_caption(window) == "Все дни ▾"

    # ── 8. World snapshot through the REAL bridge: the ViewModel answers
    # with a (coordinate, era) pair, the wiring keys the query and the
    # panel paints the pre-C3a captions. ──
    snapshot_vm = window.world_snapshot.vm
    assert snapshot_vm.dateIso == date.today().isoformat()  # «today» default
    snapshot_vm.set_date(date(1200, 3, 15))
    snapshot_vm.requestShow()
    await helpers.wait_until_settled()
    assert snapshot_vm.dateDisplay == "15 Март 1200"
    assert snapshot_vm.dateIso == "1200-03-15"
    assert "Дата: 15 Март 1200" in snapshot_vm.statsText
    assert "Событий: 1" in snapshot_vm.statsText
    snapshot_vm.toggleSection("events")  # the events section starts collapsed
    event_rows = [
        row for row in snapshot_vm._model.rows
        if row["rowKind"] == "entityRow" and row["sectionKey"] == "events"
    ]
    assert [row["displayText"] for row in event_rows] == [
        "03 Март 1200 — 20 Март 1200  |  Долгая зима"
    ]
    snapshot_vm.requestShowAll()
    await helpers.wait_until_settled()
    assert snapshot_vm.statsText.startswith("Показано: все события")

    # The last flows changed no storage shape either (window/snapshot are
    # read-only for the database).
    _assert_no_coordinates_stored(db_path)


async def test_standard_game_two_opens_leave_database_identical(
    qapp, llm_client, tmp_games_dir, tmp_llm_config, wait_for, tmp_path
):
    """Task 6.2 storage half: «база после двух открытий побитово идентична».

    Same lifecycle pattern as the C2 lifecycle suite: one Application, two
    ``start``/``shutdown`` generations over the same game file, real
    ``init_db`` + C3a startup sweep on the second open.
    """
    from app.infrastructure.ui_prefs.config import UiPrefsManager

    db_path = tmp_path / "twice" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    theme = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"))
    application = Application(qapp, http=llm_client, theme=theme)

    window = await application.start(str(db_path))
    try:
        await helpers.create_event_via_ui(
            window, wait_for, "Двойное открытие",
            start_date=date(1300, 4, 1), end_date=date(1300, 4, 2),
        )
        await helpers.wait_until_settled()
    finally:
        window.close()
    await application.shutdown()
    dump_after_first = _db_dump(db_path)
    bytes_after_first = db_path.read_bytes()

    window2 = await application.start(str(db_path))
    try:
        # The second open loaded the data back — the sweep has run by now.
        await wait_for(lambda: helpers.has_event_named(window2, "Двойное открытие"))
        await helpers.wait_until_settled()
    finally:
        window2.close()
    await application.shutdown()

    assert _db_dump(db_path) == dump_after_first
    # Not one write transaction happened in the second open: same bytes too
    # (rollback-journal mode, SQLite leaves a read-only file untouched).
    assert db_path.read_bytes() == bytes_after_first
