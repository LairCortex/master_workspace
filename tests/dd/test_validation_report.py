"""Report contract tests (change add-dnd-module-foundation, task 4.5)."""
from __future__ import annotations

from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport


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
