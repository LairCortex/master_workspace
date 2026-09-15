"""Characterization tests for the unified XlsxImportDialog island (task 4.2).

The dialog is the render half of the VM state machine (task 4.1): pre-analysis
problem list (sheet/row/reason) with the primary button blocked on fatals,
progress, the final report panel, the registry-generated hint, the «Скачать
шаблон» button and the honest `.xlsx`-only file filter.
"""
import sys

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.application.services import xlsx_schema
from app.application.services.xlsx_import_service import ImportPlan, ImportReport, RowIssue
from app.presentation.views import xlsx_import_dialog
from app.presentation.views.xlsx_import_dialog import (
    PRIMARY_TEXT_ANALYZE,
    PRIMARY_TEXT_CLOSE,
    PRIMARY_TEXT_IMPORT,
    TEMPLATE_FILE_NAME,
    XLSX_FILTER,
    XlsxImportDialog,
    build_format_text,
    import_template_source,
    save_template_as,
)
from tests.presentation.qml_helpers import find_item, island_row_texts, walk_items


def plan_with(*, fatal=(), rows=(), warnings=()) -> ImportPlan:
    plan = ImportPlan(path="/tmp/file.xlsx")
    plan.fatal_errors = list(fatal)
    plan.skipped_rows = list(rows)
    plan.warnings = list(warnings)
    return plan


@pytest.fixture
def dlg(qtbot):
    d = XlsxImportDialog()
    qtbot.addWidget(d)
    return d


def _texts(widget, object_name: str) -> list[str]:
    return [i.property("text") for i in walk_items(widget.rootObject())
            if i.objectName() == object_name]


class TestHintFromRegistry:
    def test_hint_covers_every_sheet_and_column(self):
        hint = build_format_text()
        for sheet in xlsx_schema.all_sheets():
            assert f"Лист «{sheet.sheet_name}»" in hint
            for column in xlsx_schema.all_headers(sheet):
                assert column.label in hint
        # Continuity of the old hint wording for the shared columns.
        assert "Дата начала (YYYY-MM-DD или дата Excel)" in hint
        assert "Ссылка на музыкальную тему" in hint
        assert "PNG, JPG, BMP, GIF, WebP" in hint

    def test_hint_shows_link_syntax_and_aliases(self):
        hint = build_format_text()
        assert "Связь персонажами" in hint
        assert "Связь событиями" in hint
        assert "имена через «;»" in hint
        assert "алиасы: name" in hint  # старый англ. заголовок упомянут

    def test_dialog_hint_matches_registry_generation(self, dlg):
        assert dlg.format_text.toPlainText() == build_format_text()
        assert dlg.format_text.isReadOnly()


class TestConstruction:
    def test_title_and_initial_state(self, dlg):
        assert dlg.windowTitle() == "Импорт из .xlsx"
        assert dlg.get_path() == ""
        assert dlg.path_edit.text() == ""
        assert dlg.progress_bar.value() == 0
        assert dlg.import_btn.isEnabled() is False  # no path in idle
        assert dlg.import_btn.text() == PRIMARY_TEXT_ANALYZE
        assert dlg.vm.state == "idle"
        assert not dlg.vm.hasFatal and dlg.vm.report is None

    def test_island_object_names(self, dlg):
        root = dlg.quick.rootObject()
        names = {root.objectName()} | {i.objectName() for i in walk_items(root)}
        for name in (
            "formatArea", "pathField", "browseButton", "downloadButton",
            "progressBar", "importButton", "cancelButton", "issueList",
            "reportArea",
        ):
            assert name in names
        assert not hasattr(dlg, "entity_type")
        assert root.property("defaultButton").objectName() == "importButton"


