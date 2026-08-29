"""Application wiring for the table host (tasks 5.3 / 5.4)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.domain.enums.field_type import FieldType
from app.presentation.views.character_sheet.fill_dialog import CharacterSheetFillDialog
from app.presentation.views.table_host.panel import TableHostPanel
from tests.ui.test_char_sheets_wiring import (
    create_instance_via_list,
    create_via_list,
    make_second_game,
    open_list,
    question_no,
    question_yes,
    wait_editor,
    wait_fill,
)


def _check_all_seats(panel: TableHostPanel) -> None:
    for i in range(panel.seat_list.count()):
        panel.seat_list.item(i).setCheckState(Qt.CheckState.Checked)


async def test_menu_opens_table_panel(app, wait_for):
    application, window = app
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    assert isinstance(application._table_host_panel, TableHostPanel)
    assert application._table_host_panel.isVisible()


async def test_dirty_fill_prompt_rejects_table_start(
    app, dialog_input, dialog_item, wait_for, monkeypatch
):
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
    fill.view_model.set_text(fid, "черновик")
    assert fill.view_model.dirty
    question_no(monkeypatch)
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(fill.view_model.instance_id, "Лист А")])
    _check_all_seats(panel)
    await application._start_table()
    assert not application._table_host.is_running
    assert fill.view_model.dirty


async def test_fill_is_read_only_when_table_open(
    app, dialog_input, dialog_item, wait_for
):
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
    _check_all_seats(panel)
    await application._start_table()
    assert application._table_host.is_running
    await application._open_fill(inst_id)
    await wait_for(lambda: application._sheet_fill is not None)
    fill = application._sheet_fill
    assert fill.view_model.read_only
    assert fill.view_model.set_text(fid, "нет") is False


async def test_fill_writable_after_table_stop(
    app, dialog_input, dialog_item, wait_for
):
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
    _check_all_seats(panel)
    await application._start_table()
    await application._open_fill(inst_id)
    await wait_for(lambda: application._sheet_fill is not None)
    assert application._sheet_fill.view_model.read_only
    await application._stop_table()
    fill = application._sheet_fill
    assert fill is not None
    assert fill.view_model.read_only is False
    assert fill.save_button.isVisible()
    assert fill.view_model.set_text(fid, "снова") is True
    await fill.save()
    await wait_for(lambda: not fill.view_model.dirty)
    fill.set_read_only(True)
    await application._start_table()
    assert application._table_host.is_running
    assert application._sheet_fill is fill
    assert fill.view_model.read_only is True


async def test_restart_table_uses_current_checkboxes(
    app, dialog_input, dialog_item, wait_for
):
    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill_a = await wait_fill(app, wait_for, "Лист А")
    id_a = fill_a.view_model.instance_id
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист Б")
    fill_b = await wait_fill(app, wait_for, "Лист Б")
    id_b = fill_b.view_model.instance_id
    fill_b.force_close()
    application._sheet_fill = None
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(id_a, "Лист А"), (id_b, "Лист Б")])
    _check_all_seats(panel)
    await application._start_table()
    assert application._table_host.is_running
    await application._stop_table()
    panel.seat_list.blockSignals(True)
    panel.seat_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    panel.seat_list.blockSignals(False)
    await application._start_table()
    assert id_a in application._table_host.seated_ids
    assert id_b not in application._table_host.seated_ids


async def test_switch_game_stops_table(
    app, dialog_input, dialog_item, tmp_games_dir, wait_for, monkeypatch
):
    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill = await wait_fill(app, wait_for, "Лист А")
    inst_id = fill.view_model.instance_id
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(inst_id, "Лист А")])
    _check_all_seats(panel)
    await application._start_table()
    host = application._table_host
    assert host.is_running
    path_b = await make_second_game(tmp_games_dir)
    question_yes(monkeypatch)
    await application._on_game_selected(path_b)
    assert not host.is_running


async def test_player_click_switches_preview(
    app, dialog_input, dialog_item, wait_for
):
    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill_a = await wait_fill(app, wait_for, "Лист А")
    id_a = fill_a.view_model.instance_id
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист Б")
    fill_b = await wait_fill(app, wait_for, "Лист Б")
    id_b = fill_b.view_model.instance_id
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(id_a, "Лист А"), (id_b, "Лист Б")])
    _check_all_seats(panel)
    await application._start_table()
    await application._open_fill(id_a)
    await wait_for(lambda: application._sheet_fill.view_model.instance_id == id_a)
    viewer = application._sheet_fill
    await application._open_fill(id_b)
    await wait_for(lambda: application._sheet_fill.view_model.instance_id == id_b)
    assert application._sheet_fill is viewer
    fills = [
        w for w in QApplication.instance().topLevelWidgets()
        if isinstance(w, CharacterSheetFillDialog) and w.isVisible()
    ]
    assert len(fills) == 1


async def test_start_without_seats_shows_error(
    app, wait_for, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    application, window = app
    application._table_host.set_http(None)
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    warned = []

    def fake_warn(*a, **k):
        warned.append(a)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(fake_warn))
    await application._start_table()
    assert not application._table_host.is_running
    assert warned
    application._on_host_values(1, "f", "v")
    await application._stop_table()


async def test_table_host_none_guards(app):
    application, _window = app
    host = application._table_host
    panel = application._table_host_panel
    application._table_host = None
    application._on_table_host()
    await application._stop_table()
    application._table_host = host
    application._table_host_panel = None
    await application._start_table()
    await application._refresh_table_host_panel()
    application._table_host_panel = panel


async def test_dirty_fill_yes_starts_table(
    app, dialog_input, dialog_item, wait_for, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

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
    fill.view_model.set_text(fid, "черновик")
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(fill.view_model.instance_id, "Лист А")])
    _check_all_seats(panel)
    question_yes(monkeypatch)
    await application._start_table()
    assert application._table_host.is_running
    assert application._sheet_fill is None


async def test_port_busy_shows_error(
    app, dialog_input, dialog_item, wait_for, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    class Busy:
        async def start(self, **kwargs):
            raise OSError("busy")

        async def stop(self):
            pass

    application, window = app
    application._table_host.set_http(Busy())
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill = await wait_fill(app, wait_for, "Лист А")
    inst_id = fill.view_model.instance_id
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(inst_id, "Лист А")])
    _check_all_seats(panel)
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    )
    await application._start_table()
    assert not application._table_host.is_running


async def test_host_values_update_open_fill(
    app, dialog_input, dialog_item, wait_for
):
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
    _check_all_seats(panel)
    await application._start_table()
    await application._open_fill(inst_id)
    await wait_for(lambda: application._sheet_fill is not None)
    application._on_host_values(inst_id, fid, "с веба")
    assert application._sheet_fill.view_model.display_value(fid) == "с веба"
    application._on_host_values(inst_id + 99, fid, "нет")
    assert application._sheet_fill.view_model.display_value(fid) == "с веба"


async def test_design_save_broadcasts_layout(
    app, dialog_input, dialog_item, wait_for, monkeypatch
):
    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill = await wait_fill(app, wait_for, "Лист А")
    inst_id = fill.view_model.instance_id
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(inst_id, "Лист А")])
    _check_all_seats(panel)
    await application._start_table()
    await application._open_fill(inst_id)
    await wait_for(lambda: application._sheet_fill is not None)
    calls: list[int] = []

    async def wrapped(tid):
        calls.append(tid)

    application._table_host.broadcast_layout = wrapped
    await application._reload_fill_after_design(editor)
    assert calls == [editor.view_model.sheet_id]

    async def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(application._sheet_fill.view_model, "reload_layout", boom)
    await application._reload_fill_after_design(editor)
    await application._reload_fill_after_design(None)
    application._on_design_saved(editor)
    class Other:
        class view_model:
            sheet_id = -1
    application._on_design_saved(Other())
    await application._reload_fill_after_design(Other())


async def test_design_save_broadcasts_without_open_fill(
    app, dialog_input, dialog_item, wait_for
):
    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill = await wait_fill(app, wait_for, "Лист А")
    inst_id = fill.view_model.instance_id
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(inst_id, "Лист А")])
    _check_all_seats(panel)
    await application._start_table()
    fill.force_close()
    application._sheet_fill = None
    calls: list[int] = []

    async def wrapped(tid):
        calls.append(tid)

    application._table_host.broadcast_layout = wrapped
    application._on_design_saved(editor)
    await wait_for(lambda: calls == [editor.view_model.sheet_id])


async def test_preview_switch_load_error(
    app, dialog_input, dialog_item, wait_for, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from app.application.services.character_sheet_instance_service import (
        CharacterSheetInstanceError,
    )

    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill_a = await wait_fill(app, wait_for, "Лист А")
    id_a = fill_a.view_model.instance_id
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист Б")
    fill_b = await wait_fill(app, wait_for, "Лист Б")
    id_b = fill_b.view_model.instance_id
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(id_a, "Лист А"), (id_b, "Лист Б")])
    _check_all_seats(panel)
    await application._start_table()
    await application._open_fill(id_a)
    await wait_for(lambda: application._sheet_fill is not None)

    async def boom(_iid):
        raise CharacterSheetInstanceError("нет")

    monkeypatch.setattr(application._sheet_fill, "load_instance", boom)
    warned = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: warned.append(a) or QMessageBox.StandardButton.Ok),
    )
    await application._open_fill(id_b)
    assert warned


async def test_refresh_cards_and_rename_and_editor_edges(
    app, dialog_input, dialog_item, wait_for
):
    application, window = app
    await application._refresh_character_cards()
    application._window = None
    await application._refresh_character_cards()
    application._window = window
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Шаблон")
    editor = await wait_editor(app, wait_for, "Шаблон")
    editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Шаблон", "Лист А")
    fill = await wait_fill(app, wait_for, "Лист А")
    application._on_instance_renamed(fill.view_model.instance_id, "Новое")
    application._on_host_player_selected(fill.view_model.instance_id)
    editor._sync_orientation()
    editor._on_paste()
    tmpl = editor.view_model.template
    editor.view_model._template = None
    editor._sync_orientation(None)
    editor.view_model._template = tmpl

