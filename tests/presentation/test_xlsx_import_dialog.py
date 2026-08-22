"""Characterization tests for XlsxImportDialog — import dialog widget."""
from PySide6.QtWidgets import QFileDialog, QMessageBox

import pytest

from app.presentation.views.xlsx_import_dialog import (
    ENTITY_LABELS,
    FORMAT_TEXTS,
    XlsxImportDialog,
)

ALL_TYPES = ["event", "character", "location", "organization", "item"]


class TestStaticData:
    def test_format_texts_cover_all_entity_types(self):
        assert set(FORMAT_TEXTS) == set(ALL_TYPES)

    def test_entity_labels_cover_all_entity_types(self):
        assert set(ENTITY_LABELS) == set(ALL_TYPES)

    def test_event_format_mentions_required_columns(self):
        assert "name" in FORMAT_TEXTS["event"]
        assert "start_date" in FORMAT_TEXTS["event"]


class TestDialogConstruction:
    @pytest.mark.parametrize("etype", ALL_TYPES)
    def test_title_contains_entity_label(self, qtbot, etype):
        d = XlsxImportDialog(etype)
        qtbot.addWidget(d)
        assert ENTITY_LABELS[etype] in d.windowTitle()
        assert ".xlsx" in d.windowTitle()

    @pytest.mark.parametrize("etype", ALL_TYPES)
    def test_format_text_shows_type_format(self, qtbot, etype):
        d = XlsxImportDialog(etype)
        qtbot.addWidget(d)
        assert d.format_text.toPlainText() == FORMAT_TEXTS[etype]
        assert d.format_text.isReadOnly()
        assert d.entity_type() == etype

    def test_unknown_type_falls_back_to_raw_string(self, qtbot):
        d = XlsxImportDialog("something")
        qtbot.addWidget(d)
        assert d.windowTitle() == "Импорт something из .xlsx"
        assert d.format_text.toPlainText() == ""

    def test_initial_state(self, qtbot):
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        assert d.path_edit.text() == ""
        assert d.progress_bar.value() == 0
        assert d.get_path() == ""
        assert d.import_btn.isEnabled()
        assert d.import_btn.text() == "Проверить и импортировать"


class TestBrowse:
    def test_browse_sets_path(self, qtbot, mocker, tmp_path):
        p = tmp_path / "file.xlsx"
        p.write_text("x")
        mocker.patch.object(QFileDialog, "getOpenFileName", return_value=(str(p), ""))
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d._on_browse()
        assert d.path_edit.text() == str(p)
        assert d.get_path() == str(p)

    def test_browse_cancellation_keeps_path_empty(self, qtbot, mocker):
        mocker.patch.object(QFileDialog, "getOpenFileName", return_value=("", ""))
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d._on_browse()
        assert d.path_edit.text() == ""
        assert d.get_path() == ""


class TestImportRequested:
    def test_click_with_path_emits_signal(self, qtbot):
        d = XlsxImportDialog("character")
        qtbot.addWidget(d)
        d.path_edit.setText("/tmp/batch.xlsx")
        received = []
        d.import_requested.connect(received.append)
        with qtbot.waitSignal(d.import_requested, timeout=1000):
            d.import_btn.click()
        assert received == ["/tmp/batch.xlsx"]
        # Button is locked and progress bar reset to 0 while import runs.
        assert not d.import_btn.isEnabled()
        assert d.progress_bar.value() == 0

    def test_click_with_empty_path_warns_and_does_not_emit(self, qtbot, mocker):
        warn = mocker.patch.object(QMessageBox, "warning")
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        emitted = []
        d.import_requested.connect(emitted.append)
        d._on_import_clicked()
        warn.assert_called_once()
        assert emitted == []
        assert d.import_btn.isEnabled()
        assert d.get_path() == ""


class TestProgress:
    def test_set_progress_partial(self, qtbot):
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d.set_progress(1, 4)
        assert d.progress_bar.value() == 25
        d.set_progress(3, 4)
        assert d.progress_bar.value() == 75

    def test_set_progress_complete(self, qtbot):
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d.set_progress(2, 2)
        assert d.progress_bar.value() == 100

    def test_set_progress_zero_total_resets(self, qtbot):
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d.set_progress(2, 2)
        d.set_progress(0, 0)
        assert d.progress_bar.value() == 0

    def test_set_progress_zero_current(self, qtbot):
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d.set_progress(0, 5)
        assert d.progress_bar.value() == 0


class TestGetPath:
    def test_path_edit_fallback_when_internal_empty(self, qtbot):
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d.path_edit.setText("/a/b.xlsx")
        assert d.get_path() == "/a/b.xlsx"

    def test_internal_path_wins_over_edit(self, qtbot):
        d = XlsxImportDialog("event")
        qtbot.addWidget(d)
        d._path = "/clicked/path.xlsx"
        d.path_edit.setText("/other.xlsx")
        assert d.get_path() == "/clicked/path.xlsx"
