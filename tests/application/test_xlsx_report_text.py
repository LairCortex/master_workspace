"""Wording pins for xlsx_report_text (NRI-0027, task 3.3).

The parent-problem captions must carry the shared domain module's Russian
refusal texts verbatim (the event card and the import refuse a bad parent
with one and the same formulation — design Д5, no second copy at the usage
site) plus the offending event's name and Excel row number; the time warning
names the sheet, the row and the original cell value (spec «Колонка „Время
начала“»: the event is imported without time, the row is not lost).
"""
from app.application.services.xlsx_report_text import (
    ambiguous_parent_reference,
    parent_problem_caption,
    start_time_warning,
)
from app.domain.event_nesting import (
    CODE_IS_SUBEVENT,
    CODE_NOT_FOUND,
    CODE_SELF_PARENT,
    parent_refusal_message,
)


def test_not_found_caption_renders_the_shared_text_with_the_parent_name():
    reason = parent_problem_caption("Охота", 2, CODE_NOT_FOUND, "Никогда")
    assert reason == (
        "событие «Охота» (строка 2): "
        + parent_refusal_message(CODE_NOT_FOUND, "«Никогда»")
    )
    assert "родительское событие «Никогда» не найдено" in reason


def test_is_subevent_caption_carries_the_card_wording_verbatim():
    reason = parent_problem_caption("В", 5, CODE_IS_SUBEVENT, "У")
    assert reason == (
        "событие «В» (строка 5): " + parent_refusal_message(CODE_IS_SUBEVENT)
    )
    assert "родительское событие не может быть подсобытием" in reason


def test_self_parent_caption_carries_the_card_wording_verbatim():
    reason = parent_problem_caption("Дуэль", 3, CODE_SELF_PARENT, "Дуэль")
    assert reason == (
        "событие «Дуэль» (строка 3): " + parent_refusal_message(CODE_SELF_PARENT)
    )
    assert "событие не может быть родителем самого себя" in reason


def test_ambiguous_parent_caption_names_event_row_and_parent():
    assert ambiguous_parent_reference("Дуэль", 2, "Князь") == (
        "событие «Дуэль» (строка 2): родитель «Князь» разрешения не имеет — "
        "в базе несколько событий с таким именем, "
        "а в файле нет живой строки с этим именем"
    )


def test_start_time_warning_names_sheet_row_and_original_value():
    assert start_time_warning("События", 4, "полдень") == (
        "Лист «События», строка 4: время начала «полдень» не разобрано или "
        "не помещается в игровой календарь — событие импортировано без времени"
    )
