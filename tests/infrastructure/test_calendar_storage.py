"""Storage-format carrier tests for ``app.infrastructure.calendar_storage`` —
the codec sections moved verbatim from ``tests/domain/test_game_calendar.py``
with the code itself (task 6.6); assertions unchanged.
"""
import inspect
import json
from dataclasses import FrozenInstanceError, fields
from datetime import date

import pytest

from app.domain.game_calendar import (
    DEFAULT_MONTH_NAMES,
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    InvalidGameDateError,
    MonthDay,
    MonthSpec,
    ShiftReason,
    SpecProblem,
    StandardCalendar,
    StubCalendar,
    as_game_coord,
    classify,
    shift_invalid,
)
from app.infrastructure.calendar_storage import (
    CALENDAR_DRAFT_VERSION,
    CALENDAR_STORAGE_VERSION,
    DRAFT_STAGE_MONTHS,
    DRAFT_STAGE_PREVIEW,
    DRAFT_STAGE_WEEK,
    DRAFT_STAGES,
    CalendarCorrupted,
    CalendarDecoded,
    CalendarDraft,
    CoordCorrupted,
    CoordDecoded,
    DraftCorrupted,
    DraftDecoded,
    decode_calendar,
    decode_coord,
    decode_draft,
    encode_calendar,
    encode_coord,
    encode_draft,
)


def make_months(*names_and_lengths: tuple[str, int]) -> tuple[MonthSpec, ...]:
    return tuple(MonthSpec(name, length) for name, length in names_and_lengths)


BASE_MONTHS = make_months(("Зимостой", 30), ("Талолист", 50), ("Сухочивень", 20))
BASE_WEEK = ("Восход", "Тень", "Полдень", "Закат")


def base_spec(
    months: tuple[MonthSpec, ...] = BASE_MONTHS,
    week_names: tuple[str, ...] = BASE_WEEK,
    intercalary: tuple[IntercalarySpec, ...] = (),
) -> CalendarSpec:
    """A small valid spec; each failing case overrides exactly one facet."""
    return CalendarSpec(months=months, week_names=week_names, intercalary=intercalary)


def codes_of(problems) -> set[str]:
    return {problem.code for problem in problems}

# ── кодек хранения: стандартный пресет (design D1) ──────────────────────


class TestCodecStandardPreset:
    """C2 task 1.2 / сценарий «Пресет с переименованными месяцами» +
    дизайн-нормализация «пустой словарь имён → нет поля»."""

    def test_plain_preset_encodes_without_any_payload_fields(self):
        assert json.loads(encode_calendar(StandardCalendar())) == {
            "v": 1, "kind": "standard",
        }

    def test_empty_or_default_equal_override_normalizes_to_no_field(self):
        # «про запас» не пишем: пустое переопределение и переопределение,
        # побайтово равное дефолту, не порождают поля month_names
        all_default = {number: DEFAULT_MONTH_NAMES[number] for number in range(1, 13)}
        for names in ({}, {5: "Май"}, all_default):
            payload = json.loads(encode_calendar(StandardCalendar(month_names=names)))
            assert "month_names" not in payload
            assert payload == {"v": 1, "kind": "standard"}

    def test_override_is_written_as_string_month_numbers(self):
        raw = encode_calendar(StandardCalendar(month_names={3: "Медвежарь"}))
        assert json.loads(raw) == {
            "v": 1,
            "kind": "standard",
            "month_names": {"3": "Медвежарь"},
        }
        assert "\\u" not in raw  # ensure_ascii=False — кириллица ложится как есть

    def test_plain_preset_round_trips_to_the_default_names(self):
        decoded = decode_calendar(encode_calendar(StandardCalendar()))
        assert isinstance(decoded, CalendarDecoded)
        assert decoded.calendar.month_names == DEFAULT_MONTH_NAMES

    def test_override_round_trip_keeps_names_and_keys(self):
        original = StandardCalendar(month_names={3: "Медвежарь"})
        decoded = decode_calendar(encode_calendar(original))
        assert isinstance(decoded, CalendarDecoded)
        restored = decoded.calendar
        assert restored.month_names == original.month_names
        for is_bc in (False, True):
            for coord in (MonthDay(2024, 3, 9), MonthDay(1, 1, 1)):
                assert restored.to_key(coord, is_bc) == original.to_key(coord, is_bc)


# ── кодек хранения: кастомная спека, круговой проход ────────────────────


