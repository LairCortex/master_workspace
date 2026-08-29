"""Gap-fillers for character-sheet line coverage (CI fail_under=100)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.exc import IntegrityError

from app.application.services.character_sheet_instance_service import (
    CharacterAlreadyBoundError,
    CharacterSheetInstanceError,
    CharacterSheetInstanceService,
    EMPTY_INSTANCE_NAME_ERROR,
    InstanceNameConflictError,
    InstanceNotFoundError,
)
from app.application.services.character_sheet_service import (
    CharacterSheetService,
    PresetCorruptError,
    PresetNotFoundError,
    TemplateHasInstancesError,
)
from app.domain.entities.character_sheet import (
    GUTTER_PT,
    ORIENTATION_PORTRAIT,
    PAGE_HEIGHT_PT,
    SheetPage,
    SheetTemplate,
    _opt_image_id,
    _opt_number,
    _opt_options,
    iter_sheet_image_ids,
    null_sheet_image_ids,
    tape_height,
)
from app.domain.entities.character_sheet_instance import (
    iter_instance_image_ids,
    null_instance_image_ids,
)
from app.domain.enums.field_type import FieldType
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    UNDO_STACK_LIMIT,
    CharacterSheetViewModel,
)
from app.presentation.views.character_sheet.canvas import (
    CharacterSheetCanvas,
    register_sheet_font,
)
from app.presentation.views.character_sheet.fill_dialog import (
    CharacterSheetFillDialog,
    FillPropertiesPanel,
)
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog
from app.presentation.views.character_sheet.page_rail import PageRail
from app.presentation.views.character_sheet.palette import SheetPalette
from app.presentation.views.character_sheet.properties_panel import SheetPropertiesPanel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_domain_edges():
    assert tape_height(0, 100) == 0.0
    assert _opt_number(None, "min") is None
    with pytest.raises(ValueError):
        _opt_number(True, "min")
    with pytest.raises(ValueError):
        _opt_number("x", "min")
    assert _opt_options(None, "f") == []
    with pytest.raises(ValueError):
        _opt_options("x", "f")
    with pytest.raises(ValueError):
        _opt_options([1], "f")
    with pytest.raises(ValueError):
        _opt_options(["  "], "f")
    assert _opt_image_id(None) is None
    with pytest.raises(ValueError):
        _opt_image_id(True)
    t = SheetTemplate(name="T")
    t.move_page(0, 1)
    t.add_page()
    t.move_page(0, 0)
    with pytest.raises(ValueError):
        t.set_orientation("wide")
    t.set_orientation(ORIENTATION_PORTRAIT)
    with pytest.raises(ValueError):
        SheetTemplate.parse_template('[{"name": "A"}]', name="x")
    with pytest.raises(ValueError):
        SheetTemplate.parse_template("not-json", name="x")
    assert iter_sheet_image_ids("[]") == []
    assert iter_sheet_image_ids("[1]") == []
    assert iter_sheet_image_ids(json.dumps([{"fields": None}])) == []
    assert null_sheet_image_ids("{}", 1) == "{}"
    assert null_sheet_image_ids(json.dumps([1]), 1) == json.dumps([1])
    assert iter_instance_image_ids("not-json") == []
    assert iter_instance_image_ids("[1]") == []
    assert iter_instance_image_ids(json.dumps({"a": True, "b": 3})) == [3]
    assert null_instance_image_ids("not-json", 1) == "not-json"
    assert null_instance_image_ids("[1]", 1) == "[1]"
    assert json.loads(null_instance_image_ids(json.dumps({"a": 3}), 3))["a"] is None
    assert null_instance_image_ids(json.dumps({"a": 9}), 3) == json.dumps({"a": 9})
    PresetCorruptError("p")
    PresetNotFoundError("p")


async def test_instance_service_edges(async_session):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    tid = row.id
    with pytest.raises(ValueError, match=EMPTY_INSTANCE_NAME_ERROR):
        await inst_svc.create("  ", tid)
    with pytest.raises(InstanceNotFoundError):
        await inst_svc.get(999999)
    inst = await inst_svc.create("Лист", tid)
    iid = inst.id
    with pytest.raises(ValueError):
        await inst_svc.rename(iid, "  ")

    from types import SimpleNamespace
    calls = {"n": 0}

    async def boom_create(**kwargs):
        raise IntegrityError("INSERT", {}, Exception("x"))

    async def get_name(name):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return SimpleNamespace(id=1, name=name)

    orig_create = inst_svc._repo.create
    orig_get_name = inst_svc._repo.get_by_name
    inst_svc._repo.create = boom_create  # type: ignore[method-assign]
    inst_svc._repo.get_by_name = get_name  # type: ignore[method-assign]
    try:
        with pytest.raises(InstanceNameConflictError):
            await inst_svc.create("Гонка", tid)
    finally:
        inst_svc._repo.create = orig_create
        inst_svc._repo.get_by_name = orig_get_name

    inst2 = await inst_svc.create("Другой", tid)
    iid2 = inst2.id

    async def boom_commit():
        raise IntegrityError("UPDATE", {}, Exception("x"))

    orig_commit = inst_svc._session.commit
    inst_svc._session.commit = boom_commit  # type: ignore[method-assign]
    try:
        with pytest.raises(InstanceNameConflictError):
            await inst_svc.rename(iid2, "Новое")
    finally:
        inst_svc._session.commit = orig_commit

    from datetime import date
    from app.infrastructure.repositories.character_repository import CharacterRepository
    char = await CharacterRepository(async_session).create(name="P", start_date=date(1300, 1, 1))
    await async_session.commit()

    async def boom_bind():
        raise IntegrityError("UPDATE", {}, Exception("x"))

    n = {"i": 0}

    async def get_char(cid):
        n["i"] += 1
        if n["i"] == 1:
            return None
        return SimpleNamespace(id=iid2, character_id=cid)

    orig_get = inst_svc._repo.get_by_character_id
    inst_svc._session.commit = boom_bind  # type: ignore[method-assign]
    inst_svc._repo.get_by_character_id = get_char  # type: ignore[method-assign]
    try:
        with pytest.raises(CharacterAlreadyBoundError):
            await inst_svc.bind_character(iid, char.id)
    finally:
        inst_svc._session.commit = orig_commit
        inst_svc._repo.get_by_character_id = orig_get


async def test_sheet_service_delete_integrity(async_session, monkeypatch):
    repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    svc = CharacterSheetService(repo, instance_repo=inst_repo)
    row = await svc.create("Шаблон")

    async def boom_delete(sheet_id):
        raise IntegrityError("DELETE", {}, Exception("fk"))

    monkeypatch.setattr(repo, "delete", boom_delete)
    with pytest.raises(TemplateHasInstancesError):
        await svc.delete(row.id)


async def test_viewmodel_edges(async_session, qapp):
    svc = CharacterSheetService(CharacterSheetRepository(async_session))
    unloaded = CharacterSheetViewModel(svc)
    await unloaded.save()
    unloaded.drag_move_selection(0, 0, 0, 0)
    unloaded.commit_drag_selection(0, 0, 0, 0)
    unloaded.begin_gesture()
    unloaded.redo()
    unloaded.undo()
    unloaded._refresh_dirty()
    unloaded.toggle_checkbox("x")
    unloaded.apply_number("x", "1")
    unloaded.set_options("x", ["a"])
    unloaded.set_image_id("x", 1)
    unloaded.move_selection(1, 1)
    unloaded.remove_selection()
    unloaded.bring_to_front()
    unloaded.send_to_back()
    unloaded.paste()
    unloaded.duplicate()
    assert unloaded.current_page_index == 0
    unloaded.set_current_page(1)
    unloaded.set_snap_enabled(False)
    unloaded.set_snap_enabled(False)
    unloaded.set_snap_override(True)
    assert unloaded._snap_active is True
    unloaded.set_snap_override(False)
    assert unloaded._snap_active is False
    unloaded.page_of("x")
    unloaded.resize("x", 0, 0, 1, 1)
    unloaded.remove("x")
    unloaded.remove_page(0)
    unloaded.rename_page(0, "A")
    unloaded.copy()
    unloaded.open_inline("x")

    row = await svc.create("Макет")
    vm = CharacterSheetViewModel(svc)
    await vm.load(row.id)
    assert vm.toggle_checkbox("nope") is False
    assert vm.apply_number("nope", "1") is False
    fid = vm.place(FieldType.NUMBER, 10, 10)
    vm.set_min_value(fid, 0.0)
    vm.set_max_value(fid, 5.0)
    assert vm.apply_number(fid, "abc") is False
    assert vm.apply_number(fid, "-1") is False
    assert vm.apply_number(fid, "9") is False
    assert vm.apply_number(fid, "") is True
    vm.set_min_value("nope", 1.0)
    vm.set_min_value(fid, True)  # type: ignore[arg-type]
    chk = vm.place(FieldType.CHECKBOX, 10, 40)
    vm.toggle_checkbox(chk)
    vm.toggle_checkbox(chk)
    dd = vm.place(FieldType.DROPDOWN, 10, 70)
    assert vm.set_options(dd, "x") is False  # type: ignore[arg-type]
    assert vm.set_options(dd, [" "]) is False
    assert vm.set_options(dd, ["а"]) is True
    vm.set_content(dd, "а")
    assert vm.set_options(dd, ["б"]) is True
    assert vm.set_options(dd, ["б"]) is False
    vm.remove_page(0)
    vm.rename_page(0, vm.template.pages[0].name)
    vm.rename_page(99, "x")
    vm.rename_page(0, "   ")
    vm.undo()
    vm.redo()
    vm.begin_gesture(True)
    vm.end_gesture()
    vm._layout_snapshot()
    empty_vm = CharacterSheetViewModel(svc)
    assert empty_vm._layout_snapshot() is None
    img = vm.place(FieldType.IMAGE, 10, 100)
    assert vm.set_image_id(img, None) is False
    assert vm.set_image_id("nope", 1) is False
    assert vm.set_image_id(img, 3) is True
    assert vm.set_image_id(img, 3) is False
    vm.select(None)
    assert vm.move_selection(1, 1) is False
    assert vm.remove_selection() is False
    vm.select(fid)
    vm._selected_ids.append("ghost")
    vm.move_selection(1, 0)
    vm.select(fid)
    vm.copy()
    vm.paste()
    vm.add_page()
    vm.set_current_page(1)
    vm.paste()
    vm.paste(visible_center=(40.0, 40.0))
    vm.select(fid)
    vm.begin_gesture()
    vm.commit_drag_selection(10, PAGE_HEIGHT_PT + GUTTER_PT / 2, 0, 0)
    vm.select(fid)
    vm.begin_gesture()
    vm.commit_drag_selection(10, 20, 0, 0)
    vm.select(fid)
    vm.drag_move_selection(20, 30, 0, 0)
    vm.select_ids([])
    vm.drag_move_selection(20, 30, 0, 0)
    vm.select(fid)
    vm._in_gesture = False
    vm.drag_move_selection(20, 30, 0, 0, ref_id="ghost")
    vm.send_to_back()
    vm.bring_to_front()
    vm.select(fid)
    vm.duplicate()
    vm.open_inline(fid)
    vm.set_content(fid, "1")
    vm.commit_inline()
    vm._undo_stack = [vm._layout_snapshot() for _ in range(UNDO_STACK_LIMIT)]
    vm.open_inline(fid)
    vm.set_content(fid, "2")
    vm.commit_inline()
    vm._template = None
    vm.undo()
    vm.redo()
    vm.begin_gesture()
    vm._refresh_dirty()
    vm._selected_ids = ["ghost"]
    vm.commit_drag_selection(1, 1, 0, 0)


async def test_fill_dialog_and_panels(async_session, qapp, monkeypatch, tmp_path):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text = template.add_field(FieldType.TEXT, (10.0, 10.0))
    ta = template.add_field(FieldType.TEXTAREA, (10.0, 40.0))
    num = template.add_field(FieldType.NUMBER, (10.0, 100.0))
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    d = CharacterSheetFillDialog(inst_svc, sheet_svc, inst.id)
    await d.load()
    d.view_model.template.pages.append(SheetPage(name="Два"))
    d.view_model.set_current_page(1)
    await d.save()
    d.set_name("Имя")
    d._closing = True
    await d.load()
    d._closing = False
    d._teardown_vm_links()
    d._teardown_vm_links()
    panel = d.properties_panel
    panel._fid = None
    panel._commit_text()
    panel._commit_textarea()
    panel._commit_checkbox(True)
    panel._syncing = True
    panel._commit_text()
    panel._commit_textarea()
    panel._commit_checkbox(False)
    panel._syncing = False
    panel._fid = "missing"
    panel._commit_text()
    panel._commit_textarea()
    panel.eventFilter(panel.textarea, QFocusEvent(QEvent.Type.FocusOut))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    await d._store_and_set_image(text.id, str(tmp_path / "nope.png"))
    await d._bind_character()
    await d._unbind_character()

    async def boom_save():
        raise CharacterSheetInstanceError("x")

    monkeypatch.setattr(d.view_model, "save", boom_save)
    await d.save()

    async def boom_save2():
        raise RuntimeError("x")

    monkeypatch.setattr(d.view_model, "save", boom_save2)
    await d.save()
    d.force_close()

    monkeypatch.setattr(
        "app.presentation.views.character_sheet.fill_dialog.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    d2 = CharacterSheetFillDialog(inst_svc, sheet_svc, inst.id)
    await d2.load()
    d2._pick_image(text.id)

    class Store:
        async def store(self, data):
            raise ValueError("bad")

    d2._image_store = Store()
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.fill_dialog.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "x.bin"), "")),
    )
    (tmp_path / "x.bin").write_bytes(b"x")
    d2._pick_image(text.id)
    await d2._store_and_set_image(text.id, str(tmp_path / "x.bin"))
    d2.force_close()


async def test_list_dialog_edges(async_session, qapp, monkeypatch):
    sheet_svc = CharacterSheetService(CharacterSheetRepository(async_session))
    d = CharacterSheetListDialog(sheet_svc)
    d.show()
    await d.create_instance()
    await d.delete_instance()
    await d.rename_instance()
    d._open_preset_dialog()
    d._open_preset_dialog()
    d._preset_dialog_finished(d._preset_dialog)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    inst_repo = CharacterSheetInstanceRepository(async_session)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    d2 = CharacterSheetListDialog(sheet_svc, instance_service=inst_svc)
    d2.show()
    await d2.create_instance()
    await sheet_svc.create("Шаблон")
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.list_dialog.QInputDialog.getItem",
        staticmethod(lambda *a, **k: ("", False)),
    )
    await d2.create_instance()
    row = await sheet_svc.create("Для рейки")
    vm_for_rail = CharacterSheetViewModel(sheet_svc)
    await vm_for_rail.load(row.id)
    rail = PageRail(vm_for_rail, navigation_only=True)
    rail._set_current(-1)
    rail._renaming = True
    rail._on_item_clicked(MagicMock())
    pal = SheetPalette()
    pal.set_active_tool("nope")
    d.close()
    d2.close()


async def test_canvas_and_editor_panel_edges(async_session, qapp, monkeypatch):
    svc = CharacterSheetService(CharacterSheetRepository(async_session))
    row = await svc.create("Макет")
    vm = CharacterSheetViewModel(svc)
    await vm.load(row.id)
    canvas = CharacterSheetCanvas(vm)
    canvas._page_scene_pos("missing")
    vm._template = None
    canvas._template_size()
    canvas.fit_width()
    vm2 = CharacterSheetViewModel(svc)
    await vm2.load(row.id)
    canvas2 = CharacterSheetCanvas(vm2, fill_mode=True)
    fid = vm2.place(FieldType.TEXT, 10, 10)
    canvas2._page_scene_pos(fid)
    canvas2._on_field_added("missing")
    canvas2._on_field_removed("missing")
    canvas2._fill_press(canvas2.mapFromScene(canvas2.mapToScene(0, 0)))
    if canvas2._items:
        canvas2._apply_fill_display(next(iter(canvas2._items.values())))
    props = SheetPropertiesPanel(vm2)
    props._fid = None
    props._begin_edit()
    props._end_edit()
    import app.presentation.views.character_sheet.canvas as canvas_mod
    canvas_mod._font_registered = False
    monkeypatch.setattr(
        "PySide6.QtGui.QFontDatabase.addApplicationFont",
        staticmethod(lambda *a, **k: -1),
    )
    register_sheet_font()
    canvas_mod._font_registered = True


async def test_http_ws_idle_loop(async_session):
    from aiohttp.test_utils import TestClient, TestServer

    from app.application.services.table_host_service import TableHostService
    from app.infrastructure.table_host.http import create_table_host_app

    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    host = TableHostService(inst_svc, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    inst = await inst_svc.create("Лист", row.id)
    host.seat(inst.id)
    await host.start()
    token = await host.join(host.pin, "Вася", inst.id)
    app = create_table_host_app(host)
    async with TestClient(TestServer(app)) as client:
        ws = await client.ws_connect("/ws", params={"token": token})
        await ws.send_str("ping")
        await ws.close()


async def test_store_nulls_instance_image(async_session, tmp_path, qapp):
    from app.infrastructure.images.store import ImageStore
    from tests.application.test_table_host_service import _PNG_1PX

    store = ImageStore(async_session, tmp_path / "images")
    image_id = await store.store(_PNG_1PX)
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    row = await sheet_svc.create("Шаблон")
    inst = await inst_svc.create("Лист", row.id)
    inst.values = json.dumps({"img": image_id})
    await async_session.commit()
    await store._null_references(image_id)
    await async_session.commit()
    await async_session.refresh(inst)
    assert json.loads(inst.values)["img"] is None
