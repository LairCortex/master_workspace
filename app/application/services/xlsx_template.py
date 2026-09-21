"""The import-template generator (piece C5, designs D6/D7).

The five-sheet template the import dialog offers under "Скачать шаблон" used
to ship as a static binary (``resources/import_template.xlsx``) kept in step
cell-for-cell by the generator this module hosts since C5 — the reproducible
generator (headers from the registry, data from ``SAMPLE_ROWS``) migrated here
from ``tests/application/test_xlsx_import_template.py`` unchanged (D6: the
generator is part of the import contract, and the dialog stays a transport).

Unlike the binary, the generator answers a game calendar: every sample date
becomes a valid coordinate of that calendar (design D7) — months clamp to the
calendar's month count, days to that month's length, the cell carrier is
preserved (native stays native, ISO text stays ISO) except where the clamped
numbers no longer fit that carrier, which the game wording takes over.  For
the «Стандартный» preset the adjustment is the identity, so its template
stays cell-for-cell the
template of the previous version (spec «Стандартный пресет получает прежний
шаблон»).
"""
from __future__ import annotations

from datetime import date

from openpyxl import Workbook

from app.application.services import xlsx_schema
from app.domain.game_calendar import GameCalendar, StandardCalendar

# Sample rows keyed by column key (ColumnSpec.key) / link target type. The
# rows cross-reference each other in BOTH directions with `;` lists (spec
# «Ссылка на строку другого листа») so the template demonstrates the link
# syntax; «Бал» carries a native date cell, the other rows ISO text, and
# «Заговор» shows both accepted BC text forms — all valid date spellings.
SAMPLE_ROWS: dict[str, list[dict[str, object]]] = {
    "event": [
        {
            "name": "Бал", "start_date": date(1820, 5, 1), "end_date": "1820-05-02",
            "characteristics": "Зимний бал в особняке на соборной площади",
            "backstory": "Танец, после которого старый город заговорил о Марии и Иване.",
            "rating": 4, "event_type": "Праздник",
            "character": "Иван; Мария", "organization": "Городская управа",
            "item": "Дневник", "location": "Особняк",
        },
        {
            "name": "Дуэль", "start_date": "1815-01-10", "end_date": None,
            "characteristics": "На рассвете, за старыми дубами",
            "backstory": None, "rating": None, "event_type": "Дуэль",
            "character": "Иван", "organization": None,
            "item": None, "location": "Поляна",
        },
        {
            # Era-aware dates (add-era-aware-dates): both accepted BC text
            # forms in one row — the game wording in «Дата начала» and the
            # signed ISO in «Дата конца».
            "name": "Заговор", "start_date": "15 марта 44 г. до н.э.",
            "end_date": "-0043-03-01",
            "characteristics": "Сговор против Цезаря",
            "backstory": None, "rating": None, "event_type": None,
            "character": None, "organization": None,
            "item": None, "location": None,
        },
    ],
    "character": [
        {
            "name": "Иван", "start_date": "1790-03-15", "end_date": None,
            "characteristics": "Городской кузнец",
            "backstory": "Учился ремеслу у отца, клялся отомстить за него.",
            "rating": 5, "personality": "Вспыльчивый", "tasks": "Починить крышу кузницы",
            "music_url": "https://example.org/tema-ivana.mp3", "image": None,
            "event": "Бал; Дуэль", "organization": None, "item": None,
            "location": "Особняк",
        },
        {
            "name": "Мария", "start_date": "1795-07-20", "end_date": None,
            "characteristics": "Приёмная дочь банкира",
            "backstory": "Ведёт дневник, который не для посторонних глаз.",
            "rating": None, "personality": "Сдержанная", "tasks": None,
            "music_url": None, "image": None,
            "event": "Бал", "organization": "Городская управа",
            "item": "Дневник", "location": "Особняк",
        },
    ],
    "location": [
        {
            "name": "Особняк", "start_date": "1800-01-01", "end_date": None,
            "characteristics": "Каменный особняк на соборной площади",
            "backstory": None, "rating": None, "tasks": "Ремонт восточного крыла",
            "music_url": None, "image": None,
            "event": "Бал", "character": "Иван; Мария", "organization": None,
            "item": None,
        },
        {
            "name": "Поляна", "start_date": "1815-01-10", "end_date": None,
            "characteristics": "Поляна за старыми дубами",
            "backstory": None, "rating": None, "tasks": None,
            "music_url": None, "image": None,
            "event": "Дуэль", "character": None, "organization": None,
            "item": None,
        },
    ],
    "organization": [
        {
            "name": "Городская управа", "start_date": "1780-02-01", "end_date": None,
            "characteristics": "Магистрат старого города",
            "backstory": None, "rating": None, "tasks": "Благоустройство площади",
            "music_url": None, "image": None,
            "event": "Бал", "character": "Мария", "item": None, "location": None,
        },
    ],
    "item": [
        {
            "name": "Дневник", "start_date": "1819-12-31", "end_date": None,
            "characteristics": "Кожаный дневник с вензелями",
            "backstory": None, "rating": None, "music_url": None,
            "event": "Бал", "character": "Мария", "organization": None,
            "location": None,
        },
    ],
}


def template_headers(sheet: xlsx_schema.SheetSpec) -> list[str]:
    """RU headers of one sheet — straight from the registry (all_headers)."""
    return [column.label for column in xlsx_schema.all_headers(sheet)]