CODEC_SPEC = base_spec(
    months=make_months(("Зимостой", 30), ("Талолист", 50), ("Сухочивень", 20)),
    week_names=BASE_WEEK,
    intercalary=(
        IntercalarySpec("Гром", 2),
        IntercalarySpec("Эхо", 2),
        IntercalarySpec("Тишина", 3),
    ),
)  # все три facet'а спеки сразу: месяцы разной длины, неделя, правила при хостах


class TestCodecCustomRoundTrip:
    """C2 task 1.2 / сценарий «Круговой проход через хранилище»: сохранённая
    спека равна прочитанной, ключи совпадают побитово."""

    def test_full_spec_fields_are_written_one_for_one(self):
        raw = json.loads(encode_calendar(CustomCalendar(CODEC_SPEC)))
        assert raw == {
            "v": 1,
            "kind": "custom",
            "months": [
                {"name": "Зимостой", "length": 30},
                {"name": "Талолист", "length": 50},
                {"name": "Сухочивень", "length": 20},
            ],
            "week_names": ["Восход", "Тень", "Полдень", "Закат"],
            "intercalary": [
                {"name": "Гром", "after_month": 2},
                {"name": "Эхо", "after_month": 2},
                {"name": "Тишина", "after_month": 3},
            ],
        }

    def test_saved_spec_is_equal_to_the_read_one(self):
        original = CustomCalendar(CODEC_SPEC)
        decoded = decode_calendar(encode_calendar(original))
        assert isinstance(decoded, CalendarDecoded)
        restored = decoded.calendar
        assert isinstance(restored, CustomCalendar)
        assert restored.spec == original.spec == CODEC_SPEC

    def test_restored_calendar_keys_are_bit_identical_in_both_eras(self):
        original = CustomCalendar(CODEC_SPEC)
        decoded = decode_calendar(encode_calendar(original))
        restored = decoded.calendar
        probes = [
            MonthDay(1, 1, 1), MonthDay(44, 2, 50), MonthDay(9999, 3, 20),
            IntercalaryDay(44, 0), IntercalaryDay(44, 1), IntercalaryDay(9999, 2),
        ]
        for coord in probes:
            for is_bc in (False, True):
                key = original.to_key(coord, is_bc)
                assert restored.to_key(coord, is_bc) == key
                assert restored.from_key(key, is_bc) == coord

    def test_empty_intercalary_round_trips_as_empty(self):
        original = CustomCalendar(base_spec())  # intercalary = ()
        decoded = decode_calendar(encode_calendar(original))
        assert decoded.calendar.spec.intercalary == ()

    def test_encode_is_deterministic_across_a_decode_cycle(self):
        raw_once = encode_calendar(CustomCalendar(CODEC_SPEC))
        decoded = decode_calendar(raw_once)
        assert encode_calendar(decoded.calendar) == raw_once


# ── кодек хранения: повреждённые значения никогда не бросают ────────────

CODEC_CORRUPT_CASES = [
    # ── битый JSON ────────────────────────────────────────────────────────
    pytest.param("{not json at all", {"corrupt_json"}, id="broken-json"),
    pytest.param("", {"corrupt_json"}, id="empty-string"),
    pytest.param(None, {"corrupt_json"}, id="value-is-not-a-string"),
    # ── распарсилось, но это не объект-календаря ──────────────────────────
    pytest.param("[1, 2]", {"corrupt_shape"}, id="json-array-not-object"),
    pytest.param('"просто строка"', {"corrupt_shape"}, id="json-string-not-object"),
    # ── версия формата ────────────────────────────────────────────────────
    pytest.param('{"kind": "standard"}', {"unknown_version"}, id="missing-v"),
    pytest.param('{"v": 2, "kind": "standard"}', {"unknown_version"}, id="future-v"),
    pytest.param('{"v": 0, "kind": "custom"}', {"unknown_version"}, id="zero-v"),
    # ── дискриминатор kind ────────────────────────────────────────────────
    pytest.param('{"v": 1}', {"corrupt_shape"}, id="missing-kind"),
    pytest.param('{"v": 1, "kind": "lunar"}', {"corrupt_shape"}, id="unknown-kind"),
    # ── standard: битый month_names ───────────────────────────────────────
    pytest.param(
        '{"v": 1, "kind": "standard", "month_names": []}',
        {"corrupt_shape"}, id="names-not-an-object",
    ),
    pytest.param(
        '{"v": 1, "kind": "standard", "month_names": {"3": 7}}',
        {"corrupt_shape"}, id="name-is-not-a-string",
    ),
    pytest.param(
        '{"v": 1, "kind": "standard", "month_names": {"январь": "X"}}',
        {"corrupt_shape"}, id="name-key-is-not-a-month-number",
    ),
    # ── custom: поля не списки ────────────────────────────────────────────
    pytest.param(
        '{"v": 1, "kind": "custom", "week_names": [], "intercalary": []}',
        {"corrupt_shape"}, id="custom-without-months",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": {}, "week_names": [], "intercalary": []}',
        {"corrupt_shape"}, id="months-is-not-a-list",
    ),
    # ── custom: битые записи month/week/intercalary ───────────────────────
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [30],'
        ' "week_names": ["a", "b"], "intercalary": []}',
        {"corrupt_shape"}, id="month-entry-is-not-an-object",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": 5, "length": 30}],'
        ' "week_names": ["a", "b"], "intercalary": []}',
        {"corrupt_shape"}, id="month-name-is-not-a-string",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": true}],'
        ' "week_names": ["a", "b"], "intercalary": []}',
        {"corrupt_shape"}, id="month-length-is-a-bool",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": 3}],'
        ' "week_names": [1], "intercalary": []}',
        {"corrupt_shape"}, id="week-name-is-not-a-string",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": 3}],'
        ' "week_names": ["a", "b"], "intercalary": [{"name": "Гром"}]}',
        {"corrupt_shape"}, id="intercalary-entry-without-host",
    ),
    pytest.param(
        '{"v": 1, "kind": "custom", "months": [{"name": "x", "length": 3}],'
        ' "week_names": ["a", "b"], "intercalary": [3]}',
        {"corrupt_shape"}, id="intercalary-entry-is-not-an-object",
    ),
]


