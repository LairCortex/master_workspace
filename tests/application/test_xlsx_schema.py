"""Tests for the xlsx import file-format registry (app.application.services.xlsx_schema).

Covers tasks 1.1 (registry completeness vs the 13 M2M association tables),
1.2 (header normalization / aliases / required-column check) and
1.3 (date / rating / link-list value parsing edge cases).

Since piece C5 the date parser speaks in game-calendar coordinates: every
positive case below compares against ``DateParse.ok(...)`` (task 1.1/1.2), while
the None cases stay untouched as the regression ban on growing new forms.
"""
from datetime import date, datetime

import pytest

from app.application.services import xlsx_schema as schema
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    StandardCalendar,
    reset_current_calendar,
)
from app.infrastructure.db.models import Base


# ── 1.1 registry completeness ─────────────────────────────────────────────

EXPECTED_SHEET_NAMES = {"События", "Персонажи", "Локации", "Организации", "Предметы"}


@pytest.fixture(autouse=True)
def _standard_active_calendar():
    """The default ``calendar`` argument of the date parser is the process
    global — keep it the «Стандартный» preset here so no other module's
    calendar leaks into these expectations (and out of them)."""
    reset_current_calendar()
    yield
    reset_current_calendar()


def _association_tables() -> set[str]:
    return {
        t.name
        for t in Base.metadata.tables.values()
        if len(t.primary_key.columns) == 2
    }


def test_registry_has_five_sheets_expected_names():
    sheets = schema.all_sheets()
    assert len(sheets) == 5
    assert {s.sheet_name for s in sheets} == EXPECTED_SHEET_NAMES
    assert {s.entity_type for s in sheets} == {
        "event", "character", "location", "organization", "item",
    }


def test_every_sheet_has_required_name_and_start_date():
    for sheet in schema.all_sheets():
        required = {c.key: c for c in sheet.required_columns}
        assert set(required) == {"name", "start_date"}, sheet.sheet_name
        assert required["name"].label == "Имя"
        assert required["start_date"].label == "Дата начала"


def test_link_columns_cover_all_m2m_except_ratings():
    # Sanity: the schema really has 13 M2M tables, 3 of them *_rating.
    assoc = _association_tables()
    assert len(assoc) == 13
    assert {n for n in assoc if n.endswith("_rating")} == {
        "character_rating", "item_rating", "location_rating",
    }
    reachable = {
        schema.link_table(sheet.entity_type, target)
        for sheet in schema.all_sheets()
        for target in sheet.link_targets
    }
    assert reachable == assoc - {n for n in assoc if n.endswith("_rating")}
    # The link registry must never point at a *_rating table.
    assert not any(t.endswith("_rating") for t in schema.LINK_TABLES.values())


def test_link_column_counts_per_sheet():
    # Spec: event sheet has four link columns without "Связь событиями",
    # every other sheet has four including it.
    event = schema.sheet_for("event")
    assert "event" not in event.link_targets
    assert len(event.link_columns) == 4
    for sheet in schema.all_sheets():
        if sheet.entity_type == "event":
            continue
        assert "event" in sheet.link_targets
        assert sheet.entity_type not in sheet.link_targets
        assert len(sheet.link_columns) == 4
        assert schema.LINK_COLUMNS_BY_TARGET["event"].label == "Связь событиями"


def test_link_table_lookup_is_symmetric_and_rejects_unknown():
    assert schema.link_table("event", "character") == "event_character"
    assert schema.link_table("character", "event") == "event_character"
    assert schema.link_table("item", "location").startswith("item_location")
    with pytest.raises(ValueError):
        schema.link_table("event", "rating")


def test_special_columns_placement():
    event = schema.sheet_for("event")
    assert event.column("event_type") is not None  # "Тип" — events only
    for sheet in schema.all_sheets():
        if sheet.entity_type != "event":
            assert sheet.column("event_type") is None
    image_types = {"character", "organization", "location"}
    for sheet in schema.all_sheets():
        # "Рейтинг" — on all sheets (spec), marked special.
        rating = sheet.column("rating")
        assert rating is not None and rating.label == "Рейтинг" and rating.special
        has_image = sheet.column("image") is not None
        assert has_image == (sheet.entity_type in image_types)
        if has_image:
            assert sheet.column("image").label == "Изображение"