class TestBrowseFilter:
    def test_filter_is_xlsx_only(self, dlg, mocker):
        spy = mocker.patch.object(QFileDialog, "getOpenFileName", return_value=("", ""))
        dlg._on_browse()
        selected_filter = spy.call_args.args[3]
        assert selected_filter == XLSX_FILTER
        assert "*.xlsx" in selected_filter
        assert "*.xls " not in selected_filter  # .xls честно исключён
        assert "Все файлы" not in selected_filter

    def test_browse_sets_path(self, dlg, mocker, tmp_path):
        p = tmp_path / "file.xlsx"
        p.write_bytes(b"x")
        mocker.patch.object(QFileDialog, "getOpenFileName", return_value=(str(p), ""))
        dlg.vm.requestBrowse()
        assert dlg.path_edit.text() == str(p)
        assert dlg.get_path() == str(p)

    def test_browse_cancellation_keeps_path_empty(self, dlg, mocker):
        mocker.patch.object(QFileDialog, "getOpenFileName", return_value=("", ""))
        dlg.vm.requestBrowse()
        assert dlg.path_edit.text() == ""
        assert dlg.get_path() == ""


class TestAnalyzeFlow:
    def test_primary_click_requests_analysis(self, dlg):
        dlg.path_edit.setText("/tmp/batch.xlsx")
        with qtbot_signal(dlg, "analyze_requested") as received:
            dlg.import_btn.click()
        assert received == ["/tmp/batch.xlsx"]
        assert dlg.vm.state == "analyzing"
        assert dlg.import_btn.isEnabled() is False

    def test_fatal_plan_blocks_button_and_lists_reason(self, dlg):
        dlg.path_edit.setText("/tmp/broken.xlsx")
        dlg.vm.on_analyzed(plan_with(fatal=["Лист «Персонажи»: нет строки заголовков."]))
        assert dlg.import_btn.isEnabled() is False
        assert dlg.import_btn.text() == PRIMARY_TEXT_IMPORT  # состояние problems…
        dlg.import_btn.click()  # …но клик заблокирован стейт-машиной
        assert dlg.vm.state == "problems"

        dlg.quick.grab()
        assert find_item(dlg.quick, "fatalTitle").property("visible") is True
        reasons = island_row_texts(dlg.quick, "issueRow", "issueReasonText")
        assert reasons == ["Фатально: Лист «Персонажи»: нет строки заголовков."]
        sheets = island_row_texts(dlg.quick, "issueRow", "issueSheetText")
        assert sheets == ["файл"]

    def test_row_issues_shown_sheet_row_reason(self, dlg):
        dlg.path_edit.setText("/tmp/partial.xlsx")
        dlg.vm.on_analyzed(plan_with(rows=[
            RowIssue("Персонажи", 5, "пустое имя"),
            RowIssue("События", 9, "рейтинг 7 вне диапазона 1..5"),
        ]))
        assert dlg.import_btn.isEnabled() is True
        dlg.quick.grab()
        assert island_row_texts(dlg.quick, "issueRow", "issueSheetText") == [
            "лист «Персонажи»", "лист «События»",
        ]
        assert island_row_texts(dlg.quick, "issueRow", "issueRowNumberText") == [
            "строка 5", "строка 9",
        ]
        assert island_row_texts(dlg.quick, "issueRow", "issueReasonText") == [
            "пустое имя", "рейтинг 7 вне диапазона 1..5",
        ]

    def test_confirm_from_problems_emits_signal_and_shows_progress(self, dlg):
        dlg.path_edit.setText("/tmp/partial.xlsx")
        dlg.vm.on_analyzed(plan_with(rows=[RowIssue("Персонажи", 5, "пустое имя")]))
        assert dlg.import_btn.text() == PRIMARY_TEXT_IMPORT
        with qtbot_signal(dlg, "confirm_import") as received:
            dlg.import_btn.click()
        assert received == [()]
        assert dlg.vm.state == "importing"
        assert find_item(dlg.quick, "progressBar").property("visible") is True


class TestProgress:
    def test_set_progress_partial_and_complete(self, dlg):
        dlg.path_edit.setText("/tmp/a.xlsx")
        dlg.vm.on_analyzed(plan_with())
        dlg.vm.requestConfirmImport()
        dlg.set_progress(1, 4)
        assert dlg.progress_bar.value() == 25
        dlg.set_progress(3, 4)
        assert dlg.progress_bar.value() == 75
        dlg.set_progress(4, 4)
        assert dlg.progress_bar.value() == 100

    def test_set_progress_zero_total_resets(self, dlg):
        dlg.set_progress(2, 2)
        dlg.set_progress(0, 0)
        assert dlg.progress_bar.value() == 0