class TestCodecCorruptedValue:
    """C2 task 1.2 / требование «Повреждённое значение календарь-ключа»,
    часть кодека: битое значение никогда не бросает — оно отдаёт полный
    список машинных причин (дальше их локализирует presentation, D4)."""

    @pytest.mark.parametrize(("raw", "expected_codes"), CODEC_CORRUPT_CASES)
    def test_broken_values_decode_to_corruption_not_exceptions(self, raw, expected_codes):
        result = decode_calendar(raw)
        assert isinstance(result, CalendarCorrupted)
        assert codes_of(result.reasons) == expected_codes

    def test_reasons_are_specproblem_shaped_machine_codes(self):
        result = decode_calendar('{"v": 1}')
        (reason,) = result.reasons
        assert isinstance(reason, SpecProblem)
        assert isinstance(reason.code, str) and reason.code
        assert isinstance(reason.message, str) and reason.message  # всегда есть деталь

    def test_broken_custom_spec_reports_kernel_validation_reason(self):
        # сценарий «Битая кастомная спека»: вставной день ссылается на
        # несуществующий месяц — причина из валидации ядра, не заглушка
        result = decode_calendar(
            '{"v": 1, "kind": "custom",'
            ' "months": [{"name": "Короткий", "length": 5}],'
            ' "week_names": ["а", "б"],'
            ' "intercalary": [{"name": "Гром", "after_month": 2}]}'
        )
        assert isinstance(result, CalendarCorrupted)
        assert codes_of(result.reasons) == {"intercalary_unknown_month"}

    def test_kernel_reports_every_spec_reason_not_only_the_first(self):
        # полный список причин D6 проходит через кодек без потерь
        result = decode_calendar(
            '{"v": 1, "kind": "custom",'
            ' "months": [{"name": "", "length": 0}],'
            ' "week_names": ["а"],'
            ' "intercalary": []}'
        )
        assert isinstance(result, CalendarCorrupted)
        assert codes_of(result.reasons) == {
            "empty_month_name", "month_length_below_min", "week_too_short",
        }

    def test_encode_refuses_a_calendar_without_a_storage_shape(self):
        # третий реализатор протокола храниться пока не умеет (D1: форма
        # есть только у пресета и кастома; мастер — C4)
        with pytest.raises(TypeError):
            encode_calendar(StubCalendar())


# ═════════════════════════════════════════════════════════════════════════
# C3a (wire-game-calendar-coordinates) task group 1.1 — доменный кодек
# координаты: spec «Доменный кодек хранимого представления координаты»
# и design D2: инъективный точный цикл "M:год:месяц:день" / "I:год:индекс",
# машиночитаемые причины вместо исключений, существование проверяет не
# кодек, а чистая политика сдвига
# ═════════════════════════════════════════════════════════════════════════

COORD_SWEEP_SPEC = base_spec(
    intercalary=(IntercalarySpec("Гром", 2), IntercalarySpec("Маска", 3)),
)  # 30+50+20 дней + два вставных: году есть и координаты рода M, и рода I


