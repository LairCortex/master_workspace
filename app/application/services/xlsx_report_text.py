"""User-facing phrases of the xlsx import (audit B6, design D6).

The parsing/merging/applying engines build structure; the end-user Russian
text is collected here so wordings live once, apart from the code that
decides *when* they are shown. Wording is byte-identical to the strings
the monolith produced — the import spec and the e2e assertions pin them.
"""
from __future__ import annotations

#  ── pre-analysis row problems ────────────────────────────────────────────

#: RU captions of the pre-analysis date problems (design D4, task 2.4): the
#: pure parser only carries the machine ``code`` plus the offending
#: ``subject``, the row-skip caption is assembled here (the wizard's
#: ``_CODE_PHRASES`` is the pattern).  A code missing from the dictionary is
#: a defect of the parser, never a silent fallback — hence the direct index.
_DATE_PROBLEM_PHRASES: dict[str, str] = {
    "unknown_name": "месяц «{subject}» не найден в календаре игры",
    "intercalary_with_day": "у вставного дня «{subject}» не бывает номера дня",
    "month_without_day": "месяц «{subject}» без номера дня",
    "out_of_range": "число «{subject}» вне границ игрового календаря",
}


def date_problem_caption(code: str, subject: object) -> str:
    """Row-skip caption for one machine date-problem code from the parser."""
    return _DATE_PROBLEM_PHRASES[code].format(subject=subject)


def ambiguous_link_reference(label: str, name: str, sheet_name: str) -> str:
    """Planned-skip caption for a link reference the name index cannot
    resolve uniquely: several DB rows carry the name and no file row does."""
    return (
        f"колонка «{label}»: ссылка «{name}» разрешения "
        f"не имеет — в базе несколько сущностей (лист «{sheet_name}»), "
        "а в файле нет строки с таким именем"
    )


# ── apply-phase abort ─────────────────────────────────────────────────────


def vanished_after_analysis(name: str, sheet: str) -> str:
    """Abort message when the update target of a planned row disappeared
    from the DB between the analysis and the apply (spec «Транзакционность
    импорта»: the whole import rolls back and re-raises for the UI)."""
    return (
        f"сущность «{name}» (лист «{sheet}») исчезла из базы "
        "между анализом и применением"
    )
