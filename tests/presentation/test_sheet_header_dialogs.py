"""Island-sheet header on the event dialog and the entity card (change
nri-0014-window-contract-and-docs, task 4.2; defects E1, spec qml-shell
«Лист главного окна показан заголовком»).

The rows themselves are the library component (pinned in
test_sheet_header_accessibility); here the usage sites are pinned:

* the header sits at the top of each island root and shows the dialog's own
  windowTitle — the value is threaded from Python into the root, and the
  late ``populate()`` rename rides the same wire («Новое событие» becomes
  «Редактировать событие», scenario «Активный слой опознателен»);
* the close button runs the dialogs' existing cancel route — the view model's
  requestCancel, the very handler «Отмена» uses and the guarded equivalent of
  Esc (``_on_cancel_clicked`` → reject), no second close signal was invented
  (task rule «без нового сигнала-дубля») — so one accessibility Press leaves
  the dialog closed with the rejected result (scenario «Крестик листа
  отменяет»);
* the theme-grab wireframe stays intact with the header on: the dialog's own
  corner pixel is still the ``color.bg.surface`` token — the header carries
  no private fill, so no OS-palette strip can leak at the sheet edge (the
  test_theme_grab pixel contract, recomputed with the header).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QDialog

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item
from tests.ui.test_theme_grab import make_runtime, token_color


def _press_sheet_header_close(dialog):
    iface = QAccessible.queryAccessibleInterface(
        find_item(dialog.quick, "sheetHeaderClose"))
    assert iface is not None, "no accessibility interface on the sheet header close"
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Закрыть"
    iface.actionInterface().doAction("Press")


def _header_title(dialog) -> str:
    return find_item(dialog.quick, "sheetHeaderTitle").property("text")


def test_event_header_shows_the_window_title_and_the_late_edit_rename(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    # The header row is the top element of the island root, and its title is
    # the windowTitle value Python threaded into the scene.
    assert find_item(dialog.quick, "eventSheetHeader") is not None
    assert dialog._root.property("sheetTitle") == "Новое событие"
    assert _header_title(dialog) == "Новое событие"

    # populate() renames the window late — the header follows the same wire.
    dialog.populate(SimpleNamespace(id=7, name="Война"))
    assert dialog.windowTitle() == "Редактировать событие"
    assert dialog._root.property("sheetTitle") == "Редактировать событие"
    assert _header_title(dialog) == "Редактировать событие"


def test_entity_card_header_shows_the_window_title(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)

    assert find_item(dialog.quick, "entitySheetHeader") is not None
    assert dialog._root.property("sheetTitle") == "Карточка: character"
    assert _header_title(dialog) == "Карточка: character"


def test_event_header_close_press_rejects_like_the_cancel_route(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.show()

    _press_sheet_header_close(dialog)

    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_entity_header_close_press_rejects_like_the_cancel_route(qtbot):
    dialog = EntityCardDialog(None, "item")
    qtbot.addWidget(dialog)
    dialog.show()

    _press_sheet_header_close(dialog)

    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected


@pytest.mark.parametrize("kind", ["event", "card"])
def test_header_keeps_the_sheet_surface_token_at_the_window_edge(
    qtbot, tmp_path, kind
):
    # The test_theme_grab contract recomputed with the header on: the dialog's
    # edge pixel (device-independent corner) must still be the surface token —
    # a header that painted its own fill or leaked widgets chrome would show
    # here as a foreign strip.
    runtime = make_runtime(tmp_path, "dark")
    if kind == "event":
        dialog = EventDialog(None, theme=runtime)
    else:
        dialog = EntityCardDialog(None, "character", theme=runtime)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    image = dialog.grab().toImage()
    surface = token_color("color.bg.surface", "dark")
    assert surface != token_color("color.bg.canvas", "dark")  # checks differ
    for x, y in ((0, 0), (1, 1), (1, image.height() - 2), (image.width() - 2, 1)):
        assert image.pixelColor(x, y) == surface, (kind, x, y)