class TestCoordCodecExactCycle:
    """C3a task 1.1 / сценарий «Точный цикл координаты»: декодирование
    результата возвращает ровно ту же координату обоих родов; эра в текст не
    входит (D3), а ключ каждой эры переживает цикл побитово."""

    ROUND_TRIP_COORDS = [
        pytest.param(MonthDay(1, 1, 1), id="ad-epoch"),
        pytest.param(MonthDay(44, 3, 5), id="bc-year-44"),
        pytest.param(MonthDay(2024, 2, 29), id="leap-feb-29"),
        pytest.param(MonthDay(9999, 12, 31), id="last-day-of-scale"),
        pytest.param(IntercalaryDay(1, 0), id="first-intercalary"),
        pytest.param(IntercalaryDay(44, 2), id="bc-intercalary"),
        pytest.param(IntercalaryDay(9999, 12), id="far-index"),
    ]

    @pytest.mark.parametrize("coord", ROUND_TRIP_COORDS)
    def test_cycle_returns_exactly_the_original_coordinate(self, coord):
        text = encode_coord(coord)
        decoded = decode_coord(text)
        assert isinstance(decoded, CoordDecoded)
        assert decoded.coord == coord
        # канон без ведущих нулей и лишних полей фиксируется round-trip'ом
        assert encode_coord(decoded.coord) == text

    @pytest.mark.parametrize(
        "coord",
        [
            pytest.param(MonthDay(1, 1, 1), id="ad-epoch"),
            pytest.param(MonthDay(44, 3, 5), id="bc-year-44"),
            pytest.param(MonthDay(2024, 2, 29), id="leap-feb-29"),
            pytest.param(MonthDay(9999, 12, 31), id="last-day-of-scale"),
        ],
    )
    @pytest.mark.parametrize("is_bc", [False, True], ids=["ad", "bc"])
    def test_both_era_keys_survive_the_cycle_under_the_preset(self, coord, is_bc):
        # текста на оба применения одинаков — эру различает только to_key
        preset = StandardCalendar()
        key = preset.to_key(coord, is_bc)
        restored = decode_coord(encode_coord(coord)).coord
        assert preset.to_key(restored, is_bc) == key
        assert preset.from_key(key, is_bc) == restored

    def test_intercalary_key_survives_the_cycle_under_custom(self):
        custom = CustomCalendar(COORD_SWEEP_SPEC)
        coord = IntercalaryDay(44, 1)
        for is_bc in (False, True):
            key = custom.to_key(coord, is_bc)
            restored = decode_coord(encode_coord(coord)).coord
            assert custom.to_key(restored, is_bc) == key
            assert custom.from_key(key, is_bc) == restored

    def test_text_is_the_discriminated_plain_number_format(self):
        # design D2: дискриминатор рода + десятичные числа как есть
        assert encode_coord(MonthDay(44, 3, 5)) == "M:44:3:5"
        assert encode_coord(MonthDay(1, 1, 1)) == "M:1:1:1"
        assert encode_coord(IntercalaryDay(44, 0)) == "I:44:0"
        assert set(encode_coord(MonthDay(9999, 12, 31))) <= set(".-:0123456789M")
        assert "is_bc" not in inspect.signature(encode_coord).parameters

    def test_leading_zeros_parse_but_the_encoding_stays_canonical(self):
        # рукописная правка базы переживёт чтение, а повторная запись
        # вернётся каноническим текстом того же round-trip'а
        decoded = decode_coord("M:044:03:05")
        assert isinstance(decoded, CoordDecoded)
        assert decoded.coord == MonthDay(44, 3, 5)
        assert encode_coord(decoded.coord) == "M:44:3:5"


