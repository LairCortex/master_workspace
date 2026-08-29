"""Tests for CharacterSheetFillViewModel (task 5.1).

Value-map mutations only: set_text/toggle/set_number/set_dropdown/set_image/
clear_image; number comma→dot and min/max; no move/place; dirty/save/reload
values; reload_layout leaves values; inherit new field; orphan not drawn;
undo stack 50, save does not clear, inline commit is one step.
"""
from __future__ import annotations


import pytest
from PySide6.QtWidgets import QApplication

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import FieldType
from app.domain.entities.character_sheet_instance import display_fields
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    UNDO_STACK_LIMIT,
    CharacterSheetFillViewModel,
)
from app.presentation.viewmodels.character_sheet_viewmodel import TOOL_POINTER


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def services(async_session):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    return sheet_svc, inst_svc


async def _seed(sheet_svc, inst_svc):
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (10.0, 10.0))
    text_f.content = "Иван"
    ta = template.add_field(FieldType.TEXTAREA, (10.0, 40.0))
    ta.content = ""
    chk = template.add_field(FieldType.CHECKBOX, (10.0, 100.0))
    chk.content = "false"
    num = template.add_field(FieldType.NUMBER, (10.0, 130.0))
    num.content = "5"
    num.min_value = 0.0
    num.max_value = 10.0
    dd = template.add_field(FieldType.DROPDOWN, (10.0, 160.0))
    dd.options = ["эльф", "орк"]
    dd.content = "эльф"
    img = template.add_field(FieldType.IMAGE, (10.0, 190.0))
    img.image_id = 7
    lab = template.add_field(FieldType.LABEL, (10.0, 320.0))
    lab.content = "Имя"
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист", row.id)
    ids = {
        "text": text_f.id,
        "textarea": ta.id,
        "chk": chk.id,
        "num": num.id,
        "dd": dd.id,
        "img": img.id,
        "lab": lab.id,
    }
    return inst.id, ids, row.id


@pytest.fixture
async def loaded(services):
    sheet_svc, inst_svc = services
    instance_id, ids, template_id = await _seed(sheet_svc, inst_svc)
    vm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
    await vm.load(instance_id)
    return vm, ids, sheet_svc, template_id, inst_svc, instance_id


class TestMutators:
    async def test_set_text(self, loaded):
        vm, ids, *_ = loaded
        assert vm.set_text(ids["text"], "Пётр") is True
        assert vm.display_value(ids["text"]) == "Пётр"
        assert vm.dirty is True

    async def test_toggle_checkbox(self, loaded):
        vm, ids, *_ = loaded
        assert vm.display_value(ids["chk"]) is False
        assert vm.toggle_checkbox(ids["chk"]) is True
        assert vm.display_value(ids["chk"]) is True
        vm.toggle_checkbox(ids["chk"])
        assert vm.display_value(ids["chk"]) is False

    async def test_set_number_comma_to_dot(self, loaded):
        vm, ids, *_ = loaded
        assert vm.set_number(ids["num"], "1,5") is True
        assert vm.display_value(ids["num"]) == "1.5"

    async def test_set_number_rejects_outside_min_max(self, loaded):
        vm, ids, *_ = loaded
        before = vm.display_value(ids["num"])
        assert vm.set_number(ids["num"], "99") is False
        assert vm.set_number(ids["num"], "abc") is False
        assert vm.set_number(ids["num"], "nan") is False
        assert vm.set_number(ids["num"], "inf") is False
        assert vm.display_value(ids["num"]) == before

    async def test_set_dropdown(self, loaded):
        vm, ids, *_ = loaded
        assert vm.set_dropdown(ids["dd"], "орк") is True
        assert vm.display_value(ids["dd"]) == "орк"
        assert vm.set_dropdown(ids["dd"], "дворф") is False
        assert vm.display_value(ids["dd"]) == "орк"

    async def test_set_and_clear_image(self, loaded):
        vm, ids, *_ = loaded
        assert vm.display_value(ids["img"]) == 7
        assert vm.set_image(ids["img"], 3) is True
        assert vm.display_value(ids["img"]) == 3
        assert vm.clear_image(ids["img"]) is True
        assert vm.display_value(ids["img"]) is None


