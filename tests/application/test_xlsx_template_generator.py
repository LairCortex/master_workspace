"""Calendar-aware template generator (piece C5, task group 3).

The generator moved out of this suite's helper into
``app.application.services.xlsx_template`` and now answers a given game
calendar: sample dates are deterministic clamps to valid coordinates
(month → ``min`` over the month count, day → ``min`` over that month's
length, design D7), the BC sample row speaks the game wording in the custom
branch, and a non-empty ``spec.intercalary`` grows one extra «События» row.
The «Стандартный» adjustment is the identity — pinned twice: against the raw
``SAMPLE_ROWS`` values (below) and, in ``test_xlsx_import_template``, against
the committed resource while it still exists.  The gold snapshots freeze the
generator's cell tables (the standard one captured from the generator BEFORE
the resource is removed, the custom one from the fixed 13-month calendar of
design D6) so both contracts outlive the binary file.  Finally the
cleanliness invariant of spec «Шаблон импортируется в свою игру чисто»: the
generated template of either fixed game analyzes and applies without a single
problem row or transfer row.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.application.services import xlsx_schema
from app.application.services.xlsx_import_service import XlsxImportService
from app.application.services.xlsx_template import (
    SAMPLE_ROWS,
    build_template_workbook,
    template_headers,
    template_row_values,
)
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    StandardCalendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.infrastructure.calendar_storage import (
    encode_coord,
)
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.db.models import EventModel, ItemModel


# The fixed custom calendar of design D6: thirteen months with their own
# names and lengths (several shorter than the sample days they must clamp
# into), an eight-day week and one intercalary day.
_CUSTOM_SPEC = CalendarSpec(
    months=(
        MonthSpec("Зимостой", 30),
        MonthSpec("Вьюжень", 9),
        MonthSpec("Травень", 12),
        MonthSpec("Цветень", 28),
        MonthSpec("Жневень", 20),
        MonthSpec("Сенокос", 33),
        MonthSpec("Гридень", 31),
        MonthSpec("Листопад", 7),
        MonthSpec("Хмурень", 25),
        MonthSpec("Студень", 44),
        MonthSpec("Крещень", 11),
        MonthSpec("Медовик", 21),
        MonthSpec("Чернолист", 30),
    ),
    week_names=("рысь", "волк", "лиса", "лось", "барс", "соня", "зверь", "ёж"),
    intercalary=(IntercalarySpec("Медожор", after_month=10),),
)
_CUSTOM = CustomCalendar(_CUSTOM_SPEC)

# Degenerate calendar of design D7's robustness note: a single month of a
# single day — every sample date must clamp to (year, 1, 1).
_ONE_MONTH = CustomCalendar(
    CalendarSpec(months=(MonthSpec("Круг", 1),), week_names=("утро", "вечер"))
)


@pytest.fixture(autouse=True)
def _standard_active_calendar():
    """The custom-calendar tests must not leak the global in or out."""
    reset_current_calendar()
    yield
    reset_current_calendar()


def _sheet_values(wb: Workbook, title: str) -> list[list[object]]:
    """Cell values of one sheet with datetimes normalized to dates."""
    rows = []
    for raw in wb[title].iter_rows(values_only=True):
        rows.append([
            value.date() if isinstance(value, datetime) else value
            for value in raw
        ])
    return rows


# ── 3.2 «standard adjustment — identity» ──────────────────────────────────

class TestPresetAdjustmentIsIdentity:
    def test_preset_output_equals_raw_sample_rows(self):
        wb = build_template_workbook(StandardCalendar())
        for sheet in xlsx_schema.all_sheets():
            expected = [template_headers(sheet)] + [
                template_row_values(sheet, row)
                for row in SAMPLE_ROWS[sheet.entity_type]
            ]
            assert _sheet_values(wb, sheet.sheet_name) == expected


# ── 3.2 — gold snapshot of the fixed custom calendar (design D6) ──────────

# The fixed calendar's adjustments per design D7: month → min over 13 months
# (never binds), day → min over the corrected month's length — Травень(12)
# clamps Заговор's and Иван's 15th, Медовик(21) clamps Дневник's 31st; the BC
# row speaks the game wording, the signed ISO keeps its carrier, and the
# declared intercalary day adds the «Ярмарка» row to «События».
_CUSTOM_GOLD: dict[str, list[list[object]]] = {
    "События": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "Тип", "Связь персонажами", "Связь организациями",
         "Связь предметами", "Связь локациями"],
        ["Бал", date(1820, 5, 1), "1820-05-02",
         "Зимний бал в особняке на соборной площади",
         "Танец, после которого старый город заговорил о Марии и Иване.",
         4, "Праздник", "Иван; Мария", "Городская управа", "Дневник", "Особняк"],
        ["Дуэль", "1815-01-10", None, "На рассвете, за старыми дубами",
         None, None, "Дуэль", "Иван", None, None, "Поляна"],
        ["Заговор", "12 Травень 44 г. до н.э.", "-0043-03-01",
         "Сговор против Цезаря"],
        ["Ярмарка", "Медожор 44", None, "Ярмарка в день между месяцами"],
    ],
    "Персонажи": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "personality", "tasks", "music_url", "Изображение",
         "Связь событиями", "Связь организациями", "Связь предметами",
         "Связь локациями"],
        ["Иван", "1790-03-12", None, "Городской кузнец",
         "Учился ремеслу у отца, клялся отомстить за него.", 5, "Вспыльчивый",
         "Починить крышу кузницы", "https://example.org/tema-ivana.mp3", None,
         "Бал; Дуэль", None, None, "Особняк"],
        ["Мария", "1795-07-20", None, "Приёмная дочь банкира",
         "Ведёт дневник, который не для посторонних глаз.", None, "Сдержанная",
         None, None, None, "Бал", "Городская управа", "Дневник", "Особняк"],
    ],
    "Локации": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "tasks", "music_url", "Изображение", "Связь событиями",
         "Связь персонажами", "Связь организациями", "Связь предметами"],
        ["Особняк", "1800-01-01", None, "Каменный особняк на соборной площади",
         None, None, "Ремонт восточного крыла", None, None, "Бал",
         "Иван; Мария"],
        ["Поляна", "1815-01-10", None, "Поляна за старыми дубами", None, None,
         None, None, None, "Дуэль"],
    ],
    "Организации": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "tasks", "music_url", "Изображение", "Связь событиями",
         "Связь персонажами", "Связь предметами", "Связь локациями"],
        ["Городская управа", "1780-02-01", None, "Магистрат старого города",
         None, None, "Благоустройство площади", None, None, "Бал", "Мария"],
    ],
    "Предметы": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "music_url", "Связь событиями", "Связь персонажами",
         "Связь организациями", "Связь локациями"],
        ["Дневник", "1819-12-21", None, "Кожаный дневник с вензелями", None,
         None, None, "Бал", "Мария"],
    ],
}


def _trimmed(rows: list[list[object]]) -> list[list[object]]:
    """Drop trailing empty cells, so None-sparse rows compare tightly."""
    trimmed = []
    for row in rows:
        row = list(row)
        while row and row[-1] is None:
            row.pop()
        trimmed.append(row)
    return trimmed


class TestCustomGoldSnapshot:
    def test_custom_calendar_golden_cell_table(self):
        wb = build_template_workbook(_CUSTOM)
        assert [s.sheet_name for s in xlsx_schema.all_sheets()] == list(_CUSTOM_GOLD)
        for title, gold in _CUSTOM_GOLD.items():
            assert _trimmed(_sheet_values(wb, title)) == gold, title

    def test_intercalary_row_only_when_declared(self):
        # The extra «События» row is a non-empty spec.intercalary product:
        # the intercalary-less one-month calendar keeps the three sample rows.
        wb = build_template_workbook(_ONE_MONTH)
        assert len(_sheet_values(wb, "События")) == 4  # header + three samples


# ── 3.2 — robustness against a degenerate calendar (design D7 note) ───────

class TestDegenerateCalendar:
    def test_single_one_day_month_clamps_every_sample_date(self):
        wb = build_template_workbook(_ONE_MONTH)
        values = {sheet.sheet_name: _sheet_values(wb, sheet.sheet_name)
                  for sheet in xlsx_schema.all_sheets()}
        # native cell stays native, ISO text stays ISO — all on (year, 1, 1);
        # the BC row takes the game wording of the single month «Круг».
        assert values["События"][1][1] == date(1820, 1, 1)
        assert values["События"][1][2] == "1820-01-01"
        assert values["События"][3][1] == "01 Круг 44 г. до н.э."
        assert values["События"][3][2] == "-0043-01-01"
        assert values["Персонажи"][1][1] == "1790-01-01"
        assert values["Персонажи"][2][1] == "1795-01-01"
        assert values["Локации"][1][1] == "1800-01-01"
        assert values["Организации"][1][1] == "1780-01-01"
        assert values["Предметы"][1][1] == "1819-01-01"


# ── 3.2 — carrier fallback when the clamp leaves the Gregorian shape ───────

# Six months, the sixth longer than real June (33 days): the «Дневник» sample
# (Dec 31) clamps onto 31-е of game month 6, and the text «1819-06-31» is no
# ISO date any more — the parser itself would refuse it (fromisoformat fails,
# no game form matches digits).  The cleanliness invariant (spec «Шаблон
# импортируется в свою игру чисто») therefore outranks carrier preservation
# here (D7): the cell must switch to a carrier this calendar's grammar reads.
_LONG_JUNE = CustomCalendar(CalendarSpec(
    months=tuple(
        MonthSpec(name, 33 if index == 6 else 30)
        for index, name in enumerate(
            ("Зимостой", "Вьюжень", "Травень", "Цветень", "Жневень", "Сенокос"),
            start=1,
        )
    ),
    week_names=("рысь", "волк"),
))


class TestClampedIsoBeyondGregorianShape:
    def test_iso_cell_clamped_to_a_gregorian_impossible_day_renders_game_wording(self):
        wb = build_template_workbook(_LONG_JUNE)
        items = _sheet_values(wb, "Предметы")
        start = items[1][1]  # «Дневник»: 31-е month 6 of length 33
        assert start != "1819-06-31"  # the unreadable ISO text must never ship
        assert start == "31 Сенокос 1819"
        # …and that carrier really reads back as the same coordinate.
        parsed = xlsx_schema.parse_cell_date(start, _LONG_JUNE)
        assert parsed.ok and parsed.coord == MonthDay(1819, 6, 31)

    async def test_six_month_calendar_template_imports_cleanly(self, tmp_path, async_session):
        await _assert_imports_into_itself_cleanly(
            build_template_workbook(_LONG_JUNE), _LONG_JUNE,
            async_session, tmp_path,
        )
        item = (
            await async_session.execute(select(ItemModel))
        ).scalars().one()
        assert item.start_coord == encode_coord(MonthDay(1819, 6, 31))


# ── 3.3 — gold snapshot of the «Стандартный» preset ───────────────────────

# Captured from the generator's output while resources/import_template.xlsx
# still existed and the equality test still compared the two — so this table
# IS the previous version's template cell-for-cell (spec «Стандартный пресет
# получает прежний шаблон»), outliving the binary file.
_STANDARD_GOLD: dict[str, list[list[object]]] = {
    "События": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "Тип", "Связь персонажами", "Связь организациями",
         "Связь предметами", "Связь локациями"],
        ["Бал", date(1820, 5, 1), "1820-05-02",
         "Зимний бал в особняке на соборной площади",
         "Танец, после которого старый город заговорил о Марии и Иване.",
         4, "Праздник", "Иван; Мария", "Городская управа", "Дневник", "Особняк"],
        ["Дуэль", "1815-01-10", None, "На рассвете, за старыми дубами",
         None, None, "Дуэль", "Иван", None, None, "Поляна"],
        ["Заговор", "15 марта 44 г. до н.э.", "-0043-03-01",
         "Сговор против Цезаря"],
    ],
    "Персонажи": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "personality", "tasks", "music_url", "Изображение",
         "Связь событиями", "Связь организациями", "Связь предметами",
         "Связь локациями"],
        ["Иван", "1790-03-15", None, "Городской кузнец",
         "Учился ремеслу у отца, клялся отомстить за него.", 5, "Вспыльчивый",
         "Починить крышу кузницы", "https://example.org/tema-ivana.mp3", None,
         "Бал; Дуэль", None, None, "Особняк"],
        ["Мария", "1795-07-20", None, "Приёмная дочь банкира",
         "Ведёт дневник, который не для посторонних глаз.", None, "Сдержанная",
         None, None, None, "Бал", "Городская управа", "Дневник", "Особняк"],
    ],
    "Локации": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "tasks", "music_url", "Изображение", "Связь событиями",
         "Связь персонажами", "Связь организациями", "Связь предметами"],
        ["Особняк", "1800-01-01", None, "Каменный особняк на соборной площади",
         None, None, "Ремонт восточного крыла", None, None, "Бал",
         "Иван; Мария"],
        ["Поляна", "1815-01-10", None, "Поляна за старыми дубами", None, None,
         None, None, None, "Дуэль"],
    ],
    "Организации": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "tasks", "music_url", "Изображение", "Связь событиями",
         "Связь персонажами", "Связь предметами", "Связь локациями"],
        ["Городская управа", "1780-02-01", None, "Магистрат старого города",
         None, None, "Благоустройство площади", None, None, "Бал", "Мария"],
    ],
    "Предметы": [
        ["Имя", "Дата начала", "Дата конца", "Характеристики", "Предыстория",
         "Рейтинг", "music_url", "Связь событиями", "Связь персонажами",
         "Связь организациями", "Связь локациями"],
        ["Дневник", "1819-12-31", None, "Кожаный дневник с вензелями", None,
         None, None, "Бал", "Мария"],
    ],
}


class TestStandardGoldSnapshot:
    def test_standard_calendar_golden_cell_table(self):
        wb = build_template_workbook(StandardCalendar())
        assert [s.sheet_name for s in xlsx_schema.all_sheets()] == list(_STANDARD_GOLD)
        for title, gold in _STANDARD_GOLD.items():
            assert _trimmed(_sheet_values(wb, title)) == gold, title


# ── 3.3 — cleanliness invariant (spec «Шаблон импортируется в свою игру чисто») ──

def _svc() -> XlsxImportService:
    return XlsxImportService(image_store=None)


async def _assert_imports_into_itself_cleanly(wb: Workbook, calendar, session, tmp_path):
    """Analyze and apply ``wb`` as if the game owning ``calendar`` downloaded
    and re-imported it: zero problems, zero ghosts, zero transfer rows."""
    path = tmp_path / "downloaded-template.xlsx"
    wb.save(path)
    set_current_calendar(calendar)

    plan = await _svc().analyze_file(path, GameSessionUoW(session))
    assert plan.fatal_errors == []
    assert plan.skipped_rows == []
    assert plan.warnings == []
    assert plan.ghosts == {}

    report = await _svc().apply_plan(plan, GameSessionUoW(session))
    assert report.skipped == []
    assert report.date_shifts == []  # not a single transfer row
    return report


class TestTemplateCleanliness:
    async def test_standard_template_imports_into_standard_game_cleanly(
        self, tmp_path, async_session
    ):
        report = await _assert_imports_into_itself_cleanly(
            build_template_workbook(StandardCalendar()), StandardCalendar(),
            async_session, tmp_path,
        )
        expected_entities = sum(len(rows) for rows in SAMPLE_ROWS.values())
        assert report.created == expected_entities
        assert report.updated == 0

    async def test_custom_template_imports_into_custom_game_cleanly(
        self, tmp_path, async_session
    ):
        report = await _assert_imports_into_itself_cleanly(
            build_template_workbook(_CUSTOM), _CUSTOM, async_session, tmp_path,
        )
        expected_entities = sum(len(rows) for rows in SAMPLE_ROWS.values()) + 1
        assert report.created == expected_entities  # the intercalary row included

        # The dates really landed as coordinates of the very calendar whose
        # template this is (game forms round-trip through the parser).
        events = {
            e.name: e
            for e in (await async_session.execute(select(EventModel))).scalars()
        }
        assert events["Ярмарка"].start_coord == encode_coord(IntercalaryDay(44, 0))
        assert events["Заговор"].start_coord == encode_coord(MonthDay(44, 3, 12))
        assert bool(events["Заговор"].start_bc) is True


