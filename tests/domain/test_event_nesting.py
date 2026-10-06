"""Tests for ``app.domain.event_nesting`` (NRI-0027 task 1.1, design Д5).

The contract under test is the single two-level judge shared by the event
card (``EventService``) and the xlsx pre-analysis: three refusal codes
(``not_found`` / ``is_subevent`` / ``self_parent``), the verdict order that
reproduces the historical ``EventService._guard_parent`` (self → existence
→ sub-event ban), the «no refusal» answer for a legal link, and the Russian
wordings verbatim the ``ValueError`` texts of ``EventService`` — the same
sentences the card tests have always pinned.
"""
import pytest

from app.domain.event_nesting import (
    CODE_IS_SUBEVENT,
    CODE_NOT_FOUND,
    CODE_SELF_PARENT,
    PARENT_REFUSAL_MESSAGES,
    parent_refusal_code,
    parent_refusal_message,
)


class TestRefusalCodes:
    def test_code_values_are_the_contract_strings(self):
        # the import pre-analysis (tasks 3.2/3.3) branches on these literals
        assert CODE_NOT_FOUND == "not_found"
        assert CODE_IS_SUBEVENT == "is_subevent"
        assert CODE_SELF_PARENT == "self_parent"

    def test_every_code_carries_a_russian_wording(self):
        assert set(PARENT_REFUSAL_MESSAGES) == {
            CODE_NOT_FOUND,
            CODE_IS_SUBEVENT,
            CODE_SELF_PARENT,
        }


class TestParentRefusalCode:
    def test_legal_parent_is_no_refusal(self):
        # found, parentless, not the edited event — «нет отказа»
        assert parent_refusal_code(True, False, False) is None

    def test_missing_parent_refuses_not_found(self):
        assert parent_refusal_code(False, False, False) == CODE_NOT_FOUND

    def test_parent_that_is_a_subevent_refuses(self):
        # spec «Подсобытие не обрастает детьми»: three levels are banned
        assert parent_refusal_code(True, True, False) == CODE_IS_SUBEVENT

    def test_self_parent_refuses(self):
        assert parent_refusal_code(True, False, True) == CODE_SELF_PARENT

    @pytest.mark.parametrize(
        ("parent_found", "parent_is_child"),
        [
            (True, False),   # сам себе найденный родитель
            (False, False),  # отказ считается до проверки существования
            (True, True),    # и до запрета подсобытия
        ],
    )
    def test_self_wins_over_the_other_codes(self, parent_found, parent_is_child):
        # order of the historical _guard_parent: self is checked first
        assert parent_refusal_code(parent_found, parent_is_child, True) == CODE_SELF_PARENT

    def test_not_found_wins_over_the_subevent_ban(self):
        # the judge never inspects an absent record, as EventService did
        assert parent_refusal_code(False, True, False) == CODE_NOT_FOUND

    def test_keywords_work_positionally_and_by_name(self):
        # the design Д5 signature is positional; the service calls by name
        assert parent_refusal_code(False, False, False) == parent_refusal_code(
            parent_found=False, parent_is_child=False, is_self=False,
        )


class TestParentRefusalMessage:
    def test_not_found_names_the_parent_id_verbatim(self):
        # дословный текст сегодняшнего ValueError EventService
        assert (
            parent_refusal_message(CODE_NOT_FOUND, 999999)
            == "родительское событие 999999 не найдено"
        )

    def test_is_subevent_sentence_is_verbatim(self):
        assert (
            parent_refusal_message(CODE_IS_SUBEVENT)
            == "родительское событие не может быть подсобытием"
        )

    def test_self_parent_sentence_is_verbatim(self):
        assert (
            parent_refusal_message(CODE_SELF_PARENT)
            == "событие не может быть родителем самого себя"
        )

    def test_parent_id_is_ignored_by_the_whole_sentence_codes(self):
        # the slot only exists in not_found; a stray id changes nothing here
        assert parent_refusal_message(CODE_IS_SUBEVENT, 7) == (
            PARENT_REFUSAL_MESSAGES[CODE_IS_SUBEVENT]
        )
        assert parent_refusal_message(CODE_SELF_PARENT, 7) == (
            PARENT_REFUSAL_MESSAGES[CODE_SELF_PARENT]
        )

    def test_unknown_code_is_a_key_error(self):
        # callers judge via parent_refusal_code, never invent codes
        with pytest.raises(KeyError):
            parent_refusal_message("no_such_code")