class TestCoordCodecInjective:
    """C3a task 1.1 / тот же сценарий, вторая половина: разные координаты
    дают разные тексты — ловушки «цифры переехали между полями» и оба рода
    сразу не сталкиваются."""

    COLLISION_TRAPS = [
        MonthDay(1, 11, 1), MonthDay(11, 1, 1), MonthDay(1, 1, 11),
        MonthDay(2, 2, 2), MonthDay(22, 2, 2), MonthDay(2, 22, 2),
        MonthDay(4, 4, 4), MonthDay(44, 4, 4), MonthDay(4, 44, 44),
        IntercalaryDay(1, 0), IntercalaryDay(10, 0), IntercalaryDay(1, 10),
        IntercalaryDay(11, 1), IntercalaryDay(111, 1),
        MonthDay(1, 1, 1), MonthDay(11, 11, 11),
    ]

    def test_neighbours_by_digits_never_share_a_text(self):
        # цифры, переехавшие между полями, и разные роды при равных числах
        # обязаны давать разные тексты
        unique_coords = list(dict.fromkeys(self.COLLISION_TRAPS))
        texts = [encode_coord(coord) for coord in unique_coords]
        assert len(set(texts)) == len(unique_coords)

    def test_full_custom_year_sweep_is_pairwise_distinct_and_round_trips(self):
        # весь год кастома разом: рow M-координат месяцами + все вставные слоты
        custom = CustomCalendar(COORD_SWEEP_SPEC)
        base = custom.to_key(MonthDay(44, 1, 1))
        coords = [custom.from_key(base + offset) for offset in range(custom.year_length)]
        assert len(coords) == custom.year_length == 102
        assert len(set(coords)) == len(coords)
        texts = [encode_coord(coord) for coord in coords]
        assert len(set(texts)) == len(coords)  # сценарий: разные координаты → разные тексты
        for coord, text in zip(coords, texts):
            decoded = decode_coord(text)
            assert isinstance(decoded, CoordDecoded)
            assert decoded.coord == coord


class TestCoordCodecCorruptedText:
    """C3a task 1.1 / сценарий «Чужой текст отвечает причинами»: ни один
    неразбираемый текст не бросает — только полный набор машинных причин по
    образцу календарь-кодека (SpecProblem, не локалиzaция)."""

    CORRUPT_CASES = [
        pytest.param("", {"empty_coord"}, id="empty-text"),
        pytest.param(None, {"not_a_string"}, id="value-is-not-a-string"),
        pytest.param(404, {"not_a_string"}, id="value-is-a-number"),
        # ── без дискриминатора рода / неизвестный дискриминатор ──────────
        pytest.param("44:3:5", {"unknown_kind"}, id="missing-kind-discriminator"),
        pytest.param("сорок четыре", {"unknown_kind"}, id="no-separator-at-all"),
        pytest.param("L:44:3:5", {"unknown_kind"}, id="unknown-kind"),
        pytest.param("m:44:3:5", {"unknown_kind"}, id="case-is-significant"),
        pytest.param(":44:3:5", {"unknown_kind"}, id="empty-kind"),
        # ── неполный текст ────────────────────────────────────────────────
        pytest.param("M:44:3", {"incomplete_coord"}, id="month-day-missing-field"),
        pytest.param("I:44", {"incomplete_coord"}, id="intercalary-missing-index"),
        pytest.param("M:", {"incomplete_coord", "non_numeric_field"},
                     id="incomplete-and-non-numeric-together"),
        # ── нечисловые поля ───────────────────────────────────────────────
        pytest.param("M:a:b:c", {"non_numeric_field"}, id="all-fields-non-numeric"),
        pytest.param("M:44:x:5", {"non_numeric_field"}, id="month-is-not-a-number"),
        pytest.param("I:44:второй", {"non_numeric_field"}, id="index-is-not-a-number"),
        pytest.param("M:::", {"non_numeric_field"}, id="all-fields-empty"),
        # ── лишние поля ───────────────────────────────────────────────────
        pytest.param("M:44:3:5:9", {"too_many_fields"}, id="extra-field"),
    ]

    @pytest.mark.parametrize(("raw", "expected_codes"), CORRUPT_CASES)
    def test_strange_texts_answer_reasons_not_exceptions(self, raw, expected_codes):
        result = decode_coord(raw)
        assert isinstance(result, CoordCorrupted)
        assert codes_of(result.reasons) == expected_codes
        assert all(isinstance(problem, SpecProblem) for problem in result.reasons)

    @pytest.mark.parametrize(("raw", "expected_codes"), CORRUPT_CASES)
    def test_every_reason_carries_a_detail_message(self, raw, expected_codes):
        result = decode_coord(raw)
        assert result.reasons  # причин хотя бы одна
        for problem in result.reasons:
            assert isinstance(problem.code, str) and problem.code
            assert isinstance(problem.message, str) and problem.message

    def test_encode_refuses_a_value_that_is_not_a_coordinate(self):
        # вне двух D3-родов хранимой формы нет — по образцу encode_calendar
        with pytest.raises(TypeError):
            encode_coord(date(2026, 9, 20))
        with pytest.raises(TypeError):
            encode_coord("M:1:1:1")


