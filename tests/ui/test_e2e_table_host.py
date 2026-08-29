"""E2E: table start → join TestClient → field in DB → stop (task 6.1)."""
from __future__ import annotations

import json

from aiohttp.test_utils import TestClient, TestServer

from app.domain.enums.field_type import FieldType
from app.infrastructure.table_host.http import create_table_host_app
from tests.ui.conftest import query_db
from tests.ui.test_char_sheets_wiring import (
    create_instance_via_list,
    create_via_list,
    open_list,
    wait_editor,
    wait_fill,
)


async def test_e2e_start_join_field_persists_then_stop(
    app, dialog_input, dialog_item, wait_for
):
    application, window = app
    application._table_host.set_http(None)
    list_dlg = await open_list(app, wait_for)
    create_via_list(list_dlg, dialog_input, "Макет")
    editor = await wait_editor(app, wait_for, "Макет")
    fid = editor.view_model.place(FieldType.TEXT, 30.0, 30.0)
    await editor.save()
    await wait_for(lambda: not editor.view_model.dirty)
    create_instance_via_list(list_dlg, dialog_item, dialog_input, "Макет", "Лист")
    fill = await wait_fill(app, wait_for, "Лист")
    inst_id = fill.view_model.instance_id

    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    from PySide6.QtCore import Qt
    panel.set_instances([(inst_id, "Лист")])
    for i in range(panel.seat_list.count()):
        panel.seat_list.item(i).setCheckState(Qt.CheckState.Checked)
    await application._start_table()
    host = application._table_host
    assert host.is_running
    pin = host.pin

    app_http = create_table_host_app(host)
    async with TestClient(TestServer(app_http)) as client:
        join = await client.post(
            "/api/join",
            json={"pin": pin, "name": "Вася", "instance_id": inst_id},
        )
        assert join.status == 200
        token = (await join.json())["token"]
        field = await client.post(
            "/api/field",
            json={"field_id": fid, "value": "с браузера"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert field.status == 200

    rows = query_db(
        application._db_path,
        'SELECT "values" FROM character_sheet_instances WHERE id = ?',
        (inst_id,),
    )
    assert json.loads(rows[0][0])[fid] == "с браузера"

    await application._stop_table()
    assert not host.is_running
    async with TestClient(TestServer(create_table_host_app(host))) as client:
        again = await client.post(
            "/api/field",
            json={"field_id": fid, "value": "после стопа"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert again.status == 409
    rows = query_db(
        application._db_path,
        'SELECT "values" FROM character_sheet_instances WHERE id = ?',
        (inst_id,),
    )
    assert json.loads(rows[0][0])[fid] == "с браузера"
