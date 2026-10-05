"""PR-003 crash channel, driven honestly in one offscreen process.

Reproduction of the QA record verbatim: the browse button of the real
XlsxImportDialog is pressed through its accessibility action (the QML
``onClicked`` of XlsxImportRoot.qml:101 runs on THIS stack), the real static
``QFileDialog.getOpenFileName`` then blocks in its nested ``exec()`` loop —
and inside that loop the sheet itself gets ««Отмена»»-ed, exactly the zombie
state QA hit (modality broken, presses reach the covered sheet).

Pre-fix the ``reject()`` scheduled the island release via a zero-timer that
Qt 6.10 dispatches INSIDE the nested loop; ``setSource(QUrl())`` then
destroyed the browse button whose QML handler is still on the stack and the
process aborted:

    Object 0x... destroyed while one of its QML signal handlers is in
    progress. Most likely the object was deleted synchronously (use
    QObject::deleteLater() instead), or the application is running a nested
    event loop. This behavior is NOT supported!
    file:///.../XlsxImportRoot.qml:101: function() { [native code] }

Exit code 0 with ten whole cycles means the parked-close contract holds.
Run under pytest by tests/presentation/test_xlsx_import_close_crash.py.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

CYCLES = int(os.environ.get("PR003_CYCLES", "10"))


def run_cycle(app: QApplication, index: int) -> None:
    # Late imports: the QApplication must own the interpreter state first,
    # the same order the app itself composes in.
    from app.presentation.views.xlsx_import_dialog import XlsxImportDialog
    from tests.presentation.qml_helpers import find_item

    dialog = XlsxImportDialog()
    dialog.show()
    QTest.qWait(20)
    browse = find_item(dialog.quick, "browseButton")

    def close_file_dialog() -> None:
        modal = app.activeModalWidget()
        if modal is not None:
            modal.reject()

    def press_cancel_mid_loop() -> None:
        # The sheet is covered by the nested modal file dialog; this is the
        # press QA's accessibility channel delivered anyway (the zombie).
        assert app.activeModalWidget() is not None, "closer must run inside the exec loop"
        dialog.reject()
        QTimer.singleShot(0, close_file_dialog)

    QTimer.singleShot(30, press_cancel_mid_loop)
    actions = QAccessible.queryAccessibleInterface(browse).actionInterface()
    actions.doAction("Press")  # blocks in the nested loop until the timers drain it
    QTest.qWait(50)  # let the parked close replay on the outer loop

    assert dialog.result() == 0, f"cycle {index}: the parked close never replayed"
    assert not dialog.isVisible(), f"cycle {index}: the sheet stayed visible"
    dialog.deleteLater()
    QTest.qWait(20)


def main() -> int:
    app = QApplication(sys.argv)
    for index in range(CYCLES):
        run_cycle(app, index)
    print(f"pr003-channel: {CYCLES} cycles survived", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