class TestCoordCodecResultShapes:
    """Среза результатов кодекса — те же frozen-доменные формы, что у
    календарь-кодека (design D2 «тот же контракт»)."""

    def test_decoded_exposes_only_the_coordinate_and_is_frozen(self):
        assert {f.name for f in fields(CoordDecoded)} == {"coord"}
        result = CoordDecoded(MonthDay(1, 1, 1))
        with pytest.raises(FrozenInstanceError):
            result.coord = MonthDay(2, 1, 1)  # type: ignore[misc]

    def test_corrupted_exposes_only_reasons_and_is_frozen(self):
        assert {f.name for f in fields(CoordCorrupted)} == {"reasons"}
        result = decode_coord("M:44:3")
        assert isinstance(result, CoordCorrupted)
        with pytest.raises(FrozenInstanceError):
            result.reasons = ()  # type: ignore[misc]


class TestCoordCodecNeverChecksExistence:
    """C3a task 1.1: кодек отвечает за разбор и форму, существование — дело
    чистой политики сдвига (spec «Доменный кодек…»)."""

    NONEXISTENT_COORDS = [
        pytest.param(MonthDay(2026, 13, 40), id="month-13-day-40"),
        pytest.param(MonthDay(44, 0, 0), id="zero-month-and-day"),
        pytest.param(IntercalaryDay(44, 99), id="index-beyond-any-spec"),
        pytest.param(MonthDay(0, 99, 99), id="year-zero-absurd-fields"),
    ]

    @pytest.mark.parametrize("coord", NONEXISTENT_COORDS)
    def test_absurd_coordinates_still_round_trip_exactly(self, coord):
        # ни один календарь в декод не заглядывает: ровно та же координата
        assert decode_coord(encode_coord(coord)).coord == coord

    def test_existence_judges_the_policy_not_the_codec(self):
        coord = MonthDay(2026, 13, 40)
        assert decode_coord(encode_coord(coord)).coord == coord  # кодек принял
        with pytest.raises(InvalidGameDateError):
            StandardCalendar().to_key(coord)                     # ядро отказало
        assert classify(coord, StandardCalendar()) is ShiftReason.MONTH_OUT_OF_RANGE
        assert shift_invalid(coord, StandardCalendar())[0] == MonthDay(2026, 12, 31)


# ── C4: черновик мастера (task 4.1, design D6) ────────────────────────────


#: Спека-сквозняк: та же форма, что пишет основной ключ kind=custom, но с
#: вставным днём — черновик обязан нести все три facet'а без потерь.
DRAFT_SPEC = base_spec(
    months=make_months(("Черновершь", 12), ("Разливань", 18)),
    week_names=("Буд", "Ведь", "Творец", "Грозник", "Светлай"),
    intercalary=(IntercalarySpec("Гром", 1),),
)


def draft_body(spec: CalendarSpec, stage: str = DRAFT_STAGE_MONTHS, **envelope) -> dict:
    """Собрать JSON-конверт черновика: тело спеки отдаёт основной кодек,
    чтобы тесты битого черновика говорили на том же формате, что пишет app."""
    payload = {
        "v": CALENDAR_DRAFT_VERSION,
        "spec": json.loads(encode_calendar(CustomCalendar(spec))),
        "stage": stage,
    }
    payload.update(envelope)
    return payload