def template_row_values(
    sheet: xlsx_schema.SheetSpec, row: dict[str, object]
) -> list[object]:
    """Sample-row values ordered exactly like ``template_headers``.

    A scalar column is looked up by its ``key``, a link column by its target
    type — the two namespaces never collide (column keys are field names,
    link keys are entity types).
    """
    return [
        row.get(
            column.key if isinstance(column, xlsx_schema.ColumnSpec)
            else column.target_type
        )
        for column in xlsx_schema.all_headers(sheet)
    ]


# ── Sample-date adjustment (design D7) ─────────────────────────────────────

# Reads the SAMPLE_ROWS numbers through the untouched preset grammar — the
# adjustment is about coordinates of the TARGET calendar, the sample cells are
# authored in preset spellings, so the preset reader just extracts numbers.
_PRESET_READER = StandardCalendar()

# The era suffix of the game wording, exactly what the app's date captions
# print (presentation.date_utils.format_game_date) — the custom-branch BC
# sample row re-renders with it.
_BC_ERA_SUFFIX = " г. до н.э."

# The extra intercalary sample row: an arbitrary valid world year (the parse
# accepts the day-less «Имя год» form for the first declared rule), minimal
# fields — template_row_values resolves every absent key to an empty cell.
_INTERCALARY_SAMPLE_YEAR = 44
_INTERCALARY_SAMPLE_ROW: dict[str, object] = {
    "name": "Ярмарка",
    "characteristics": "Ярмарка в день между месяцами",
}


def _adjust_date_cell(value: object, calendar: GameCalendar) -> object:
    """One sample date → the same (year, era) coordinate clamped into
    ``calendar``: month → ``min`` over the calendar's months, day → ``min``
    over that month's length (design D7).  The carrier survives where it can
    carry — a native cell stays a native date, an ISO text stays ISO, the
    signed ISO keeps its sign — and the game wording takes over where it
    cannot: the custom branch's BC text row, and an ISO text whose clamped
    numbers leave the Gregorian shape (the cleanliness invariant of D7 wins
    over carrier preservation there).  For the «Стандартный» preset every
    sample date is already a valid coordinate, so there the adjustment is the
    identity and nothing (not even the BC spelling) is rewritten.
    """
    spec = getattr(calendar, "spec", None)
    if spec is None:
        return value  # preset adjustment — the identity (spec «прежний шаблон»)
    parsed = xlsx_schema.parse_cell_date(value, _PRESET_READER)
    coord = parsed.coord  # every SAMPLE_ROWS date cell parses into a MonthDay
    month = min(coord.month, len(spec.months))
    day = min(coord.day, calendar.month_length(coord.year, month))
    if isinstance(value, date):
        return date(coord.year, month, day)
    text = str(value).strip()
    if text.startswith("-"):
        return f"-{coord.year:04d}-{month:02d}-{day:02d}"
    try:
        date.fromisoformat(text)
    except ValueError:
        name = calendar.month_names.get(month, str(month))
        return f"{day:02d} {name} {coord.year}{_BC_ERA_SUFFIX}"
    iso = f"{coord.year:04d}-{month:02d}-{day:02d}"
    try:
        # The clamp may land on numbers the ISO carrier cannot hold (a game
        # month longer than its Gregorian namesake — e.g. Dec 31 clamped onto
        # a 33-day game June).  The cleanliness invariant outranks carrier
        # preservation there (D7 robustness, spec «Шаблон импортируется в свою
        # игру чисто»): fall back to the game wording this calendar reads.
        date.fromisoformat(iso)
    except ValueError:
        name = calendar.month_names.get(month, str(month))
        return f"{day:02d} {name} {coord.year}"
    return iso


def _adjust_row(row: dict[str, object], calendar: GameCalendar) -> dict[str, object]:
    """Copy of one sample row with its two date columns adjusted."""
    adjusted = dict(row)
    for key in ("start_date", "end_date"):
        value = adjusted.get(key)
        if value is not None:
            adjusted[key] = _adjust_date_cell(value, calendar)
    return adjusted


def _intercalary_sample_row(calendar: GameCalendar) -> dict[str, object] | None:
    """Extra «События» row demonstrating the day-less intercalary form, only
    when the calendar declares intercalary days (design D7)."""
    spec = getattr(calendar, "spec", None)
    if spec is None or not spec.intercalary:
        return None
    row = dict(_INTERCALARY_SAMPLE_ROW)
    row["start_date"] = f"{spec.intercalary[0].name} {_INTERCALARY_SAMPLE_YEAR}"
    return row


def build_template_workbook(calendar: GameCalendar) -> Workbook:
    """Regenerate the template workbook from the registry + SAMPLE_ROWS.

    Moved from the test suite verbatim (task 3.1); ``calendar`` drives the
    sample-date adjustment of design D7 (task 3.2) — under the «Стандартный»
    preset the workbook is byte-content-identical to the old template.
    """
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in xlsx_schema.all_sheets():
        ws = wb.create_sheet(sheet.sheet_name)
        ws.append(template_headers(sheet))
        for row in SAMPLE_ROWS[sheet.entity_type]:
            ws.append(template_row_values(sheet, _adjust_row(row, calendar)))
        if sheet.entity_type == "event":
            extra = _intercalary_sample_row(calendar)
            if extra is not None:
                ws.append(template_row_values(sheet, extra))
    return wb
