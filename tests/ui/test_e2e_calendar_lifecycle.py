"""E2E lifecycle of the active calendar across games (piece C2, task 5.3).

Spec «Активный календарь в жизненном цикле игры», both scenarios, as a
temporal test over two throw-away game databases driven through the real
``Application`` lifecycle (start / shutdown, as a game switch performs):

* «Две игры с разными календарями» — a standard-preset game and a game whose
  custom spec was written into ``game_settings`` directly; each open speaks
  its own month names and keys its dates through its own calendar, with no
  trace of the other leaking across a regular close.
* «После закрытия игры — пресет» — after every shutdown the active calendar
  is the «Стандартный» preset again.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from app.domain.date_era import era_key
from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    CalendarSpec,
    CustomCalendar,
    MonthDay,
    MonthSpec,
    StandardCalendar,
    current_calendar,
    encode_calendar,
)
from app.infrastructure.db.database import create_engine
from app.infrastructure.db.migrations import init_db
from app.main import Application
from app.presentation.utils.date_utils import format_game_date

#: Three flat 30-day months — deliberately nothing like the Gregorian preset,
#: so any leakage between games shows up as a wrong name or key immediately.
CUSTOM_MONTH_NAMES = ("Светопрел", "Тьмопрест", "Хмарь")

CUSTOM_CALENDAR = CustomCalendar(
    CalendarSpec(
        months=tuple(MonthSpec(name, 30) for name in CUSTOM_MONTH_NAMES),
        week_names=("Буд", "Ведь", "Творец", "Грозник", "Светлай", "Прочь", "Хмарь"),
    )
)


async def _make_custom_game_db(db_path: Path) -> None:
    """Create a game file whose ``game_calendar`` holds the custom spec.

    The setting is written straight into the database («настройки записаны
    напрямую»): the C4 wizard is the only in-app writer of custom specs."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    (db_path.parent / "images").mkdir(exist_ok=True)
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await init_db(engine)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO game_settings (key, value) VALUES ('game_calendar', ?)",
                (encode_calendar(CUSTOM_CALENDAR),),
            )
    finally:
        await engine.dispose()


def _game_settings_rows(db_path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [tuple(row) for row in conn.execute("SELECT key, value FROM game_settings")]
    finally:
        conn.close()


def _assert_standard_game(db_path: Path) -> None:
    """The Gregorian preset is active: names, captions, key order."""
    calendar = current_calendar()
    assert isinstance(calendar, StandardCalendar)
    assert dict(calendar.month_names) == dict(DEFAULT_MONTH_NAMES)
    assert format_game_date(date(1200, 5, 1)) == "01 Май 1200"
    # Standard keys are the pre-C2 numbers: the AD scale is the ordinal.
    assert era_key(date(1200, 5, 1)) == date(1200, 5, 1).toordinal()
    # An old game without either calendar key gets no key written "just in
    # case" (spec «Старая игра без ключа»).
    assert _game_settings_rows(db_path) == []


def _assert_custom_game() -> None:
    """The custom spec is active: its own names in its own key order."""
    calendar = current_calendar()
    assert isinstance(calendar, CustomCalendar)
    assert [calendar.month_names[number] for number in (1, 2, 3)] == list(
        CUSTOM_MONTH_NAMES
    )
    # Names come from the spec, in month order; captions follow them…
    assert format_game_date(date(5, 3, 10)) == "10 Хмарь 5"
    # …and the chronological ORDER of dates keys through this calendar: the
    # same coordinate maps to its linear year (L = 90), not to the ordinal.
    key = era_key(date(5, 3, 10))
    assert key == calendar.to_key(MonthDay(5, 3, 10))
    assert key != date(5, 3, 10).toordinal()


async def test_two_games_keep_own_calendars_close_to_preset(
    qapp, llm_client, tmp_llm_config, tmp_path
):
    standard_db = tmp_path / "Std" / "game.db"
    standard_db.parent.mkdir(parents=True)
    (standard_db.parent / "images").mkdir()
    custom_db = tmp_path / "Custom" / "game.db"
    await _make_custom_game_db(custom_db)

    application = Application(qapp, http=llm_client)

    # ── Game 1: no calendar key at all — the «Стандартный» preset. ──
    window = await application.start(str(standard_db))
    try:
        _assert_standard_game(standard_db)
    finally:
        window.close()
    await application.shutdown()
    # «После закрытия игры — пресет»: the preset survives the first close…
    assert isinstance(current_calendar(), StandardCalendar)

    # ── Game 2: the custom spec, opened through the same lifecycle. ──
    window = await application.start(str(custom_db))
    try:
        _assert_custom_game()
    finally:
        window.close()
    await application.shutdown()
    # …and also the custom game's close.
    assert isinstance(current_calendar(), StandardCalendar)
    assert dict(current_calendar().month_names) == dict(DEFAULT_MONTH_NAMES)

    # ── Back to game 1: state of the previous game did not leak. ──
    window = await application.start(str(standard_db))
    try:
        _assert_standard_game(standard_db)
    finally:
        window.close()
    await application.shutdown()

    # And game 2 through the same round-trip keeps its own calendar again.
    window = await application.start(str(custom_db))
    try:
        _assert_custom_game()
    finally:
        window.close()
    await application.shutdown()
    assert isinstance(current_calendar(), StandardCalendar)
