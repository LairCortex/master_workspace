"""Unit tests for the xlsx-import VM state machine (task 4.1).

idle → analyzing → problems → importing → done, with `analysisIssues` /
`hasFatal` / `canImport` / `report` and the analyze/confirm/download signals.
The service plan artifacts are the real pure dataclasses (no DB, no file).
"""
from pathlib import Path

import pytest

from app.application.services.xlsx_import_service import ImportPlan, ImportReport, RowIssue
from app.presentation.viewmodels.xlsx_import_view_model import (
    STATE_ANALYZING,
    STATE_DONE,
    STATE_IDLE,
    STATE_IMPORTING,
    STATE_PROBLEMS,
    XlsxImportViewModel,
)


def plan_with(*, fatal=(), rows=()) -> ImportPlan:
    plan = ImportPlan(path=Path("/tmp/file.xlsx"))
    plan.fatal_errors = list(fatal)
    plan.skipped_rows = list(rows)
    return plan


@pytest.fixture
def vm(qtbot):
    v = XlsxImportViewModel("hint")
    return v


class TestIdle:
    def test_initial_state(self, vm):
        assert vm.formatText == "hint"
        assert vm.state == STATE_IDLE
        assert vm.path == ""
        assert vm.analysisIssues == []
        assert vm.hasFatal is False
        assert vm.canImport is False  # no path yet — nothing to analyze
        assert vm.report is None
        assert vm.progress == 0
        assert vm.progressVisible is False

    def test_path_enables_analyze(self, vm):
        vm.path = "/a.xlsx"
        assert vm.state == STATE_IDLE
        assert vm.canImport is True

    def test_blank_path_does_not_enable_analyze(self, vm):
        vm.path = "   "
        assert vm.canImport is False

    def test_browse_and_download_signals(self, vm):
        browsed, downloaded = [], []
        vm.browseRequested.connect(lambda: browsed.append(1))
        vm.download_template.connect(lambda: downloaded.append(1))
        vm.requestBrowse()
        vm.requestDownloadTemplate()
        assert browsed == downloaded == [1]


class TestAnalyze:
    def test_request_analyze_emits_path_and_locks(self, vm):
        requested = []
        vm.analyze_requested.connect(requested.append)
        vm.path = " /tmp/batch.xlsx "
        vm.requestAnalyze()
        assert requested == ["/tmp/batch.xlsx"]
        assert vm.state == STATE_ANALYZING
        assert vm.canImport is False

    def test_request_analyze_ignored_without_path(self, vm):
        requested = []
        vm.analyze_requested.connect(requested.append)
        vm.requestAnalyze()
        assert requested == []
        assert vm.state == STATE_IDLE

    def test_request_analyze_ignored_while_analyzing(self, vm):
        requested = []
        vm.analyze_requested.connect(requested.append)
        vm.path = "/a.xlsx"
        vm.requestAnalyze()
        vm.requestAnalyze()
        assert requested == ["/a.xlsx"]


class TestProblems:
    def test_clean_plan_allows_confirm(self, vm):
        vm.path = "/a.xlsx"
        vm.requestAnalyze()
        vm.on_analyzed(plan_with())
        assert vm.state == STATE_PROBLEMS
        assert vm.analysisIssues == []
        assert vm.hasFatal is False
        assert vm.canImport is True

    def test_row_problems_listed_and_import_allowed(self, vm):
        issues = [
            RowIssue("Персонажи", 5, "пустое имя"),
            RowIssue("События", 9, "дата начала: пусто"),
        ]
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with(rows=issues))
        assert vm.state == STATE_PROBLEMS
        assert vm.hasFatal is False
        assert vm.canImport is True  # spec: продолжить «с пропуском»
        assert vm.analysisIssues == [
            {"sheet": "Персонажи", "row": 5, "reason": "пустое имя", "fatal": False},
            {"sheet": "События", "row": 9, "reason": "дата начала: пусто", "fatal": False},
        ]

    def test_fatal_plan_blocks_can_import(self, vm):
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with(fatal=["Файл повреждён."]))
        assert vm.state == STATE_PROBLEMS
        assert vm.hasFatal is True
        assert vm.canImport is False  # spec: «Фатальная ошибка блокирует»
        assert vm.analysisIssues == [
            {"sheet": "", "row": 0, "reason": "Файл повреждён.", "fatal": True},
        ]

    def test_confirm_blocked_while_fatal(self, vm):
        confirmed = []
        vm.confirm_import.connect(lambda: confirmed.append(1))
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with(fatal=["нет знакомых листов."]))
        vm.requestConfirmImport()
        assert confirmed == []
        assert vm.state == STATE_PROBLEMS

    def test_analyze_failed_marks_fatal(self, vm):
        vm.path = "/a.xlsx"
        vm.on_analyze_failed("нет доступа")
        assert vm.state == STATE_PROBLEMS
        assert vm.hasFatal is True
        assert vm.canImport is False
        assert "нет доступа" in vm.analysisIssues[0]["reason"]

    def test_path_change_resets_analysis(self, vm):
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with(fatal=["битый файл"], rows=[RowIssue("События", 2, "х")]))
        assert vm.hasFatal is True
        vm.path = "/b.xlsx"  # другой файл — прежний пул проблем больше неактуален
        assert vm.state == STATE_IDLE
        assert vm.analysisIssues == []
        assert vm.hasFatal is False
        assert vm.canImport is True
        assert vm.report is None


