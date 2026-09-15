"""ObjectName contracts and live-retheme for R3 pack 1 islands."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from app.presentation.views.doc_viewer_dialog import DocViewerDialog
from app.presentation.views.image_viewer_dialog import ImageViewerDialog
from app.presentation.views.month_settings_dialog import MonthSettingsDialog
from app.presentation.views.xlsx_import_dialog import XlsxImportDialog
from tests.presentation.qml_helpers import find_item, walk_items


def _names(root) -> set[str]:
    return {root.objectName()} | {i.objectName() for i in walk_items(root)}


def test_month_settings_root_object_names(qtbot):
    dlg = MonthSettingsDialog()
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    names = _names(root)
    for i in range(1, 13):
        assert f"monthField{i}" in names
    assert "saveButton" in names
    assert "resetButton" in names
    assert root.property("defaultButton").objectName() == "saveButton"


def test_xlsx_import_root_object_names(qtbot):
    dlg = XlsxImportDialog()
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    names = _names(root)
    assert "formatArea" in names
    assert find_item(dlg.quick, "formatArea").property("readOnly") is True
    assert "pathField" in names
    assert "browseButton" in names
    assert "downloadButton" in names
    assert "progressBar" in names
    assert "importButton" in names
    assert root.property("defaultButton").objectName() == "importButton"


def test_image_viewer_root_object_names(qtbot):
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.red)
    dlg = ImageViewerDialog(QPixmap.fromImage(img))
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    names = _names(root)
    assert "viewerImage" in names
    assert "closeButton" in names
    assert root.property("defaultButton").objectName() == "closeButton"


def test_doc_viewer_root_has_textarea_no_buttons(qtbot, tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("hello", encoding="utf-8")
    dlg = DocViewerDialog("T", path)
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    names = _names(root)
    assert "docText" in names
    assert "saveButton" not in names
    assert "closeButton" not in names
    assert find_item(dlg.quick, "docText").property("readOnly") is True


def test_month_island_live_retheme(qtbot, tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    dlg = MonthSettingsDialog(theme=runtime)
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    before = root.objectName()
    assert runtime.toggle() is True
    assert dlg.quick.rootObject() is root
    assert root.objectName() == before
    assert find_item(dlg.quick, "monthField1") is not None


def test_xlsx_island_live_retheme(qtbot, tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    dlg = XlsxImportDialog(theme=runtime)
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    assert runtime.toggle() is True
    assert dlg.quick.rootObject() is root
    assert find_item(dlg.quick, "formatArea") is not None


def test_image_island_live_retheme(qtbot, tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    dlg = ImageViewerDialog(None, None, theme=runtime)
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    assert runtime.toggle() is True
    assert dlg.quick.rootObject() is root
    assert find_item(dlg.quick, "unavailableText") is not None


def test_doc_island_live_retheme(qtbot, tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    dlg = DocViewerDialog("t", tmp_path / "missing.md", theme=runtime)
    qtbot.addWidget(dlg)
    root = dlg.quick.rootObject()
    assert runtime.toggle() is True
    assert dlg.quick.rootObject() is root
    assert find_item(dlg.quick, "docText") is not None


def test_month_enter_saves(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    dlg = MonthSettingsDialog()
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.saved, timeout=2000):
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
        )
        dlg.keyPressEvent(event)


def test_month_other_key_falls_through(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    dlg = MonthSettingsDialog()
    qtbot.addWidget(dlg)
    event = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier
    )
    dlg.keyPressEvent(event)


def test_month_cancel(qtbot):
    dlg = MonthSettingsDialog()
    qtbot.addWidget(dlg)
    dlg._root.cancelRequested.emit()
    dlg.done(0)


def test_xlsx_enter_and_import_signal(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    dlg = XlsxImportDialog()
    qtbot.addWidget(dlg)
    received = []
    dlg.analyze_requested.connect(received.append)
    dlg.vm.path = "/tmp/a.xlsx"
    assert dlg.get_path() == "/tmp/a.xlsx"
    # Enter hits the default primary button → the analyze intent.
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    dlg.keyPressEvent(event)
    assert received == ["/tmp/a.xlsx"]
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    dlg.keyPressEvent(event)
    dlg.done(0)


def test_image_enter_closes(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    dlg = ImageViewerDialog(None, None)
    qtbot.addWidget(dlg)
    dlg.show()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    dlg.keyPressEvent(event)
    qtbot.waitUntil(lambda: not dlg.isVisible(), timeout=2000)


def test_doc_done_releases(qtbot, tmp_path):
    dlg = DocViewerDialog("t", tmp_path / "x.md")
    qtbot.addWidget(dlg)
    dlg.done(0)