class TestDraftCodecRoundTrip:
    """Круговой проход design D6: версия + спека + индекс ступени возвращаются
    ровно теми же, а тело спеки побайтово совпадает с телом основного ключа."""

    def test_envelope_shape_is_version_spec_and_stage(self):
        raw = encode_draft(CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_MONTHS))
        payload = json.loads(raw)
        assert payload == {
            "v": CALENDAR_DRAFT_VERSION,
            "spec": json.loads(encode_calendar(CustomCalendar(DRAFT_SPEC))),
            "stage": DRAFT_STAGE_MONTHS,
        }
        assert "\\u" not in raw  # ensure_ascii=False — спека читается глазами

    @pytest.mark.parametrize("stage", DRAFT_STAGES)
    def test_every_stage_survives_the_cycle(self, stage):
        draft = CalendarDraft(spec=DRAFT_SPEC, stage=stage)
        decoded = decode_draft(encode_draft(draft))
        assert isinstance(decoded, DraftDecoded)
        assert decoded.draft == draft

    def test_custom_body_rides_inside_the_draft_byte_identical(self):
        # «то же тело, что у custom-значения game_calendar» — переиспользование
        # encode_calendar/decode_calendar, а не второй формат хранения
        draft = CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_WEEK)
        inner = json.loads(encode_draft(draft))["spec"]
        assert encode_calendar(CustomCalendar(DRAFT_SPEC)) == json.dumps(
            inner, ensure_ascii=False
        )

    def test_round_trip_keys_are_bit_identical_in_both_eras(self):
        original = CustomCalendar(DRAFT_SPEC)
        decoded = decode_draft(encode_draft(CalendarDraft(original.spec, DRAFT_STAGE_PREVIEW)))
        assert isinstance(decoded, DraftDecoded)
        restored = CustomCalendar(decoded.draft.spec)
        for coord in (MonthDay(1, 1, 1), MonthDay(9999, 2, 18), IntercalaryDay(44, 0)):
            for is_bc in (False, True):
                key = original.to_key(coord, is_bc)
                assert restored.to_key(coord, is_bc) == key
                assert restored.from_key(key, is_bc) == coord

    def test_encode_is_deterministic_across_a_decode_cycle(self):
        raw_once = encode_draft(CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_PREVIEW))
        decoded = decode_draft(raw_once)
        assert isinstance(decoded, DraftDecoded)
        assert encode_draft(decoded.draft) == raw_once

    def test_draft_and_main_key_are_the_separate_shapes(self):
        # основной ключ не содержит stage, черновик не умеет kind=standard —
        # перепутать их местами можно только написав JSON руками
        assert "stage" not in json.loads(encode_calendar(StandardCalendar()))
        draft = CalendarDraft(spec=base_spec(), stage=DRAFT_STAGE_WEEK)
        assert json.loads(encode_draft(draft))["spec"]["kind"] == "custom"

    def test_draft_form_is_a_frozen_pair_of_spec_and_stage(self):
        assert {f.name for f in fields(CalendarDraft)} == {"spec", "stage"}
        draft = CalendarDraft(spec=DRAFT_SPEC, stage=DRAFT_STAGE_WEEK)
        with pytest.raises(FrozenInstanceError):
            draft.spec = base_spec()  # type: ignore[misc]

    def test_stage_is_not_interpreted_beyond_being_a_known_marker(self):
        # индекс ступени — данные черновика, а не условие кодирования:
        # предпросмотр собирается из той же спеки, что и месяцы
        for stage in (DRAFT_STAGE_WEEK, DRAFT_STAGE_MONTHS, DRAFT_STAGE_PREVIEW):
            assert decode_draft(
                encode_draft(CalendarDraft(spec=base_spec(), stage=stage))
            ).draft.stage == stage


class TestDraftCodecWriteGuards:
    """Писатель строже читателя: в хранилище не попадает ни битая спека,
    ни неизвестная ступень — и то и другое拒绝 на глазах у мастера."""

    def test_unknown_stage_refuses_to_be_written(self):
        with pytest.raises(ValueError, match="unknown wizard draft stage"):
            encode_draft(CalendarDraft(spec=base_spec(), stage="interstice"))

    def test_invalid_spec_refuses_through_the_kernel_validation(self):
        broken = base_spec(
            months=make_months(("Первый", 5), ("Первый", 6)),
        )  # дубликат имени месяца — ядро reject'ит спеку целиком
        with pytest.raises(ValueError, match="duplicate month name"):
            encode_draft(CalendarDraft(spec=broken, stage=DRAFT_STAGE_MONTHS))


DRAFT_CORRUPT_CASES = [
    # ── битый конверт ──────────────────────────────────────────────────────
    pytest.param("{это не json", {"corrupt_json"}, id="broken-json"),
    pytest.param("", {"corrupt_json"}, id="empty-string"),
    pytest.param(None, {"corrupt_json"}, id="value-is-not-a-string"),
    pytest.param("[1, 2]", {"corrupt_shape"}, id="json-array-not-object"),
    pytest.param('"черновик"', {"corrupt_shape"}, id="json-string-not-object"),
    # ── версия формата черновика ──────────────────────────────────────────
    pytest.param(
        {"spec": {}, "stage": DRAFT_STAGE_WEEK}, {"unknown_version"}, id="missing-v"
    ),
    pytest.param(
        draft_body(base_spec(), v=2), {"unknown_version"}, id="future-v"
    ),
    # ── тело спеки ────────────────────────────────────────────────────────
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "stage": DRAFT_STAGE_WEEK},
        {"corrupt_shape"},
        id="no-spec-field",
    ),
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "spec": [], "stage": DRAFT_STAGE_WEEK},
        {"corrupt_shape"},
        id="spec-not-an-object",
    ),
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "spec": json.loads(encode_calendar(StandardCalendar())),
         "stage": DRAFT_STAGE_WEEK},
        {"corrupt_shape"},
        id="spec-is-the-standard-preset",
    ),
    # ── ступень ───────────────────────────────────────────────────────────
    pytest.param(
        {"v": CALENDAR_DRAFT_VERSION, "spec": json.loads(
            encode_calendar(CustomCalendar(base_spec())))},
        {"corrupt_shape"},
        id="no-stage-field",
    ),
    pytest.param(
        draft_body(base_spec(), stage="interstice"),
        {"corrupt_shape"},
        id="unknown-stage",
    ),
    pytest.param(
        draft_body(base_spec(), stage=3), {"corrupt_shape"}, id="stage-is-not-a-string"
    ),
]


