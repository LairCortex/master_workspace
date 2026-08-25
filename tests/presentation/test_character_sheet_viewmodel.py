"""Tests for CharacterSheetViewModel (tasks 5.1–5.4)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypdf import PdfReader

from app.application.services.character_sheet_service import CharacterSheetNameConflict
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
    MIN_FIELD_HEIGHT,
    MIN_FIELD_WIDTH,
    UNDO_LIMIT,
)
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation


@pytest.fixture
def vm(qapp):
    viewmodel = CharacterSheetViewModel(AsyncMock())
    viewmodel.create_new("Лист")
    return viewmodel


def add(vm, field_type=FieldType.SHORT_TEXT, page=0, x=100.0, y=100.0, **kw) -> str:
    return vm.add_field(field_type, page, x, y, **kw).id


def page_fields(vm, page=0):
    return vm.template.pages[page].fields


# ── opening / creating ────────────────────────────────────────────────────


class TestOpening:
    @pytest.mark.asyncio
    async def test_open_existing_sheet(self, qapp):
        service = AsyncMock()
        template = make_template()
        service.load.return_value = template
        vm = CharacterSheetViewModel(service)
        assert await vm.open(5) is True
        assert vm.sheet_id == 5
        assert vm.template is template
        assert vm.dirty is False

    @pytest.mark.asyncio
    async def test_open_missing_sheet(self, qapp):
        service = AsyncMock()
        service.load.return_value = None
        vm = CharacterSheetViewModel(service)
        assert await vm.open(404) is False
        assert vm.sheet_id is None


# ── field operations (5.1) ────────────────────────────────────────────────


class TestFieldOperations:
    def test_add_field_placed_with_defaults_and_selected(self, vm):
        fid = add(vm, FieldType.SHORT_TEXT, x=20.0, y=40.0)
        field = page_fields(vm)[0]
        assert field.id == fid
        assert field.type is FieldType.SHORT_TEXT
        assert field.x == 20.0 and field.y == 40.0
        assert field.w == 180.0 and field.h == 24.0  # palette defaults
        assert len(field.id) == 32 and int(field.id, 16) >= 0
        assert vm.selected_field_id == fid
        assert vm.dirty and vm.can_undo

    def test_add_field_clamps_min_size(self, vm):
        vm.add_field(FieldType.SHORT_TEXT, 0, 20.0, 40.0, w=5.0, h=5.0)
        f = page_fields(vm)[0]
        assert (f.w, f.h) == (MIN_FIELD_WIDTH, MIN_FIELD_HEIGHT)

    def test_add_field_per_type_defaults(self, vm):
        add(vm, FieldType.HEADING)
        h = page_fields(vm)[-1]
        assert h.font_size == 16.0 and (h.w, h.h) == (250.0, 24.0)
        add(vm, FieldType.CHECKBOX)
        c = page_fields(vm)[-1]
        assert (c.w, c.h) == (20.0, 20.0)
        add(vm, FieldType.PORTRAIT)
        p = page_fields(vm)[-1]
        assert (p.w, p.h) == (120.0, 150.0)

    def test_move_field_changes_x_y(self, vm):
        vm.set_snap(False)  # isolate the move from grid snapping
        fid = add(vm, x=100.0, y=100.0)
        assert vm.set_field_rect(fid, 300.0, 400.0, 180.0, 24.0) is True
        f = page_fields(vm)[0]
        assert (f.x, f.y, f.w, f.h) == (300.0, 400.0, 180.0, 24.0)

    def test_resize_enforces_min_size(self, vm):
        vm.set_snap(False)
        fid = add(vm)
        vm.set_field_rect(fid, 10.0, 10.0, 1.0, 1.0)
        f = page_fields(vm)[0]
        assert f.w == MIN_FIELD_WIDTH and f.h == MIN_FIELD_HEIGHT

    def test_remove_field(self, vm):
        a, b = add(vm), add(vm, x=300.0)
        assert vm.selected_field_id == b  # last added is selected
        assert vm.remove_field(a) is True
        assert [f.id for f in page_fields(vm)] == [b]
        assert vm.selected_field_id == b  # valid selection survives
        assert vm.remove_field(b) is True
        assert vm.selected_field_id is None  # selecting a removed field clears it
        assert vm.remove_field(a) is False  # already gone

    def test_duplicate_field_new_id_offset_position(self, vm):
        src = add(vm, x=100.0, y=100.0)
        clone = vm.duplicate_field(src)
        assert clone is not None
        assert clone.id != src
        assert (clone.x, clone.y) == (120.0, 120.0)
        assert [f.id for f in page_fields(vm)] == [src, clone.id]
        assert vm.selected_field_id == clone.id
        assert vm.duplicate_field("missing") is None

    def test_copy_paste_internal_buffer(self, vm):
        src = add(vm, x=100.0, y=100.0)
        assert vm.copy_selected() is True
        pasted = vm.paste(dx=20.0, dy=20.0)
        assert pasted is not None
        assert pasted.id not in {src}
        assert (pasted.x, pasted.y) == (120.0, 120.0)  # +offset, snap to 20
        assert len(page_fields(vm)) == 2
        assert vm.paste() is not None  # the buffer stays valid for repeat pastes

    def test_paste_without_buffer_is_noop(self, vm):
        assert vm.paste() is None

    def test_copy_without_selection_fails(self, vm):
        assert vm.copy_selected() is False

    def test_bring_forward_send_backward(self, vm):
        a, b, c = add(vm), add(vm, x=200.0), add(vm, x=300.0)
        assert [f.id for f in page_fields(vm)] == [a, b, c]
        assert vm.send_backward(a) is False  # already at the back
        assert vm.bring_forward(b) is True   # b: index 1 → 2
        assert [f.id for f in page_fields(vm)] == [a, c, b]
        assert vm.send_backward(c) is True   # c: index 1 → 0
        assert [f.id for f in page_fields(vm)] == [c, a, b]
        assert vm.bring_forward(c) is True   # c: index 0 → 1
        assert [f.id for f in page_fields(vm)] == [a, c, b]
        assert vm.bring_forward(b) is False  # already at the front
        assert vm.bring_forward("nope") is False
        assert vm.send_backward("nope") is False

    def test_update_field_properties(self, vm):
        fid = add(vm, FieldType.NUMBER)
        assert vm.update_field(
            fid,
            label="Сила", default_value="10", font_size=14.0,
            min_value=1, max_value=30, options=["А"], initial_checked=True,
        ) is True
        f = page_fields(vm)[0]
        assert f.label == "Сила" and f.default_value == "10"
        assert f.font_size == 14.0
        assert (f.min_value, f.max_value) == (1, 30)
        assert f.options == ["А"] and f.initial_checked is True

    def test_set_field_rect_unknown_id(self, vm):
        assert vm.set_field_rect("nope", 0.0, 0.0, 10.0, 10.0) is False

    def test_update_field_unknown_id(self, vm):
        assert vm.update_field("nope", label="x") is False

    def test_update_field_rejects_invalid_raises(self, vm):
        fid = add(vm)
        with pytest.raises(ValueError):
            vm.update_field(fid, bogus=1)
        with pytest.raises(ValueError):
            vm.update_field(fid, font_size=0)
        with pytest.raises(ValueError):
            vm.update_field(fid, min_value=5, max_value=3)

    def test_select_unknown_id_ignored(self, vm):
        vm.select("nope")
        assert vm.selected_field_id is None
        fid = add(vm)
        vm.select(fid)
        vm.select(None)
        assert vm.selected_field_id is None
        assert vm.selected_field is None
        assert vm.selected_page_index is None

    def test_selected_accessors_with_stale_id(self, vm):
        add(vm)  # selects a field
        vm._selected_field_id = "missing"  # internal inconsistency guard
        assert vm.selected_field is None
        assert vm.selected_page_index is None
        assert vm.selected_field_id == "missing"


# ── undo / redo (5.1) ─────────────────────────────────────────────────────


class TestUndoRedo:
    def test_undo_redo_add(self, vm):
        fid = add(vm, x=100.0)
        assert vm.undo() and page_fields(vm) == []
        assert vm.redo() and page_fields(vm)[0].id == fid
        assert not vm.can_redo

    def test_undo_redo_move(self, vm):
        fid = add(vm, x=100.0)
        vm.set_field_rect(fid, 500.0, 500.0, 100.0, 20.0)
        vm.undo()
        assert vm.template.pages[0].fields[0].x == 100.0
        vm.redo()
        assert vm.template.pages[0].fields[0].x == 500.0

    def test_undo_limit(self, vm):
        for i in range(UNDO_LIMIT + 1):
            add(vm, x=float(i * 40))
        # the first snapshot was evicted by the limit
        for _ in range(UNDO_LIMIT):
            vm.undo()
        assert len(page_fields(vm)) == 1
        assert not vm.can_undo

    def test_redo_cleared_by_new_operation(self, vm):
        add(vm)
        vm.undo()
        assert vm.can_redo
        add(vm, x=300.0)
        assert not vm.can_redo
        assert vm.can_undo

    def test_undo_redo_on_empty_stacks(self, vm):
        assert vm.undo() is False
        assert vm.redo() is False

    def test_undo_drops_stale_selection(self, vm):
        add(vm)
        vm.undo()
        assert vm.selected_field_id is None

    def test_dirty_survives_undo(self, vm):
        add(vm)
        vm.undo()
        assert vm.dirty is True


# ── page operations (5.2) ─────────────────────────────────────────────────


class TestPageOperations:
    def test_add_page_auto_name(self, vm):
        assert vm.add_page() == 1
        assert vm.template.pages[1].name == "Стр 2"
        idx = vm.add_page("Задний план")
        assert vm.template.pages[idx].name == "Задний план"

    def test_rename_page(self, vm):
        vm.add_page()
        assert vm.rename_page(1, "Вторая") is True
        assert vm.template.pages[1].name == "Вторая"
        assert vm.rename_page(99, "X") is False
        assert vm.rename_page(1, "") is False

    def test_remove_page_with_and_without_fields(self, vm):
        add(vm)
        assert vm.add_page() == 1
        assert vm.remove_page(99) is False  # out of range
        assert vm.remove_page(1) is True
        assert len(vm.template.pages) == 1
        assert vm.remove_page(0) is False  # last page is protected

    def test_clipboard_page_index_shifted_on_page_removal(self, vm):
        add(vm, x=50.0)  # page 0
        vm.add_page()
        add(vm, page=1, x=100.0)
        assert vm.copy_selected() is True  # copied from page index 1
        assert vm.remove_page(0) is True
        pasted = vm.paste()
        assert pasted is not None
        assert len(vm.template.pages[0].fields) == 2  # pasted into the surviving page

    def test_move_page_up_down(self, vm):
        vm.add_page()
        vm.add_page()
        names = [p.name for p in vm.template.pages]
        assert vm.move_page_up(2) is True
        assert [p.name for p in vm.template.pages] == [names[0], names[2], names[1]]
        assert vm.move_page_down(0) is True
        assert [p.name for p in vm.template.pages] == [names[2], names[0], names[1]]
        assert vm.move_page_up(0) is False
        assert vm.move_page_down(2) is False

    def test_remove_page_clears_selection_on_it(self, vm):
        add(vm)
        assert vm.add_page() == 1
        assert vm.remove_page(0) is True
        assert vm.selected_field_id is None

    def test_set_orientation_scales_all_pages(self, vm):
        add(vm, x=100.0, y=100.0)  # w=180, h=24
        vm.add_page()
        add(vm, page=1, x=200.0, y=60.0)
        assert vm.set_orientation(SheetOrientation.PORTRAIT) is True

        kx = 595.28 / 841.89
        ky = 841.89 / 595.28
        first, second = [page.fields[0] for page in vm.template.pages]
        assert vm.template.orientation is SheetOrientation.PORTRAIT
        assert (first.x, first.y, first.w, first.h) == (
            round(100 * kx, 2), round(100 * ky, 2), round(180 * kx, 2), round(24 * ky, 2))
        assert (second.x, second.y) == (round(200 * kx, 2), round(60 * ky, 2))
        # ids are preserved by the scaling
        assert vm.selected_field is not None
        # same orientation is a no-op
        assert vm.set_orientation(SheetOrientation.PORTRAIT) is False


# ── snap (5.3) ────────────────────────────────────────────────────────────


class TestSnap:
    def test_snap_default_step(self, vm):
        # default: enabled, step 20
        assert vm.snap_enabled is True
        assert vm.snap_step == 20.0
        add(vm, x=25.0, y=66.0)
        f = page_fields(vm)[0]
        assert (f.x, f.y) == (20.0, 60.0)

    def test_snap_custom_step(self, vm):
        vm.set_snap(True, step=30.0)
        add(vm, x=40.0, y=50.0)
        f = page_fields(vm)[0]
        assert (f.x, f.y) == (30.0, 60.0)

    def test_snap_disabled(self, vm):
        vm.set_snap(False)
        add(vm, x=25.5, y=66.75)
        f = page_fields(vm)[0]
        assert (f.x, f.y) == (25.5, 66.75)

    def test_snap_applies_to_resize(self, vm):
        vm.set_snap(True, step=20.0)
        fid = add(vm)
        vm.set_field_rect(fid, 15.0, 25.0, 105.0, 55.0)
        f = page_fields(vm)[0]
        assert (f.x, f.y, f.w, f.h) == (20.0, 20.0, 100.0, 60.0)


# ── save / export (5.4) ───────────────────────────────────────────────────


class TestSaveAndExport:
    @pytest.mark.asyncio
    async def test_save_new_template(self, qapp):
        service = AsyncMock()
        row = MagicMock()
        row.id = 7
        service.create.return_value = row
        vm = CharacterSheetViewModel(service)
        vm.create_new("Лист")
        add(vm)

        assert await vm.save() is True
        service.create.assert_awaited_once()
        assert vm.sheet_id == 7
        assert vm.dirty is False

    @pytest.mark.asyncio
    async def test_save_updated_template(self, qapp):
        service = AsyncMock()
        row = MagicMock()
        row.id = 3
        service.update.return_value = row
        vm = CharacterSheetViewModel(service)
        vm._sheet_id = 3  # simulate an opened sheet
        vm._template = make_template()

        assert await vm.save() is True
        service.update.assert_awaited_once_with(3, vm._template)

    @pytest.mark.asyncio
    async def test_save_conflict_reports_and_keeps_dirty(self, qapp):
        service = AsyncMock()
        service.create.side_effect = CharacterSheetNameConflict("Лист")
        vm = CharacterSheetViewModel(service)
        vm.create_new("Лист")
        add(vm)  # make the sheet dirty
        messages = []
        vm.status_message.connect(messages.append)

        assert await vm.save() is False
        assert vm.sheet_id is None
        assert vm.dirty is True
        assert messages == ["Имя «Лист» уже существует"]

    @pytest.mark.asyncio
    async def test_save_update_conflict_reports(self, qapp):
        service = AsyncMock()
        service.update.side_effect = CharacterSheetNameConflict("Другое")
        vm = CharacterSheetViewModel(service)
        vm._sheet_id = 1
        vm._template = make_template()
        add(vm)
        assert await vm.save() is False
        assert vm.dirty is True

    @pytest.mark.asyncio
    async def test_save_missing_row_reports(self, qapp):
        service = AsyncMock()
        service.update.return_value = None
        vm = CharacterSheetViewModel(service)
        vm._sheet_id = 99
        vm._template = make_template()
        assert await vm.save() is False

    @pytest.mark.asyncio
    async def test_export_pdf_writes_file(self, vm, tmp_path: Path):
        fid = add(vm, FieldType.HEADING)
        vm.update_field(fid, label="Заголовок")
        assert await vm.export_pdf(tmp_path / "sheet.pdf") is True
        reader = PdfReader(str(tmp_path / "sheet.pdf"))
        assert reader.metadata.title == "Лист"

    @pytest.mark.asyncio
    async def test_export_pdf_bad_path_reports(self, vm, qapp):
        messages = []
        vm.status_message.connect(messages.append)
        assert await vm.export_pdf(Path("/nonexistent-dir-xyz/s.pdf")) is False
        assert messages and "PDF" in messages[0]


def make_template(name: str = "Лист"):
    from app.domain.entities.character_sheet import SheetPage, SheetTemplate

    return SheetTemplate(name=name, orientation=SheetOrientation.LANDSCAPE,
                         pages=[SheetPage(name="Стр 1")])