def test_legacy_english_alias_columns_available_by_type():
    # personality only characters; tasks — character/location/organization;
    # music_url — everywhere except events (mirrors the old per-type columns).
    assert schema.sheet_for("character").column("personality") is not None
    assert schema.sheet_for("location").column("personality") is None
    for et in ("character", "location", "organization"):
        assert schema.sheet_for(et).column("tasks") is not None
    assert schema.sheet_for("event").column("tasks") is None
    for et in ("character", "location", "organization", "item"):
        assert schema.sheet_for(et).column("music_url") is not None


# ── 1.2 header normalization + required check ─────────────────────────────

def test_normalize_header_case_and_whitespace_insensitive():
    assert schema.normalize_header("  Дата   начала\n") == schema.normalize_header("датаначала")
    assert schema.normalize_header("Имя") == schema.normalize_header("  имя ")
    assert schema.normalize_header(None) == ""


def test_english_headers_read_as_russian_columns():
    # Spec scenario: `name` / `start_date` are treated as `Имя` / `Дата начала`.
    sheet = schema.sheet_for("character")
    resolved = schema.resolve_headers(sheet, ["START_DATE", " Name "])
    assert resolved.position("name") == 1
    assert resolved.position("start_date") == 0
    assert not resolved.unknown
    assert resolved.position("backstory") is None  # нет такой колонки — нет позиции
    assert schema.missing_required_headers(sheet, ["name", "start_date"]) == []


def test_russian_headers_and_case_variants_resolve():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(sheet, ["ИМЯ", "Дата  начала", "Тип"])
    assert resolved.position("name") == 0
    assert resolved.position("start_date") == 1
    assert resolved.scalars[2].key == "event_type"
    assert resolved.scalars[2].special


def test_link_headers_resolve_to_link_columns():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(
        sheet, ["Имя", "Дата начала", " связь Персонажами ", "СВЯЗЬ ПРЕДМЕТАМИ"]
    )
    assert {c.target_type for c in resolved.links.values()} == {"character", "item"}
    assert not resolved.unknown


def test_unknown_columns_reported_and_ignored():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(sheet, ["Имя", "Заметка", "", None, "Дата начала"])
    assert resolved.unknown == ["Заметка"]


def test_link_column_of_foreign_semantics_not_matched_wrongly():
    # "Связь событиями" is not a column of the events sheet, so it is unknown there.
    resolved = schema.resolve_headers(schema.sheet_for("event"), ["Связь событиями"])
    assert resolved.unknown == ["Связь событиями"]


def test_duplicate_header_first_occurrence_wins():
    sheet = schema.sheet_for("event")
    resolved = schema.resolve_headers(sheet, ["Имя", "name", "Дата начала"])
    assert resolved.position("name") == 0
    assert resolved.unknown == []  # duplicate alias is known, just superseded


def test_missing_required_headers_lists_labels():
    sheet = schema.sheet_for("character")
    assert schema.missing_required_headers(sheet, ["Характеристики"]) == [
        "Имя", "Дата начала",
    ]
    assert schema.missing_required_headers(sheet, ["Имя", "Дата начала"]) == []


def test_find_sheet_by_name_case_insensitive():
    assert schema.sheet_for("event") is schema.find_sheet_by_name("события")
    assert schema.find_sheet_by_name("  ОРГАНИЗАЦИИ ").entity_type == "organization"
    assert schema.find_sheet_by_name("Заметки") is None


def test_sheet_for_unknown_type_raises():
    with pytest.raises(ValueError):
        schema.sheet_for("planet")


# ── 1.3 value parsing ─────────────────────────────────────────────────────