class TestReportPanel:
    @pytest.fixture
    def reported(self, dlg):
        dlg.path_edit.setText("/tmp/a.xlsx")
        report = ImportReport(
            created=8,
            updated=2,
            links=5,
            skipped=[RowIssue("Персонажи", 3, "пустое имя")],
            decisions=["Автосоздание: тип события «Дуэль»"],
            warnings=["Неизвестный лист «Заметки»"],
        )
        dlg.vm.on_analyzed(plan_with(rows=report.skipped))
        dlg.vm.requestConfirmImport()
        dlg.vm.on_report(report)
        return dlg, report

    def test_state_and_button(self, reported):
        d, _ = reported
        assert d.vm.state == "done"
        assert d.import_btn.isEnabled() is True
        assert d.import_btn.text() == PRIMARY_TEXT_CLOSE

    def test_panel_numbers_and_lists(self, reported):
        d, report = reported
        d.quick.grab()
        assert find_item(d.quick, "reportArea").property("visible") is True
        assert find_item(d.quick, "reportCreatedText").property("text") == "Создано: 8"
        assert find_item(d.quick, "reportUpdatedText").property("text") == "Обновлено: 2"
        assert find_item(d.quick, "reportLinksText").property("text") == "Связей: 5"
        assert "Пропущено строк: 1" in _texts(d.quick, "reportSkippedTitle")
        assert _texts(d.quick, "reportSkippedRowText") == [
            "лист «Персонажи», строка 3: пустое имя"
        ]
        assert _texts(d.quick, "reportDecisionText") == [
            "Решение: Автосоздание: тип события «Дуэль»"
        ]
        assert _texts(d.quick, "reportWarningText") == [
            "Предупреждение: Неизвестный лист «Заметки»"
        ]

    def test_close_via_primary_click(self, reported, qtbot):
        d, _ = reported
        with qtbot.waitSignal(d.finished, timeout=2000):
            d.import_btn.click()


class TestDownloadTemplate:
    def test_button_emits_dialog_signal(self, dlg, qtbot):
        # Seam for task 5.2: the island only emits, the save--as flow lands there.
        with qtbot.waitSignal(dlg.download_template, timeout=2000):
            dlg.vm.requestDownloadTemplate()


class TestDownloadTemplateFlow:
    """Task 5.2 — the save--as side of the «Скачать шаблон» seam."""

    def test_dev_path_resolves_to_committed_resource(self):
        source = import_template_source()
        assert source.name == TEMPLATE_FILE_NAME
        assert source.is_file()
        assert source.read_bytes().startswith(b"PK")  # zip container = real xlsx

    def test_frozen_path_uses_bundle_datas_layout(self, tmp_path, monkeypatch):
        dist = (tmp_path / "dist").resolve()  # resolve(): macOS /var symlink
        (dist / "_internal" / "resources").mkdir(parents=True)
        target = dist / "_internal" / "resources" / TEMPLATE_FILE_NAME
        target.write_bytes(b"bundled")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(dist / "nri_manager"))
        assert import_template_source() == target

    def test_get_save_file_name_defaults_and_filter(self, mocker, tmp_path):
        out = tmp_path / "мой_шаблон.xlsx"
        spy = mocker.patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(out), XLSX_FILTER),
        )
        written = save_template_as(None)
        assert spy.call_args.args[2] == TEMPLATE_FILE_NAME  # имя по умолчанию
        assert spy.call_args.args[3] == XLSX_FILTER  # честный .xlsx-фильтр
        assert written == out
        assert out.read_bytes() == import_template_source().read_bytes()

    def test_cancellation_writes_nothing(self, mocker, tmp_path):
        spy = mocker.patch.object(QFileDialog, "getSaveFileName", return_value=("", ""))
        assert save_template_as(None) is None
        assert spy.called
        assert list(tmp_path.iterdir()) == []

    def test_missing_extension_gets_xlsx_appended(self, mocker, tmp_path):
        out = tmp_path / "template"  # пользователь не дописал расширение
        mocker.patch.object(QFileDialog, "getSaveFileName", return_value=(str(out), ""))
        written = save_template_as(None)
        assert written == tmp_path / "template.xlsx"
        assert written.is_file()

    def test_missing_resource_warns_and_writes_nothing(self, mocker, tmp_path):
        mocker.patch.object(
            xlsx_import_dialog, "import_template_source",
            return_value=tmp_path / "absent" / TEMPLATE_FILE_NAME,
        )
        warn = mocker.patch.object(QMessageBox, "warning")
        save = mocker.patch.object(QFileDialog, "getSaveFileName")
        assert save_template_as(None) is None
        assert warn.called
        assert not save.called  # спросить негде — ресурса нет

    def test_copy_failure_reports_to_user(self, mocker, tmp_path):
        mocker.patch.object(
            QFileDialog, "getSaveFileName",
            return_value=(str(tmp_path / "copy" / "t.xlsx"), ""),
        )
        fail = mocker.patch(
            "app.presentation.views.xlsx_import_dialog.shutil.copyfile",
            side_effect=OSError("диск кончился"),
        )
        critical = mocker.patch.object(QMessageBox, "critical")
        assert save_template_as(None) is None
        assert fail.called and critical.called


