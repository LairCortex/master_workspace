"""Sync VMs for R3 pack 1 thin dialogs."""
from __future__ import annotations

from app.presentation.utils.date_utils import DEFAULT_MONTHS
from app.presentation.viewmodels.doc_viewer_view_model import DocViewerViewModel
from app.presentation.viewmodels.image_viewer_view_model import ImageViewerViewModel
from app.presentation.viewmodels.month_settings_view_model import MonthSettingsViewModel
from app.presentation.viewmodels.xlsx_import_view_model import XlsxImportViewModel


def test_month_settings_vm_twelve_names_reset_saved():
    vm = MonthSettingsViewModel({1: "Зимостой", 2: "Февраль"})
    assert vm.nameAt(0) == "Зимостой"
    assert vm.nameAt(1) == ""
    assert vm.placeholderAt(0) == DEFAULT_MONTHS[1]
    assert vm.nameAt(-1) == ""
    assert vm.placeholderAt(99) == ""
    vm.setName(0, "Зимостой")
    vm.setName(0, "Новый")
    assert vm.nameAt(0) == "Новый"
    vm.setName(99, "x")
    captured = []
    vm.saved.connect(captured.append)
    vm.reset()
    assert vm.names == [""] * 12
    vm.setName(0, "  ")
    vm.save()
    result = captured[0]
    assert result[1] == DEFAULT_MONTHS[1]
    assert result[2] == DEFAULT_MONTHS[2]


def test_xlsx_import_vm_path_progress_import_requested():
    vm = XlsxImportViewModel("fmt")
    assert vm.formatText == "fmt"
    assert vm.path == ""
    assert vm.progress == 0
    assert vm.progressVisible is False
    assert vm.importEnabled is True
    vm.path = "/a.xlsx"
    vm.path = "/a.xlsx"
    browsed = []
    imported = []
    vm.browseRequested.connect(lambda: browsed.append(1))
    vm.importRequested.connect(imported.append)
    vm.requestBrowse()
    vm.requestImport()
    assert browsed == [1]
    assert imported == ["/a.xlsx"]
    vm.begin_import()
    assert vm.importEnabled is False
    assert vm.progressVisible is True
    vm.set_progress(1, 4)
    assert vm.progress == 25
    vm.set_progress(0, 0)
    assert vm.progress == 0


def test_image_viewer_vm_source_key():
    vm = ImageViewerViewModel()
    assert vm.unavailable is True
    vm.set_source("image://dialog/abc", used_preview=True, unavailable=False)
    assert vm.source == "image://dialog/abc"
    assert vm.usedPreview is True
    assert vm.unavailable is False


def test_doc_viewer_vm_text():
    vm = DocViewerViewModel("hello")
    assert vm.text == "hello"
    vm.text = "hello"
    vm.text = "world"
    assert vm.text == "world"