def test_date_parse_ok_and_fail_are_exclusive():
    # Design D2's invariant: exactly one of coord / problem, so the direct
    # constructor is not an option — only the two factories build a DateParse.
    ok = schema.DateParse.ok(MonthDay(2025, 12, 31), False)
    assert ok.coord == MonthDay(2025, 12, 31) and ok.is_bc is False
    assert ok.problem is None and ok.ok is True

    failed = schema.DateParse.fail(schema.DateProblem("unknown_name", "Флорель"))
    assert failed.coord is None and failed.problem.code == "unknown_name"
    assert failed.ok is False

    with pytest.raises(ValueError):
        schema.DateParse(MonthDay(2025, 12, 31), False, schema.DateProblem("unknown_name"))
    with pytest.raises(ValueError):
        schema.DateParse(None, False, None)


def test_parse_date_native_cell_is_our_era():
    # add-era-aware-dates D7: native Excel cells keep the «н.э.» era.
    assert schema.parse_cell_date(datetime(2025, 12, 31, 10, 30)) == schema.DateParse.ok(
        MonthDay(2025, 12, 31), False
    )
    assert schema.parse_cell_date(date(1820, 5, 1)) == schema.DateParse.ok(
        MonthDay(1820, 5, 1), False
    )


def test_parse_date_text_iso_is_our_era():
    # A bare ISO date stays our era exactly as before.
    assert schema.parse_cell_date("2025-12-31") == schema.DateParse.ok(MonthDay(2025, 12, 31), False)
    assert schema.parse_cell_date(" 2025-12-31 ") == schema.DateParse.ok(MonthDay(2025, 12, 31), False)


def test_parse_date_bc_text():
    # Spec «Дата до нашей эры текстом»: the game wording with the mandatory
    # «г. до н.э.» suffix; both the genitive scenario spelling and the
    # nominative display spelling parse to the same coordinate + era.
    assert schema.parse_cell_date("5 марта 44 г. до н.э.") == schema.DateParse.ok(
        MonthDay(44, 3, 5), True
    )
    assert schema.parse_cell_date("05 Март 44 г. до н.э.") == schema.DateParse.ok(
        MonthDay(44, 3, 5), True
    )
    assert schema.parse_cell_date("  25 декабря 500 г до н э  ") == schema.DateParse.ok(
        MonthDay(500, 12, 25), True
    )
    # Leap-year mirror: 29 февраля до н.э. exists in the same years as after.
    assert schema.parse_cell_date("29 февраля 44 г. до н.э.") == schema.DateParse.ok(
        MonthDay(44, 2, 29), True
    )


def test_parse_date_bc_signed_iso():
    # Spec «Дата до нашей эры знаковым ISO»: same result as the text form.
    assert schema.parse_cell_date("-0044-03-05") == schema.DateParse.ok(MonthDay(44, 3, 5), True)
    assert schema.parse_cell_date(" -0500-01-01 ") == schema.DateParse.ok(MonthDay(500, 1, 1), True)
    assert schema.parse_cell_date("-9999-12-31") == schema.DateParse.ok(MonthDay(9999, 12, 31), True)


def test_parse_date_ok_carries_the_active_calendar_coordinate():
    # Design D2: the successful parse is the active calendar's own coordinate —
    # a month/day the game calendar is the authority on, not a datetime.date.
    parsed = schema.parse_cell_date("2025-12-31", StandardCalendar())
    assert isinstance(parsed.coord, MonthDay)
    assert parsed.ok is True


def test_parse_date_bc_forms_invalid_are_none():
    # Year zero exists in neither era; month/day must be real and stated.
    assert schema.parse_cell_date("-0000-01-01") is None
    assert schema.parse_cell_date("-0044-13-01") is None
    assert schema.parse_cell_date("-0044-02-30") is None
    assert schema.parse_cell_date("-44-03-05") is None  # не форма -YYYY-MM-DD
    assert schema.parse_cell_date("44 г. до н.э.") is None  # месяц обязателен
    assert schema.parse_cell_date("5 флореля 44 г. до н.э.") is None
    assert schema.parse_cell_date("5 марта 0 г. до н.э.") is None
    assert schema.parse_cell_date("5 марта 44 г. до н.э. и после") is None