class TestNoLayoutMutators:
    def test_no_move_or_place(self):
        for name in ("place", "move", "drag_move", "commit_drag", "add_page", "remove_page"):
            assert not hasattr(CharacterSheetFillViewModel, name)


class TestDirtySaveReload:
    async def test_save_and_reload_values(self, loaded):
        vm, ids, sheet_svc, template_id, inst_svc, instance_id = loaded
        vm.set_text(ids["text"], "Пётр")
        await vm.save()
        assert vm.dirty is False

        other = CharacterSheetFillViewModel(inst_svc, sheet_svc)
        await other.load(instance_id)
        assert other.display_value(ids["text"]) == "Пётр"
        assert other.dirty is False

    async def test_reload_discards_unsaved_values(self, loaded):
        vm, ids, *_ = loaded
        vm.set_text(ids["text"], "Пётр")
        await vm.reload()
        assert vm.display_value(ids["text"]) == "Иван"
        assert vm.dirty is False


class TestReloadLayout:
    async def test_reload_layout_updates_geometry_keeps_values(self, loaded):
        vm, ids, sheet_svc, template_id, *_ = loaded
        vm.set_text(ids["text"], "Пётр")
        before = dict(vm.values)

        template = await sheet_svc.load(template_id)
        field = template.get_field(ids["text"])
        field.x = 200.0
        extra = template.add_field(FieldType.TEXT, (10.0, 400.0))
        extra.content = "новое"
        await sheet_svc.update_pages(template_id, template)

        await vm.reload_layout()
        assert vm.template.get_field(ids["text"]).x == 200.0
        assert vm.values == before
        assert vm.display_value(ids["text"]) == "Пётр"
        assert extra.id not in vm.values
        assert vm.display_value(extra.id) == "новое"

    async def test_reload_layout_closes_inline(self, loaded):
        vm, ids, *_ = loaded
        vm.open_inline(ids["text"])
        assert vm.inline_field_id == ids["text"]
        await vm.reload_layout()
        assert vm.inline_field_id is None

    async def test_orphan_not_drawn(self, loaded):
        vm, ids, *_ = loaded
        vm.values["ghost"] = "сирота"
        drawn = [f.id for f in display_fields(vm.template)]
        assert "ghost" not in drawn
        assert ids["text"] in drawn


class TestUndo:
    async def test_undo_stack_capped_at_50(self, loaded):
        vm, ids, *_ = loaded
        for i in range(UNDO_STACK_LIMIT + 1):
            vm.set_text(ids["text"], str(i))
        for _ in range(UNDO_STACK_LIMIT):
            assert vm.can_undo is True
            vm.undo()
        assert vm.can_undo is False
        assert vm.display_value(ids["text"]) == "0"

    async def test_save_does_not_clear_undo(self, loaded):
        vm, ids, *_ = loaded
        vm.set_text(ids["text"], "Пётр")
        await vm.save()
        assert vm.dirty is False
        vm.undo()
        assert vm.display_value(ids["text"]) == "Иван"
        assert vm.dirty is True

    async def test_inline_commit_is_one_step(self, loaded):
        vm, ids, *_ = loaded
        vm.open_inline(ids["text"])
        vm.set_text(ids["text"], "а")
        vm.set_text(ids["text"], "аб")
        vm.set_text(ids["text"], "абв")
        vm.commit_inline()
        vm.undo()
        assert vm.display_value(ids["text"]) == "Иван"
        assert vm.can_undo is False

    async def test_undo_during_inline_cancels_inline(self, loaded):
        vm, ids, *_ = loaded
        vm.set_text(ids["text"], "saved")
        vm.open_inline(ids["text"])
        vm.set_text(ids["text"], "draft")
        vm.undo()
        assert vm.inline_field_id is None
        assert vm.display_value(ids["text"]) == "saved"
        vm.undo()
        assert vm.display_value(ids["text"]) == "Иван"


class TestBind:
    async def test_bind_and_unbind(self, loaded, async_session):
        from datetime import date

        from app.infrastructure.repositories.character_repository import (
            CharacterRepository,
        )

        vm, _ids, _sheet, _tid, inst_svc, instance_id = loaded
        char = await CharacterRepository(async_session).create(
            name="Герой", start_date=date(1300, 1, 1)
        )
        await async_session.commit()
        await vm.bind_character(char.id)
        assert vm.character_id == char.id
        row = await inst_svc.get(instance_id)
        assert row.character_id == char.id
        await vm.unbind_character()
        assert vm.character_id is None
        assert (await inst_svc.get(instance_id)).character_id is None


