"""PR-026 crash channel of the ENTITY CARD, driven honestly in one process.

PR-003's child (pr003_close_channel_child.py) proved the parking contract on
the .xlsx sheet; this one pins the card's own «Выбрать файл» channel — the
record docs/qa/test-plan-2026-10-03.md «### PR-026» caught THIS button
(EntityCardRoot.qml, objectName entityImagePickButton) killing the process
1/4 of the file-picking galops with Qt's «Object destroyed while one of its
QML signal handlers is in progress».

Same forced state as PR-003, card's own widgets: the real EntityCardDialog
browse button is pressed through its accessibility action (its QML
``onClicked`` → ``requestImagePick`` → the real static
``QFileDialog.getOpenFileName`` runs its nested ``exec()`` on THIS stack),
and a timer inside that loop closes the card — every cycle alternates the
public close entry the record rode: reject («Отмена»/Escape) and accept
(the «Сохранить» completion, ``finish_saving(True)`` — the exact close the
QA galop performed before the process died). With the PR-003 parking the
close is parked and replayed on the outer loop; exit code 0 with ten whole
cycles means the card channel holds.

PR026_NOPARK=1 reproduces the pre-fix shape in the same channel: the mixin's
parking is neutralized (the close schedules its island release right where it
arrives, inside the nested loop) — the island release then destroys the very
button whose handler is still on the stack and Qt aborts the process. That
red shape is what tests/presentation/test_entity_card_close_crash.py pins as
the channel's proof-of-life.

Run under pytest by tests/presentation/test_entity_card_close_crash.py.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

CYCLES = int(os.environ.get("PR026_CYCLES", "10"))
NOPARK = os.environ.get("PR026_NOPARK") == "1"


def neutralize_parking() -> None:
    from app.presentation.qml.island import IslandDialogMixin

    IslandDialogMixin._defer_close_under_modal = lambda self, close_call: False


def run_cycle(app: QApplication, index: int) -> None:
    # Late imports: the QApplication must own the interpreter state first,
    # the same order the app itself composes in.
    from app.presentation.views.entity_card_dialog import EntityCardDialog
    from tests.presentation.qml_helpers import find_item

    dialog = EntityCardDialog(None, "character")
    dialog.show()
    QTest.qWait(20)
    browse = find_item(dialog.quick, "entityImagePickButton")

    # The close the record rode: even cycles answer «Отмена», odd cycles the
    # «Сохранить» completion (finish_saving(True) -> accept) — both are the
    # card's public close entries over the same handler stack.
    use_accept = index % 2 == 1

    def close_file_dialog() -> None:
        modal = app.activeModalWidget()
        if modal is not None:
            modal.reject()

    def close_card_mid_loop() -> None:
        # The card is covered by the nested modal file dialog; this is the
        # press QA's accessibility channel delivered anyway (the zombie).
        assert app.activeModalWidget() is not None, "closer must run inside the exec loop"
        if use_accept:
            dialog.finish_saving(True)
        else:
            dialog.reject()
        QTimer.singleShot(0, close_file_dialog)

    QTimer.singleShot(30, close_card_mid_loop)
    actions = QAccessible.queryAccessibleInterface(browse).actionInterface()
    actions.doAction("Press")  # blocks in the nested loop until the timers drain it
    QTest.qWait(50)  # let the parked close replay on the outer loop

    expected = QDialog.DialogCode.Accepted if use_accept else QDialog.DialogCode.Rejected
    assert dialog.result() == expected, (
        f"cycle {index}: the close never replayed (result {dialog.result()})"
    )
    assert not dialog.isVisible(), f"cycle {index}: the card stayed visible"
    dialog.deleteLater()
    QTest.qWait(20)


def main() -> int:
    app = QApplication(sys.argv)
    if NOPARK:
        neutralize_parking()
        run_cycle(app, 0)
        print("pr026-nopark: survived without the park (defect shape gone?)", flush=True)
        return 0
    for index in range(CYCLES):
        run_cycle(app, index)
    print(f"pr026-channel: {CYCLES} cycles survived", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