def test_parse_date_bad_values_are_none():
    # Unparsable content yields None — the caller raises it as a row problem.
    assert schema.parse_cell_date("31.12.2025") is None
    assert schema.parse_cell_date("не дата") is None
    assert schema.parse_cell_date("") is None
    assert schema.parse_cell_date("   ") is None
    assert schema.parse_cell_date(None) is None
    assert schema.parse_cell_date(12345) is None


# Names the delta spec gives the custom grammar («Игровая форма месяца»,
# «Вставной день по имени»); the standard branch must refuse every one of them.
_GAME_MONTH_NAMES = {1: "Зимостой", 2: "Ледокол"}
_GAME_INTERCALARY_NAME = "Медожор"


@pytest.mark.parametrize(
    "cell",
    [
        "3 Зимостой 44",                       # spec «Стандартная игра не принимает…»
        "3 Зимостой 44 г.",
        "3 зимостой 44 г. до н.э.",
        f"{_GAME_INTERCALARY_NAME} 44",        # an intercalary name is no preset form
        f"{_GAME_INTERCALARY_NAME} 44 г. до н.э.",
    ],
)
def test_standard_preset_refuses_game_forms(cell):
    # Task 1.2 / design D5: the preset grammar gains no new textual form —
    # neither the game wording of a custom month nor an intercalary name
    # parses, whether the parser reads the active calendar or a preset whose
    # captions were relabeled (only a `spec` makes a calendar custom, D1).
    assert schema.parse_cell_date(cell) is None
    assert schema.parse_cell_date(cell, StandardCalendar(month_names=_GAME_MONTH_NAMES)) is None


# ── C5 tasks 2.1–2.3: the custom-branch grammar ───────────────────────────