class TestReadOnly:
    async def test_read_only_blocks_mutations_and_inline(self, loaded):
        vm, ids, *_ = loaded
        vm.open_inline(ids["text"])
        vm.set_read_only(True)
        assert vm.read_only
        assert vm.inline_field_id is None
        assert vm.set_text(ids["text"], "Пётр") is False
        assert vm.display_value(ids["text"]) == "Иван"
        vm.open_inline(ids["text"])
        assert vm.inline_field_id is None
        assert vm.toggle_checkbox(ids["chk"]) is False
        assert vm.set_number(ids["num"], "1") is False
        assert vm.set_dropdown(ids["dd"], "орк") is False
        assert vm.set_image(ids["img"], 1) is False
        vm.apply_remote_value(ids["text"], "с стола")
        assert vm.display_value(ids["text"]) == "с стола"
        assert vm.dirty is False


class TestProtocolAndEdges:
    def test_unloaded_protocol(self, services):
        sheet_svc, inst_svc = services
        vm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
        assert vm.template_id is None
        assert vm.tool == TOOL_POINTER
        assert vm.snap_enabled is False
        assert vm.selected_ids == []
        assert vm.page_of("x") is None
        assert vm.display_value("x") is None
        assert vm.displayed_fields() == []
        assert vm.set_content("x", "t") is False
        assert vm.apply_number("x", "1") is False
        vm.set_name("n")
        assert vm.name == "n"
        vm.select("a")
        vm.select("a")
        vm.set_current_page(3)
        vm.open_inline("x")
        vm.commit_inline()
        vm.cancel_inline()
        vm.undo()
        vm.redo()

    async def test_unloaded_async_noops(self, services):
        sheet_svc, inst_svc = services
        vm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
        await vm.save()
        await vm.reload()
        await vm.reload_layout()
        await vm.bind_character(1)
        await vm.unbind_character()

    async def test_loaded_protocol_and_edges(self, loaded):
        vm, ids, *_ = loaded
        assert vm.template_id is not None
        assert vm.tool == TOOL_POINTER
        assert vm.page_of(ids["text"]) == 0
        assert vm.displayed_fields()
        assert vm.display_value("nope") is None
        assert vm.set_content(ids["text"], "Пётр") is True
        assert vm.set_content(ids["text"], "Пётр") is False
        assert vm.set_text(ids["chk"], "x") is False
        assert vm.apply_number(ids["num"], "2") is True
        assert vm.set_number(ids["num"], "2") is True
        assert vm.set_number(ids["num"], "") is True
        assert vm.set_number("nope", "1") is False
        assert vm.set_number(ids["num"], "-1") is False
        vm.select(ids["text"])
        vm.select(ids["text"])
        vm.set_current_page(0)
        vm.open_inline("missing")
        vm.open_inline(ids["chk"])
        vm.open_inline(ids["text"])
        vm.open_inline(ids["text"])
        vm.commit_inline()
        vm.cancel_inline()
        vm.open_inline(ids["text"])
        vm.set_text(ids["text"], "черновик")
        vm.cancel_inline()
        assert vm.toggle_checkbox("nope") is False
        assert vm.set_dropdown("nope", "x") is False
        assert vm.set_dropdown(ids["dd"], "эльф") is False
        assert vm.set_image("nope", 1) is False
        assert vm.set_image(ids["img"], 3) is True
        assert vm.set_image(ids["img"], 3) is False
        vm.set_text(ids["text"], "а")
        vm.undo()
        vm.redo()
        vm.redo()
        vm.open_inline(ids["text"])
        vm.redo()
        vm.undo()
        vm._undo_stack = [dict(vm.values) for _ in range(UNDO_STACK_LIMIT)]
        vm._redo_stack = [dict(vm.values)]
        vm.redo()
        vm.open_inline(ids["text"])
        vm.set_text(ids["text"], "шаг")
        vm._undo_stack = [dict(vm.values) for _ in range(UNDO_STACK_LIMIT)]
        vm.commit_inline()

