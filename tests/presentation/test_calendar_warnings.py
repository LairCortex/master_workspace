"""Маппинг кодов повреждения календарь-ключа на русские фразы (задача 5.1).

Чистые функции без Qt (требование задачи): проверка словаря
``calendar_warnings`` и тела предупреждающего окна для кодов кодека
(``corrupt_json``/``corrupt_shape``), валидации спеки и неизвестных случаев."""
from app.domain.game_calendar import SpecProblem
from app.presentation.utils.calendar_warnings import (
    GENERIC_CORRUPT_PHRASE,
    MONTH_WARNING_TITLE,
    calendar_corruption_body,
    corruption_reason_phrase,
)


def test_known_codes_get_specific_russian_phrases():
    assert corruption_reason_phrase("corrupt_json") != GENERIC_CORRUPT_PHRASE
    assert corruption_reason_phrase("corrupt_shape") != GENERIC_CORRUPT_PHRASE
    assert corruption_reason_phrase("intercalary_unknown_month") == (
        "вставной день ссылается на несуществующий месяц"
    )
    assert "JSON" in corruption_reason_phrase("corrupt_json")


def test_all_validation_codes_are_mapped_in_non_latin():
    validation_codes = (
        "no_months",
        "empty_month_name",
        "duplicate_month_name",
        "month_length_below_min",
        "week_too_short",
        "week_length_mismatch",
        "empty_week_name",
        "duplicate_week_name",
        "empty_intercalary_name",
        "duplicate_intercalary_name",
        "intercalary_unknown_month",
        "year_length_overflow",
    )
    for code in validation_codes:
        phrase = corruption_reason_phrase(code)
        assert phrase != GENERIC_CORRUPT_PHRASE, code
        # Русские фразы — кириллица, а не английское message домена.
        assert any("а" <= ch <= "я" for ch in phrase), code


def test_unknown_code_and_unknown_version_fall_back_to_generic():
    # Spec «Неизвестная версия формата»: версия v больше известной даёт
    # общую формулировку — тот же путь, что и неизвестный код.
    assert corruption_reason_phrase("unknown_version") == GENERIC_CORRUPT_PHRASE
    assert corruption_reason_phrase("code_from_the_future") == GENERIC_CORRUPT_PHRASE


def test_body_mentions_standard_preset_and_reason():
    # Spec «Битая кастомная спека»: предупреждение с русской формулировкой
    # про причину.
    body = calendar_corruption_body(
        (SpecProblem("intercalary_unknown_month", "domain english detail"),)
    )
    assert "«Стандартный»" in body
    assert "вставной день ссылается на несуществующий месяц" in body
    # Английское доменное message пользователю не показываем.
    assert "domain english detail" not in body
    assert MONTH_WARNING_TITLE == "Настройки календаря"


def test_body_dedups_repeated_phrases():
    reasons = (
        SpecProblem("empty_month_name", "a"),
        SpecProblem("empty_month_name", "b"),
        SpecProblem("corrupt_json", "c"),
    )
    body = calendar_corruption_body(reasons)
    assert body.count(corruption_reason_phrase("empty_month_name")) == 1
    assert corruption_reason_phrase("corrupt_json") in body


def test_empty_reasons_never_leaves_silence():
    # Spec «Окно не глотает молчание»: тело всегда непустое и осмысленное.
    body = calendar_corruption_body(())
    assert GENERIC_CORRUPT_PHRASE in body