# The fixed calendar of the game-form matrix: the delta-spec names «Зимостой»
# (30 days) and «Ледокол», plus a month deliberately relabeled «Март» so the
# genitive reference dictionary can bridge to it (design D3); «Флорель» and
# «апрель» are absent on purpose.  «Медожор»/«Пиггей» are the two intercalary
# rules — their spec-list positions (0/1) are the coordinate indexes (D10).
_CUSTOM_SPEC = CalendarSpec(
    months=(
        MonthSpec("Зимостой", 30),
        MonthSpec("Март", 31),
        MonthSpec("Ледокол", 15),
    ),
    week_names=("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
    intercalary=(
        IntercalarySpec("Медожор", after_month=1),
        IntercalarySpec("Пиггей", after_month=2),
    ),
)
_CUSTOM = CustomCalendar(_CUSTOM_SPEC)

# The validator never compares month names against intercalary ones — the
# write form itself distinguishes them (spec: с номером — месяц, без — вставной).
_DOUBLE_SPEC = CalendarSpec(
    months=(MonthSpec("Двойник", 12),),
    week_names=("пн", "вт"),
    intercalary=(IntercalarySpec("Двойник", after_month=1),),
)
_DOUBLE = CustomCalendar(_DOUBLE_SPEC)


@pytest.mark.parametrize("cell", [
    "3 Зимостой 44",              # spec «Игровая форма месяца»
    "3 зимостой 44",              # регистронезависимое сопоставление
    "3 ЗИМОСТОЙ 44",
    "   3 Зимостой 44   ",        # внешние пробелы
    "3 зимостой  44",             # spec «…лишних пробелов»: внутренний повтор схлопнут
    "3 Зимостой 44 г.",           # хвост «г.» — единственный источник эры: наша
    "3 Зимостой 44г.",            # та же терпимость к пробелу, что у стандартного хвоста
    "3 Зимостой 0044",            # год leading zeros ≤ 4 digits
])
def test_custom_month_form_is_our_era(cell):
    # Empty and «г.» tails both mean our era, nothing is asked back (D3).
    assert schema.parse_cell_date(cell, _CUSTOM) == schema.DateParse.ok(
        MonthDay(44, 1, 3), False
    )


@pytest.mark.parametrize("cell", [
    "3 Зимостой 44 г. до н.э.",    # spec «Игровая форма до нашей эры»
    "3 Зимостой 44 г до н э",     # the optional punctuation dots, as in the preset
    "3 зимостой  44 г.до н.э.",   # era suffix stays the sole era source
])
def test_custom_month_form_bc_tail(cell):
    assert schema.parse_cell_date(cell, _CUSTOM) == schema.DateParse.ok(
        MonthDay(44, 1, 3), True
    )


def test_custom_genitive_bridge_requires_the_nominative_in_the_calendar():
    # Spec «Родительный справочник требует имени в календаре»: «марта» is no
    # calendar name, but its nominative «март» is named month 2, so the old
    # reference word maps onto it; «апрель» is unnamed here, so «апреля» is
    # just an unknown name — endings are never guessed (D3).
    assert schema.parse_cell_date("5 марта 44 г. до н.э.", _CUSTOM) == schema.DateParse.ok(
        MonthDay(44, 2, 5), True
    )
    assert schema.parse_cell_date("5 марта 44", _CUSTOM) == schema.DateParse.ok(
        MonthDay(44, 2, 5), False
    )
    assert schema.parse_cell_date("5 апреля 44 г. до н.э.", _CUSTOM) == schema.DateParse.fail(
        schema.DateProblem("unknown_name", "апреля")
    )


@pytest.mark.parametrize(("cell", "code", "subject"), [
    ("3 Флорель 44", "unknown_name", "Флорель"),                # spec «Незнакомое имя месяца»
    ("3 флорель 44 г. до н.э.", "unknown_name", "флорель"),     # subject echoes the cell case
    ("3 Медожор 44", "intercalary_with_day", "Медожор"),        # spec «Номер дня при вставном имени»
    ("Зимостой 44", "month_without_day", "Зимостой"),           # D4: month named without its number
    ("марта 44", "month_without_day", "марта"),                 # the bridge feeds this gate too
    ("0 Зимостой 44", "out_of_range", "0"),                     # D4: 0 dies at the constructor,
    ("3 Зимостой 0", "out_of_range", "0"),                      # before any shift policy could see it
])
def test_custom_branch_refuses_with_the_subject_problem(cell, code, subject):
    parsed = schema.parse_cell_date(cell, _CUSTOM)
    assert parsed.ok is False
    assert parsed.problem == schema.DateProblem(code, subject)


def test_custom_day_beyond_month_length_is_not_a_problem():
    # Spec «Игровая дата с числом длиннее месяца переносится»: the parser hands
    # out the exact coordinate; clamping 31→30 (with the visible transfer row)
    # is the service's shift policy (D4), never the parser's.
    assert schema.parse_cell_date("31 Зимостой 44", _CUSTOM) == schema.DateParse.ok(
        MonthDay(44, 1, 31), False
    )


@pytest.mark.parametrize(("cell", "coord", "is_bc"), [
    ("Медожор 44", IntercalaryDay(44, 0), False),
    ("  медожор   44 ", IntercalaryDay(44, 0), False),          # case + space normalization
    ("Медожор 44 г.", IntercalaryDay(44, 0), False),
    ("Медожор 44 г. до н.э.", IntercalaryDay(44, 0), True),     # spec «Вставной день по имени»
    ("Пиггей 44", IntercalaryDay(44, 1), False),                # index = the rule's spec position (D10)
])
def test_custom_intercalary_form(cell, coord, is_bc):
    assert schema.parse_cell_date(cell, _CUSTOM) == schema.DateParse.ok(coord, is_bc)


@pytest.mark.parametrize(("cell", "code", "subject"), [
    ("Флорель 44", "unknown_name", "Флорель"),
    ("Флорель 44 г. до н.э.", "unknown_name", "Флорель"),
    ("Медожор 0", "out_of_range", "0"),
])
def test_custom_intercalary_form_problems(cell, code, subject):
    parsed = schema.parse_cell_date(cell, _CUSTOM)
    assert parsed.ok is False
    assert parsed.problem == schema.DateProblem(code, subject)


def test_cross_named_month_and_intercalary_are_split_by_the_day_number():
    # The validator allows one name as both a month and an intercalary rule;
    # the write form alone resolves the ambiguity (proposal: с номером — месяц,
    # без номера — вставной день).
    assert schema.parse_cell_date("3 Двойник 44", _DOUBLE) == schema.DateParse.ok(
        MonthDay(44, 1, 3), False
    )
    assert schema.parse_cell_date("Двойник 44", _DOUBLE) == schema.DateParse.ok(
        IntercalaryDay(44, 0), False
    )


@pytest.mark.parametrize("cell", [
    "31.12.2025",       # the forbidden «дд.мм.гггг» stays unparsable here too
    "не дата",
    "44 г. до н.э.",    # a year without any name is no form on either branch
    "3 Зимостой",       # name without a year
    "Ледокол",          # name without a year
    "   ",              # a whitespace-only cell normalizes away to empty
])
def test_custom_branch_unparsable_text_is_none_not_a_problem(cell):
    # Garbage the grammar never recognized stays None (spec «Битая дата начала»);
    # a DateProblem is only ever raised from inside a recognized game form.
    assert schema.parse_cell_date(cell, _CUSTOM) is None


def test_custom_branch_keeps_iso_signed_iso_and_native_coordinates():
    # Task 2.3 / spec: bare ISO, signed ISO and the native cell stay accepted
    # in the custom branch and pay out the same calendar coordinate.
    assert schema.parse_cell_date("2025-12-31", _CUSTOM) == schema.DateParse.ok(
        MonthDay(2025, 12, 31), False
    )
    assert schema.parse_cell_date(" -0500-01-01 ", _CUSTOM) == schema.DateParse.ok(
        MonthDay(500, 1, 1), True
    )
    assert schema.parse_cell_date(date(1820, 5, 1), _CUSTOM) == schema.DateParse.ok(
        MonthDay(1820, 5, 1), False
    )
    assert schema.parse_cell_date(datetime(2025, 12, 31, 10, 30), _CUSTOM) == (
        schema.DateParse.ok(MonthDay(2025, 12, 31), False)
    )
    # Numbers of an unreadable ISO shape stay None, never become problems.
    assert schema.parse_cell_date("-0000-01-01", _CUSTOM) is None
    assert schema.parse_cell_date("-0044-13-01", _CUSTOM) is None


def test_parse_rating_valid():
    assert schema.parse_cell_rating(4) == 4
    assert schema.parse_cell_rating("3") == 3
    assert schema.parse_cell_rating(5.0) == 5


def test_parse_rating_empty_is_none():
    assert schema.parse_cell_rating(None) is None
    assert schema.parse_cell_rating("") is None
    assert schema.parse_cell_rating("  ") is None


@pytest.mark.parametrize("bad", ["abc", "0", "6", -1, 3.7, "4.5", True, object()])
def test_parse_rating_garbage_raises(bad):
    with pytest.raises(ValueError):
        schema.parse_cell_rating(bad)


def test_parse_link_cell_strips_and_skips_empty_segments():
    # Task edge-case: " а;б; ;в "
    assert schema.parse_link_cell(" а;б; ;в ") == ["а", "б", "в"]


def test_parse_link_cell_edge_cases():
    assert schema.parse_link_cell(None) == []
    assert schema.parse_link_cell("") == []
    assert schema.parse_link_cell("; ; ;") == []
    assert schema.parse_link_cell("Иван") == ["Иван"]
    # Order and duplicates preserved; dedup is the apply pass' job.
    assert schema.parse_link_cell("б;а;б") == ["б", "а", "б"]
