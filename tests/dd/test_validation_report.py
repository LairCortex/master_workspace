"""Report contract tests (change add-dnd-module-foundation, task 4.5; path
notation formatter of fix-dnd-followups, design Д3)."""
from __future__ import annotations

from app.dd.domain.validation_report import (
    CheckIssue,
    Severity,
    ValidationReport,
    format_issue_path,
)


def _issue(code: str, severity: Severity, path: str, message: str = "текст") -> CheckIssue:
    return CheckIssue(code=code, severity=severity, path=path, message=message)


def test_report_splits_categories_and_decides_the_import_threshold():
    errors = _issue("A", Severity.ERROR, "classes[x]")
    warnings = _issue("B", Severity.WARNING, "classes[y]")
    report = ValidationReport.of([warnings, errors])
    assert report.errors == (errors,)
    assert report.warnings == (warnings,)
    assert not report.import_allowed


def test_warnings_alone_never_block_the_import():
    report = ValidationReport.of([_issue("B", Severity.WARNING, "races[elf]")])
    assert report.import_allowed
    assert report.errors == ()


def test_no_issues_means_import_allowed():
    report = ValidationReport.of([])
    assert report.issues == ()
    assert report.import_allowed


def test_report_orders_issues_deterministically():
    first = _issue("Z_CODE", Severity.ERROR, "a/path")
    second = _issue("A_CODE", Severity.ERROR, "b/path")
    warning = _issue("W", Severity.WARNING, "a/path")
    same_path_later_code = _issue("Z_CODE", Severity.ERROR, "a/path", "another text")
    report = ValidationReport.of([warning, second, same_path_later_code, first])
    paths = [(i.severity, i.path, i.code, i.message) for i in report.issues]
    assert paths == sorted(paths)
    assert report.issues[0].severity is Severity.ERROR


def test_issue_is_frozen_and_equal_by_value():
    left = _issue("A", Severity.ERROR, "p")
    right = _issue("A", Severity.ERROR, "p")
    assert left == right
    assert len({left, right}) == 1


# ── format_issue_path (fix-dnd-followups, design Д3) ──────────────────────────


def test_formatter_passes_the_canonical_notation_through():
    for path in (
        "id",
        "data.info.charClass.id",
        "classes[0].grants[5].type",
        "classes[cleric]",
        "spells[fire-ball].slug",
        "spells[Тихий знак]",
        "license",
        "$schema",
        "data.spells.list[0]",
    ):
        assert format_issue_path(path) == path
        assert format_issue_path(format_issue_path(path)) == path


def test_formatter_passes_placeholders_through():
    for path in ("<файл>", "<корень>", "<ответ модели>", "<блок>"):
        assert format_issue_path(path) == path


def test_formatter_turns_colon_joins_into_dots():
    assert format_issue_path("classes[cleric]:grants") == "classes[cleric].grants"
    assert (
        format_issue_path("races[elf]:leveledGrants[3].grants[0]")
        == "races[elf].leveledGrants[3].grants[0]"
    )


def test_formatter_prints_away_grant_type_stamps():
    assert format_issue_path("classes[wiz]:grants[0](bonus)") == "classes[wiz].grants[0]"
    assert (
        format_issue_path(
            "classes[wiz]:grants[1](pick-one).options[0].grants[0](feat)"
        )
        == "classes[wiz].grants[1].options[0].grants[0]"
    )


def test_formatter_re_joins_the_block_reanchor_with_a_dot():
    assert format_issue_path("Биография · doc.content[0]") == "Биография.doc.content[0]"
    # снимок-блок без внутреннего места едет как «блок · <placeholder>»
    assert format_issue_path("Биография · <блок>") == "Биография.<блок>"


def test_formatter_leaves_bracket_content_verbatim():
    # имена и слаги в [...] — не разделители пути: ни двоеточие, ни скобки
    # внутри индекса не трогаются
    assert format_issue_path("spells[Огонь: сильный (яркий)]") == "spells[Огонь: сильный (яркий)]"
    assert format_issue_path("spells[a]b:c") == "spells[a]b.c"


def test_formatter_survives_pathological_brackets():
    # незакрытая скобка печатается как есть, гуляющая ] не ломает счёт
    assert format_issue_path("a(b") == "a(b"
    assert format_issue_path("x](a)") == "x]"
    assert format_issue_path("data.spells.list:](") == "data.spells.list.]("


def test_report_of_formats_every_record_path():
    raw = _issue("BONUS_TARGET", Severity.ERROR, "classes[wiz]:grants[0](bonus)")
    clean = _issue("DUP_ID", Severity.ERROR, "classes[wiz]")
    report = ValidationReport.of([raw, clean])
    assert [(i.code, i.path) for i in report.issues] == [
        ("DUP_ID", "classes[wiz]"),
        ("BONUS_TARGET", "classes[wiz].grants[0]"),
    ]
    # идемпотентность сборки: повторный прогон через of() ничего не меняет
    assert ValidationReport.of(list(report.issues)).issues == report.issues
