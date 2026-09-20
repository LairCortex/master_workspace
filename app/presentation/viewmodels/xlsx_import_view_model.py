"""State-machine VM for the unified xlsx-import QML island (rework 4.1).

States (design D8): ``idle → analyzing → problems → importing → done``.

* ``idle`` — file chosen (or not yet); the primary button means «Проверить…».
* ``analyzing`` — the wiring runs ``XlsxImportService.analyze_file`` under the
  session lock; every write control of the flow is locked out.
* ``problems`` — the analysis result is on screen: ``analysisIssues`` lists
  fatal file errors first, then per-row planned skips (sheet/number/reason).
  Fatal entries (``hasFatal``) block ``canImport``; row-only problems allow
  the "import with skips" confirmation (spec «Пул проблем показан до записи»).
* ``importing`` — apply pass runs; progress (0..100) is reported.
* ``done`` — ``report`` (created/updated/links/skipped/dateShifts/decisions/
  warnings) feeds the dialog's report panel; the primary button becomes
  «Закрыть».

The VM never touches services or the session: the wiring calls the service
and feeds results back through ``on_analyzed`` / ``on_analyze_failed`` /
``on_report`` / ``on_import_failed``. A technical import failure returns to
``problems`` with a fatal entry (the transaction was rolled back, so nothing
may be re-applied blindly; the user must analyze a file again).

The service dataclasses (``ImportPlan`` / ``ImportReport``) are consumed by
duck-typing — only TYPE_CHECKING imports, so this module stays light.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Property, Signal, Slot

if TYPE_CHECKING:  # pragma: no cover — annotations only
    from app.application.services.xlsx_import_service import ImportPlan, ImportReport

STATE_IDLE = "idle"
STATE_ANALYZING = "analyzing"
STATE_PROBLEMS = "problems"
STATE_IMPORTING = "importing"
STATE_DONE = "done"


def _issue(sheet: str, row: int, reason: str, fatal: bool) -> dict[str, Any]:
    return {"sheet": sheet, "row": row, "reason": reason, "fatal": fatal}


class XlsxImportViewModel(QObject):
    # property notifiers
    pathChanged = Signal()
    stateChanged = Signal()
    issuesChanged = Signal()
    progressChanged = Signal()
    reportChanged = Signal()
    formatChanged = Signal()

    # user intents (task 4.1)
    analyze_requested = Signal(str)
    confirm_import = Signal()
    download_template = Signal()
    # kept from the old island contract: the facade owns QFileDialog
    browseRequested = Signal()

    def __init__(self, format_text: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._format = format_text
        self._path = ""
        self._state = STATE_IDLE
        self._issues: list[dict[str, Any]] = []
        self._has_fatal = False
        self._progress = 0
        self._report: dict[str, Any] | None = None

    # ── state ──────────────────────────────────────────────────────────────

    def _get_state(self) -> str:
        return self._state

    state = Property(str, _get_state, notify=stateChanged)

    def _set_state(self, value: str) -> None:
        if self._state != value:
            self._state = value
            # canImport depends on the state as well as on path/hasFatal;
            # progressVisible is the state itself (importing), so both flags
            # travel with every state transition.
            self.stateChanged.emit()
            self.progressChanged.emit()

    # ── path ───────────────────────────────────────────────────────────────

    def _get_path(self) -> str:
        return self._path

    def _set_path(self, value: str) -> None:
        if self._path != value:
            self._path = value
            # A new (or cleared) file invalidates the whole analysis: the plan
            # the wiring holds no longer matches the shown path.
            self._reset_analysis()
            self.pathChanged.emit()
            self.stateChanged.emit()

    path = Property(str, _get_path, _set_path, notify=pathChanged)

    def _reset_analysis(self) -> None:
        # Plain assignment here: the path setter emits the notifiers below
        # (stateChanged covers canImport, progressChanged covers visibility).
        self._state = STATE_IDLE
        self._issues = []
        self._has_fatal = False
        self._progress = 0
        self._set_report(None)
        self.issuesChanged.emit()
        self.progressChanged.emit()

    # ── analysis issues / canImport ────────────────────────────────────────

    def _get_issues(self) -> list[dict[str, Any]]:
        return self._issues

    analysisIssues = Property("QVariant", _get_issues, notify=issuesChanged)

    def _get_has_fatal(self) -> bool:
        return self._has_fatal

    hasFatal = Property(bool, _get_has_fatal, notify=issuesChanged)

    def _get_can_import(self) -> bool:
        """Primary button actionability: only idle (analyze) and problems
        (confirm, when nothing is fatal) are actionable; busy/done are not."""
        if self._state not in (STATE_IDLE, STATE_PROBLEMS):
            return False
        if self._has_fatal:
            return False
        return bool(self._path.strip())

    canImport = Property(bool, _get_can_import, notify=stateChanged)

    # ── progress ───────────────────────────────────────────────────────────

    def _get_progress(self) -> int:
        return self._progress

    progress = Property(int, _get_progress, notify=progressChanged)

    def _get_progress_visible(self) -> bool:
        return self._state == STATE_IMPORTING

    progressVisible = Property(bool, _get_progress_visible, notify=progressChanged)

    # ── hint text (registry-generated, continuity of old hint texts) ──────

    def _get_format(self) -> str:
        return self._format

    formatText = Property(str, _get_format, notify=formatChanged)

    # ── report ─────────────────────────────────────────────────────────────

    def _get_report(self) -> "dict[str, Any] | None":
        return self._report

    report = Property("QVariant", _get_report, notify=reportChanged)

    def _set_report(self, value: "dict[str, Any] | None") -> None:
        if self._report != value:
            self._report = value
            self.reportChanged.emit()

    # ── user intents (QML slots) ───────────────────────────────────────────

    @Slot()
    def requestBrowse(self) -> None:  # noqa: N802
        self.browseRequested.emit()

    @Slot()
    def requestAnalyze(self) -> None:  # noqa: N802
        if self._state != STATE_IDLE or not self.canImport:
            return
        self._set_state(STATE_ANALYZING)
        self.analyze_requested.emit(self._path.strip())

    @Slot()
    def requestConfirmImport(self) -> None:  # noqa: N802
        if self._state != STATE_PROBLEMS or not self.canImport:
            return
        self._progress = 0
        self.progressChanged.emit()
        self._set_state(STATE_IMPORTING)
        self.confirm_import.emit()

    @Slot()
    def requestDownloadTemplate(self) -> None:  # noqa: N802
        self.download_template.emit()

    # ── facade callbacks (fed by the wiring) ───────────────────────────────

    def on_analyzed(self, plan: "ImportPlan") -> None:
        """Publish the analysis result: fatal file errors first, then the
        planned-skip rows (spec «Пред-анализ файла до импорта»)."""
        self._issues = [
            _issue("", 0, message, True) for message in plan.fatal_errors
        ] + [
            _issue(row.sheet, row.row_number, row.reason, False)
            for row in plan.skipped_rows
        ]
        self._has_fatal = plan.has_fatal
        self._set_state(STATE_PROBLEMS)
        self.issuesChanged.emit()

    def on_analyze_failed(self, message: str) -> None:
        self._issues = [_issue("", 0, f"Файл не удалось проанализировать: {message}", True)]
        self._has_fatal = True
        self._set_state(STATE_PROBLEMS)
        self.issuesChanged.emit()

    def set_progress(self, current: int, total: int) -> None:
        self._progress = int(100 * current / total) if total > 0 else 0
        self.progressChanged.emit()

    def on_report(self, report: "ImportReport") -> None:
        self._set_report(
            {
                "created": report.created,
                "updated": report.updated,
                "links": report.links,
                "skipped": [
                    {"sheet": row.sheet, "row": row.row_number, "reason": row.reason}
                    for row in report.skipped
                ],
                "dateShifts": [
                    {"sheet": s.sheet, "row": s.row_number, "field": s.field,
                     "old": s.old, "new": s.new}
                    for s in report.date_shifts
                ],
                "decisions": list(report.decisions),
                "warnings": list(report.warnings),
            }
        )
        self._progress = 100
        self._set_state(STATE_DONE)
        self.progressChanged.emit()

    def on_import_failed(self, message: str) -> None:
        """The apply pass rolled everything back (design D6): go back to
        ``problems`` with a fatal entry so the same plan cannot be re-applied
        blindly — only a repeated analysis (or a new file) re-enables import."""
        rows = [issue for issue in self._issues if not issue["fatal"]]
        self._issues = [
            _issue("", 0, f"Импорт не выполнен (изменения откатаны): {message}", True)
        ] + rows
        self._has_fatal = True
        self._set_state(STATE_PROBLEMS)
        self.issuesChanged.emit()