class TestPathInvalidation:
    def test_new_path_clears_problems_and_report(self, dlg):
        dlg.path_edit.setText("/tmp/broken.xlsx")
        dlg.vm.on_analyzed(plan_with(fatal=["битый"]))
        assert dlg.import_btn.isEnabled() is False
        dlg.path_edit.setText("/tmp/next.xlsx")
        assert dlg.vm.state == "idle"
        assert dlg.vm.analysisIssues == []
        assert dlg.import_btn.isEnabled() is True


class TestWiringPublishSeam:
    """The wiring feeds analyze/confirm results back through the guarded
    publish_* seam (analyze and confirm run as detached tasks; the user may
    close the dialog — «finished → deleteLater» — while they are awaiting).
    The live part lives here; the dead part deletes the C++ side for real."""

    def test_publish_analysis_adopts_plan_and_feeds_vm(self, dlg):
        plan = plan_with(rows=[RowIssue("Персонажи", 5, "пустое имя")])
        dlg.publish_analysis(plan)
        assert dlg.plan is plan
        assert dlg.vm.state == "problems"
        assert dlg.vm.analysisIssues[0]["sheet"] == "Персонажи"

    def test_publish_failure_report_transitions(self, dlg):
        dlg.publish_analysis_failure("диск отвалился")
        assert dlg.vm.state == "problems" and dlg.vm.hasFatal
        # another analysis round, then results of the apply pass
        dlg.path_edit.setText("/tmp/b.xlsx")
        dlg.publish_analysis(plan_with())
        dlg.publish_import_failure("сбой прохода 2")
        assert dlg.vm.hasFatal and "сбой" in dlg.vm.analysisIssues[0]["reason"]
        dlg.publish_report(ImportReport(created=1))
        assert dlg.vm.state == "done" and dlg.vm.report["created"] == 1

    def test_dead_dialog_publishing_and_progress_are_noops(self):
        # Mirrors the wiring teardown («finished → deleteLater») and the
        # engine.py island-release guard precedent: a deferred callback on a
        # destroyed C++ side must silently drop, not raise a RuntimeError.
        import shiboken6
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication

        dead = XlsxImportDialog()
        dead.publish_analysis(plan_with())          # still alive: adopted
        assert dead.plan is not None
        dead.done(0)
        QApplication.processEvents()                # deferred island release
        dead.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(dead)          # the C++ side is really gone
        plan_after = plan_with(rows=[RowIssue("События", 2, "х")])
        dead.set_progress(1, 2)                     # progress tick mid-import
        dead.publish_analysis(plan_after)           # must not resurrect/raise
        dead.publish_analysis_failure("x")
        dead.publish_report(ImportReport())
        dead.publish_import_failure("x")
        assert dead.plan is not plan_after          # publishes were dropped


# small helper: collect a named dialog signal's emits as a context manager
class qtbot_signal:
    def __init__(self, dialog, signal_name):
        self._signal = getattr(dialog, signal_name)
        self.received = []

    def __enter__(self):
        self._signal.connect(lambda *args: self.received.append(args[0] if len(args) == 1 else args))
        return self.received

    def __exit__(self, *exc):
        self._signal.disconnect()
        return False