class TestImporting:
    def test_confirm_switches_to_importing_and_resets_progress(self, vm):
        confirmed = []
        vm.confirm_import.connect(lambda: confirmed.append(1))
        vm.path = "/a.xlsx"
        vm.set_progress(3, 4)  # leftover from a previous run
        vm.on_analyzed(plan_with(rows=[RowIssue("События", 2, "х")]))
        vm.requestConfirmImport()
        assert confirmed == [1]
        assert vm.state == STATE_IMPORTING
        assert vm.progress == 0
        assert vm.progressVisible is True
        assert vm.canImport is False

    def test_write_intents_locked_out_while_importing(self, vm):
        analyzed, confirmed = [], []
        vm.analyze_requested.connect(analyzed.append)
        vm.confirm_import.connect(lambda: confirmed.append(1))
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with())
        vm.requestConfirmImport()
        vm.requestAnalyze()
        vm.requestConfirmImport()
        assert analyzed == [] and confirmed == [1]

    def test_progress_percent(self, vm):
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with())
        vm.requestConfirmImport()
        vm.set_progress(1, 4)
        assert vm.progress == 25
        vm.set_progress(3, 4)
        assert vm.progress == 75
        vm.set_progress(4, 4)
        assert vm.progress == 100
        vm.set_progress(0, 0)
        assert vm.progress == 0


class TestDone:
    def test_report_populates_and_state_done(self, vm):
        report = ImportReport(
            created=8,
            updated=2,
            links=5,
            skipped=[RowIssue("Персонажи", 3, "пустое имя")],
            decisions=["Автосоздание: тип события «Дуэль»"],
            warnings=["Неизвестный лист «Заметки»"],
        )
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with(rows=report.skipped))
        vm.requestConfirmImport()
        vm.on_report(report)
        assert vm.state == STATE_DONE
        assert vm.progress == 100
        assert vm.progressVisible is False
        assert vm.canImport is False  # the primary button is «Закрыть» now
        assert vm.report == {
            "created": 8,
            "updated": 2,
            "links": 5,
            "skipped": [{"sheet": "Персонажи", "row": 3, "reason": "пустое имя"}],
            "decisions": ["Автосоздание: тип события «Дуэль»"],
            "warnings": ["Неизвестный лист «Заметки»"],
        }

    def test_import_failure_returns_to_fatal_problems(self, vm):
        vm.path = "/a.xlsx"
        vm.on_analyzed(plan_with(rows=[RowIssue("События", 2, "х")]))
        vm.requestConfirmImport()
        vm.on_import_failed("база заблокирована")
        assert vm.state == STATE_PROBLEMS
        assert vm.hasFatal is True  # rollback: blind repeat is not allowed
        assert vm.canImport is False
        assert "база заблокирована" in vm.analysisIssues[0]["reason"]
        # The earlier row problems stay visible next to the fatal entry.
        assert vm.analysisIssues[-1]["sheet"] == "События"
        # Only a repeated analysis (path touched) re-enables the flow.
        vm.path = "/a2.xlsx"
        assert vm.canImport is True
