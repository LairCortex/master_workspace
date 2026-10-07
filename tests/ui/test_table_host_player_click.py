"""Desk player click — the player's «Лист» window (NRI-0024 task 5.3).

Spec character-sheet-host «Из пульта открывают лист игрока» on the real
composition (app fixture): the desk sheet of a raised table, its players
list fed by a service-level join, and a real mouse click on the row. The
click rides the old route (panel.player_selected → Application delegate →
SheetWindowsManager.on_host_player_selected → open_fill) and opens the
player's Fill window as the exception window of the three-class contract —
it lives and stays live over the open desk sheet. Read-only while the table
is up (the values are the web player's to write); a repeat click on the
same row re-raises the LIVE window instead of stacking a second one; the
window's close releases the slot so the next click builds a fresh one.

The socket stays unset (like the desk-wiring suite): the subject is the
click path, not the wire.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.domain.enums.field_type import FieldType
from app.presentation.views.character_sheet.fill_dialog import CharacterSheetFillDialog
from app.presentation.views.table_host.panel import TableHostPanel
from tests.ui.test_char_sheets_wiring import (
    create_instance_via_list,
    create_via_list,
    open_list,
    wait_editor,
    wait_fill,
)


def _fills() -> list[CharacterSheetFillDialog]:
    return [
        w for w in QApplication.instance().topLevelWidgets()
        if isinstance(w, CharacterSheetFillDialog) and w.isVisible()
    ]


def _click_player_row(panel: TableHostPanel, index: int) -> None:
    """One real mouse click on a players row — press + release with the
    buttons spelled out (the suite's recipe against the stale offscreen
    button state). itemClicked only exists on this route, so the repeat of
    task 5.3 can only be pinned by the mouse."""
    item = panel.player_list.item(index)
    viewport = panel.player_list.viewport()
    pos = panel.player_list.visualItemRect(item).center()
    global_pos = viewport.mapToGlobal(pos)
    for kind, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(viewport, QMouseEvent(
            kind, QPointF(pos), global_pos,
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier,
        ))
        QApplication.processEvents()


async def _raise_table_with_player(
    app, dialog_input, dialog_item, wait_for
) -> tuple[object, TableHostPanel, int, str]:
    """Template + instance through the list, the desk raised with the seat,
    a player «Вася» joined. The start retired the editable Fill (the pre-
    start window of the freshly created instance), so afterwards no Fill
    exists — the desk click is the only opener left. Returns the application,
    the desk panel, the instance id and the TEXT field id."""
    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    fid = editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill = await wait_fill(app, wait_for, "Лист А")
    inst_id = fill.view_model.instance_id
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(inst_id, "Лист А")])
    panel.seat_boxes()[0].setChecked(True)
    await application._start_table()
    assert application._table_host.is_running
    assert application._sheet_fill is None  # the editable Fill was retired
    host = application._table_host
    await host.join(host.pin, "Вася", inst_id)
    await wait_for(lambda: panel.player_list.count() == 1)
    return application, panel, inst_id, fid


async def test_desk_player_click_opens_read_only_fill(
    app, dialog_input, dialog_item, wait_for
):
    """Spec «Быстрый взгляд в лист игрока»: the click on the player's row
    opens that player's Fill window — read-only over the raised table, the
    values the web writes, living as the exception window above the still
    open desk sheet. Exactly one emission for the row-changing click."""
    application, panel, inst_id, fid = await _raise_table_with_player(
        app, dialog_input, dialog_item, wait_for
    )
    seen: list[int] = []
    panel.player_selected.connect(seen.append)

    _click_player_row(panel, 0)
    assert seen == [inst_id], "a desk click must emit player_selected once"

    fill = await wait_fill(app, wait_for, "Лист А")
    assert fill.view_model.instance_id == inst_id
    assert fill.view_model.read_only is True
    assert fill.view_model.set_text(fid, "нет") is False  # the web owns writes
    assert fill.isVisible()
    assert panel.isVisible()  # the exception window lives over the sheet
    assert len(_fills()) == 1


async def test_desk_reclick_raises_the_live_fill_without_a_second(
    app, dialog_input, dialog_item, wait_for, monkeypatch
):
    """Spec «Повторный клик поднимает живое окно»: with the Fill of the same
    player already open, the repeat click on the (still current) row rides
    the press-side channel and re-enters open_fill — the LIVE window is
    raised and reactivated, no second window is created."""
    application, panel, inst_id, _fid = await _raise_table_with_player(
        app, dialog_input, dialog_item, wait_for
    )
    seen: list[int] = []
    panel.player_selected.connect(seen.append)
    _click_player_row(panel, 0)
    fill = await wait_fill(app, wait_for, "Лист А")

    raised: list[bool] = []
    real_raise = fill.raise_

    def spy_raise():
        raised.append(True)
        return real_raise()

    monkeypatch.setattr(fill, "raise_", spy_raise)

    _click_player_row(panel, 0)  # the row stayed current: only the press side can speak
    assert seen == [inst_id, inst_id], (
        "the repeat click must re-emit so the live window is re-raised"
    )
    await wait_for(lambda: raised)  # the SAME window took the raise
    assert application._sheet_fill is fill
    assert fill.isVisible()
    assert len(_fills()) == 1  # no duplicate «Лист» was built


async def test_desk_fill_close_then_click_builds_a_fresh_window(
    app, dialog_input, dialog_item, wait_for
):
    """The closed window releases its slot (the _forget_fill contract): the
    next desk click — again a repeat click on the current row — builds a
    FRESH read-only Fill for the same player, still exactly one on screen."""
    application, panel, inst_id, _fid = await _raise_table_with_player(
        app, dialog_input, dialog_item, wait_for
    )
    seen: list[int] = []
    panel.player_selected.connect(seen.append)
    _click_player_row(panel, 0)
    fill = await wait_fill(app, wait_for, "Лист А")

    fill.close()  # read-only: no dirty guard, a clean close
    await wait_for(lambda: application._sheet_fill is None)

    _click_player_row(panel, 0)
    assert seen == [inst_id, inst_id]
    fresh = await wait_fill(app, wait_for, "Лист А")
    assert fresh is not fill
    assert fresh.view_model.instance_id == inst_id
    assert fresh.view_model.read_only is True
    assert len(_fills()) == 1