class TestDraftCodecCorruptedDraft:
    """Требование «Битой черновик — как его нет»: кодекс никогда не бросает и
    отдаёт машинные причины, из которых вызывающий делает вывод «черновика
    нет» (сервис логирует, мастер начинает сызнова)."""

    @pytest.mark.parametrize(("raw", "expected_codes"), DRAFT_CORRUPT_CASES)
    def test_unreadable_values_answer_reasons_not_exceptions(self, raw, expected_codes):
        # dict/list-параметры — это заготовки конвертов; строка (и None)
        # уходит в кодекс как есть, ровно так, как их видит хранилище
        stored = json.dumps(raw) if isinstance(raw, (dict, list)) else raw
        result = decode_draft(stored)
        assert isinstance(result, DraftCorrupted)
        assert codes_of(result.reasons) == expected_codes
        assert all(
            isinstance(problem, SpecProblem)
            and problem.code
            and problem.message
            for problem in result.reasons
        )

    def test_uncodable_value_type_never_reaches_the_caller_as_a_crash(self):
        assert isinstance(decode_draft(None), DraftCorrupted)
        assert codes_of(decode_draft(None).reasons) == {"corrupt_json"}

    @pytest.mark.parametrize(
        ("spec", "expected_codes"),
        [
            pytest.param(
                base_spec(
                    months=make_months(("Первый", 3)),
                    intercalary=(IntercalarySpec("Гром", 2),),
                ),
                {"intercalary_unknown_month"},
                id="kernel-rejects-the-half-built-spec",
            ),
            pytest.param(
                base_spec(months=(), week_names=("а", "б")),
                {"no_months"},
                id="months-not-entered-yet",
            ),
            pytest.param(
                base_spec(
                    months=make_months(("", 5), ("Второй", -1)),
                    week_names=("а",),
                ),
                {"empty_month_name", "month_length_below_min", "week_too_short"},
                id="every-kernel-reason-survives",
            ),
        ],
    )
    def test_a_stored_but_invalid_spec_is_the_same_absence(self, spec, expected_codes):
        # валидация тела идёт тем же _decode_calendar_data, что и у основного
        # ключа: черновик не может «протащить» спеку, которую не принял бы он
        body = {
            "v": CALENDAR_DRAFT_VERSION,
            "spec": {
                "v": CALENDAR_STORAGE_VERSION,
                "kind": "custom",
                "months": [
                    {"name": m.name, "length": m.length} for m in spec.months
                ],
                "week_names": list(spec.week_names),
                "intercalary": [
                    {"name": r.name, "after_month": r.after_month}
                    for r in spec.intercalary
                ],
            },
            "stage": DRAFT_STAGE_MONTHS,
        }
        result = decode_draft(json.dumps(body))
        assert isinstance(result, DraftCorrupted)
        assert codes_of(result.reasons) == expected_codes


@pytest.fixture(params=[30, "M:44:3:5", object()], ids=["int", "coord-text", "object"])
def any_non_coord(request):
    """Anything that is neither a coordinate, nor a date, nor absence."""
    return request.param


class TestDraftCodecCorruptedValueBoundary:
    """Кодек черновика стоит поверх D3-координатного контракта: координата в
    спеке — не параметр, а часть тела, поэтому проверка рода координаты
    живёт в `as_game_coord`, которую черновик обязан унаследовать без мягкости
    (design D6: «spec — то же тело» ⇒ те же отказы)."""

    def test_non_coordinate_values_refuse_rather_than_become_days(
        self, any_non_coord
    ):
        with pytest.raises(TypeError):
            as_game_coord(any_non_coord)

    def test_dates_and_coordinates_pass_through_the_same_gate(self):
        assert as_game_coord(date(2024, 3, 9)) == MonthDay(2024, 3, 9)
        coord = MonthDay(44, 2, 1)
        assert as_game_coord(coord) is coord
        assert as_game_coord(None) is None  # absence is not a coordinate carrier
