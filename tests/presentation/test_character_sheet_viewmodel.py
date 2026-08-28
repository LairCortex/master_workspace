"""Tests for CharacterSheetViewModel (tasks 4.1 of add-character-sheet-a1 and
add-character-sheet-a-playable).

VM is the single in-memory source of truth for the template (design D4):
tool/selection/inline state, geometry clamping, stable ids, dirty tracking and
save/reload through the service. Real in-memory DB + real service (no mocks of
the persistence path), qapp for the QObject signals.

A-playable part: page operations (add after current / remove with confirm /
last page / reorder / rename), template-wide orientation, cross-page field
relocation (drag, drop on another sheet, drop in the gutter).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from PySide6.QtWidgets import QApplication

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.entities.character_sheet import (
    GUTTER_PT,
    ORIENTATION_LANDSCAPE,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    SheetTemplate,
)
from app.domain.enums.field_type import FieldType
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    TOOL_POINTER,
    TOOL_PLACE_LABEL,
    TOOL_PLACE_TEXT,
    TOOL_PLACE_TEXTAREA,
    CharacterSheetViewModel,
    field_type_for_tool,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def service(async_session):
    return CharacterSheetService(CharacterSheetRepository(async_session))


@pytest.fixture
async def vm(service):
    """VM loaded on a fresh empty sheet with id 1... whatever it gets."""
    row = await service.create("Лист")
    vm = CharacterSheetViewModel(service)
    await vm.load(row.id)
    return vm


# ── load / initial state ───────────────────────────────────────────────────

async def test_load_initial_state(vm):
    assert vm.template is not None
    assert vm.sheet_id == vm.template.id
    assert vm.dirty is False
    assert vm.tool == TOOL_POINTER
    assert vm.selection is None
    assert vm.inline_field_id is None
    assert vm.template.page.fields == []


async def test_tool_constants_cover_palette(vm, qtbot):
    assert field_type_for_tool(TOOL_POINTER) is None
    assert field_type_for_tool(TOOL_PLACE_LABEL) is FieldType.LABEL
    assert field_type_for_tool(TOOL_PLACE_TEXT) is FieldType.TEXT
    assert field_type_for_tool(TOOL_PLACE_TEXTAREA) is FieldType.TEXTAREA

    seen = []
    vm.tool_changed.connect(seen.append)
    vm.set_tool(TOOL_PLACE_LABEL)
    vm.set_tool(TOOL_PLACE_LABEL)  # same tool — no signal
    vm.set_tool(TOOL_POINTER)
    assert seen == [TOOL_PLACE_LABEL, TOOL_POINTER]
    assert vm.tool == TOOL_POINTER


# ── place ──────────────────────────────────────────────────────────────────

async def test_place_resets_tool_selects_and_no_inline(vm, qtbot):
    added = []
    selected = []
    inlined = []
    vm.field_added.connect(added.append)
    vm.selection_changed.connect(selected.append)
    vm.inline_changed.connect(inlined.append)

    vm.set_tool(TOOL_PLACE_TEXT)
    field_id = vm.place(FieldType.TEXT, 100, 200)

    assert vm.tool == TOOL_POINTER          # tool reset after placement
    assert vm.selection == field_id         # the new field is selected
    assert vm.inline_field_id is None       # inline editing is NOT opened
    assert added == [field_id]
    assert selected == [field_id]
    assert inlined == []
    assert len(vm.template.page.fields) == 1
    f = vm.template.get_field(field_id)
    assert (f.x, f.y, f.w, f.h) == (100, 200, 120, 18)
    assert vm.dirty is True


async def test_place_clamps_to_page(vm):
    # click near the right/bottom edge: default 72x18 label must stay on page
    field_id = vm.place(FieldType.LABEL, PAGE_WIDTH_PT - 10, PAGE_HEIGHT_PT - 5)
    f = vm.template.get_field(field_id)
    assert f.x == PAGE_WIDTH_PT - 72
    assert f.y == PAGE_HEIGHT_PT - 18
    assert f.x >= 0 and f.y >= 0
    assert f.x + f.w <= PAGE_WIDTH_PT and f.y + f.h <= PAGE_HEIGHT_PT


async def test_z_order_later_on_top(vm):
    a = vm.place(FieldType.LABEL, 10, 10)
    b = vm.place(FieldType.TEXT, 20, 20)
    fields = vm.template.page.fields
    assert [f.id for f in fields] == [a, b]  # b was placed later — index 1


# ── ids are stable ─────────────────────────────────────────────────────────

async def test_id_stable_across_move_resize_content(vm):
    fid = vm.place(FieldType.TEXT, 50, 50)
    original = vm.template.get_field(fid)

    vm.move(fid, 60, 70)
    vm.resize(fid, 5, 5, 40, 20)
    vm.set_content(fid, "привет")
    vm.set_font_size(fid, 12.0)

    assert vm.template.page.fields[0] is original
    assert vm.template.page.fields[0].id == fid
    assert set(f.id for f in vm.template.page.fields) == {fid}


async def test_remove_neighbor_id_unchanged(vm):
    a = vm.place(FieldType.LABEL, 10, 10)
    b = vm.place(FieldType.TEXT, 60, 60)
    b_obj = vm.template.get_field(b)

    vm.remove(a)

    fields = vm.template.page.fields
    assert [f.id for f in fields] == [b]
    assert fields[0] is b_obj
    # removing again is a no-op
    vm.remove(a)
    assert [f.id for f in fields] == [b]


# ── moving / resizing (clamped) ────────────────────────────────────────────

async def test_move_clamped(vm):
    fid = vm.place(FieldType.LABEL, 100, 100)  # 72x18
    vm.move(fid, -50, PAGE_HEIGHT_PT)  # way below & left of the page
    f = vm.template.get_field(fid)
    assert f.x == 0
    assert f.y == PAGE_HEIGHT_PT - f.h
    vm.move(fid, PAGE_WIDTH_PT, PAGE_HEIGHT_PT)
    assert f.x == PAGE_WIDTH_PT - f.w
    assert f.y == PAGE_HEIGHT_PT - f.h


async def test_resize_clamped(vm):
    fid = vm.place(FieldType.LABEL, 10, 10)
    vm.resize(fid, 0, 0, PAGE_WIDTH_PT * 2, PAGE_HEIGHT_PT * 2)
    f = vm.template.get_field(fid)
    assert (f.x, f.y, f.w, f.h) == (0, 0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT)
    # minimum size
    vm.resize(fid, 0, 0, 1, 1)
    f = vm.template.get_field(fid)
    assert f.w == 16 and f.h == 16
    # resizing a moved field keeps it inside the page
    vm.resize(fid, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 80, 80)
    assert f.x <= PAGE_WIDTH_PT - f.w
    assert f.y <= PAGE_HEIGHT_PT - f.h


async def test_move_resize_nochange_no_signal(vm):
    fid = vm.place(FieldType.LABEL, 100, 100)
    await vm.save()
    f = vm.template.get_field(fid)
    geometry = []
    vm.field_geometry_changed.connect(geometry.append)
    assert vm.dirty is False

    vm.move(fid, f.x, f.y)            # same position — nothing happens
    vm.resize(fid, f.x, f.y, f.w, f.h)
    assert geometry == []
    assert vm.dirty is False          # pure no-op: not even dirtied


async def test_mutators_on_unknown_id_are_noop(vm):
    vm.move("nope", 1, 2)
    vm.resize("nope", 1, 2, 20, 20)
    vm.set_content("nope", "x")
    vm.set_font_size("nope", 8)
    vm.remove("nope")
    vm.open_inline("nope")
    assert vm.template.page.fields == []
    assert vm.dirty is False
    assert vm.inline_field_id is None


# ── selection ──────────────────────────────────────────────────────────────

async def test_single_selection(vm):
    a = vm.place(FieldType.LABEL, 10, 10)
    b = vm.place(FieldType.TEXT, 50, 50)
    assert vm.selection == b

    vm.select(a)
    assert vm.selection == a
    vm.select(b)
    assert vm.selection == b
    vm.select(None)
    assert vm.selection is None

    # clicking through removal of the selected field clears the selection
    vm.select(b)
    vm.remove(b)
    assert vm.selection is None


async def test_opening_inline_clears_on_removal(vm):
    fid = vm.place(FieldType.LABEL, 10, 10)
    vm.open_inline(fid)
    assert vm.inline_field_id == fid
    vm.remove(fid)
    assert vm.inline_field_id is None
    assert vm.selection is None


# ── inline editing state ───────────────────────────────────────────────────

async def test_open_inline_snapshots_and_commit(vm):
    fid = vm.place(FieldType.TEXT, 10, 10)
    vm.set_tool(TOOL_POINTER)
    vm.open_inline(fid)
    assert vm.inline_field_id == fid
    assert vm.selection == fid

    # typing goes through set_content: one buffer, no second copy
    vm.set_content(fid, "новое значение")
    assert vm.template.get_field(fid).content == "новое значение"
    assert vm.dirty is True

    vm.commit_inline()
    assert vm.inline_field_id is None
    assert vm.selection == fid
    assert vm.template.get_field(fid).content == "новое значение"


async def test_commit_inline_without_opening_is_noop(vm):
    vm.commit_inline()
    assert vm.inline_field_id is None
    assert vm.dirty is False


async def test_cancel_inline_restores_text(vm):
    fid = vm.place(FieldType.LABEL, 10, 10)
    vm.set_content(fid, "первоначальное")
    await vm.save()

    vm.open_inline(fid)
    vm.set_content(fid, "изменено")
    vm.cancel_inline()

    assert vm.inline_field_id is None
    assert vm.template.get_field(fid).content == "первоначальное"
    assert vm.selection == fid          # the field stays selected
    # a cancelled edit is not a layout change: the sheet is back to its
    # saved state and must not be marked dirty (no spurious close prompt)
    assert vm.dirty is False


async def test_cancel_inline_keeps_pre_existing_dirty(vm):
    fid = vm.place(FieldType.LABEL, 10, 10)  # unsaved placement
    vm.open_inline(fid)
    vm.set_content(fid, "черновик")
    vm.cancel_inline()
    assert vm.template.get_field(fid).content == ""
    assert vm.dirty is True             # the unsaved placement is still there


async def test_cancel_inline_without_changes_keeps_content(vm):
    fid = vm.place(FieldType.LABEL, 10, 10)
    vm.set_content(fid, "текст")
    await vm.save()
    vm.open_inline(fid)
    vm.cancel_inline()
    assert vm.template.get_field(fid).content == "текст"
    assert vm.dirty is False          # no change happened — not dirtied


async def test_set_content_nochange_no_signal(vm):
    fid = vm.place(FieldType.LABEL, 10, 10)
    vm.set_content(fid, "abc")
    await vm.save()
    content = []
    vm.field_content_changed.connect(content.append)
    vm.set_content(fid, "abc")
    assert content == []
    assert vm.dirty is False


# ── dirty / save / reload ──────────────────────────────────────────────────

async def test_save_writes_pages_and_resets_dirty(vm, service):
    fid = vm.place(FieldType.TEXT, 30, 40)
    vm.set_content(fid, "список дел")
    assert vm.dirty is True

    dirty = []
    vm.dirty_changed.connect(dirty.append)
    await vm.save()

    assert vm.dirty is False
    assert dirty == [False]
    row = await service._repo.get_by_id(vm.sheet_id)
    template = SheetTemplate.from_pages_json(row.pages, name=row.name)
    saved = template.page.fields[0]
    assert saved.id == fid
    assert saved.content == "список дел"
    assert (saved.x, saved.y) == (30, 40)

    # saving again while clean is a no-op for the flag
    await vm.save()
    assert vm.dirty is False
    assert dirty == [False]


async def test_reload_after_unsaved_move_restores_geometry(vm, service):
    fid = vm.place(FieldType.TEXT, 30, 40)
    await vm.save()
    saved_row = await service._repo.get_by_id(vm.sheet_id)
    before = SheetTemplate.from_pages_json(saved_row.pages, name=saved_row.name)
    original = (before.page.fields[0].x, before.page.fields[0].y)

    vm.move(fid, 111, 222)   # unsaved
    assert (vm.template.get_field(fid).x, vm.template.get_field(fid).y) == (111, 222)
    vm.resize(fid, 111, 222, 60, 60)  # unsaved, same corner
    assert vm.dirty is True
    f = vm.template.get_field(fid)
    assert (f.x, f.y, f.w, f.h) == (111, 222, 60, 60)

    await vm.reload()

    f = vm.template.get_field(fid)
    assert (f.x, f.y, f.w, f.h) == original + (120, 18)
    assert vm.dirty is False
    assert vm.selection is None
    assert vm.tool == TOOL_POINTER
    # id survived the reload
    assert vm.template.get_field(fid) is not None


# ── edge guards ────────────────────────────────────────────────────────────

async def test_unloaded_vm_mutators_are_noop(service):
    vm = CharacterSheetViewModel(service)
    assert vm.template is None
    assert vm.move("x", 1, 2) is False
    assert vm.resize("x", 1, 2, 20, 20) is False
    assert vm.set_content("x", "t") is False
    assert vm.set_font_size("x", 12) is False
    assert vm.remove("x") is False
    # place/save before load must not crash (interactive canvas during load)
    assert vm.place(FieldType.LABEL, 0, 0) == ""
    await vm.save()
    vm.open_inline("x")
    vm.select("x")
    assert vm.selection == "x"          # selection is transient state, no template
    assert vm.dirty is False
    assert vm.template is None


async def test_cancel_inline_without_opening_is_noop(vm):
    assert vm.dirty is False
    vm.cancel_inline()
    assert vm.inline_field_id is None
    assert vm.dirty is False


async def test_reload_resets_place_tool_back_to_pointer(vm):
    vm.set_tool(TOOL_PLACE_TEXTAREA)
    assert vm.tool == TOOL_PLACE_TEXTAREA
    await vm.reload()
    assert vm.tool == TOOL_POINTER
    assert vm.selection is None
    assert vm.dirty is False


# ── A-playable: pages (add / remove / reorder / rename) ────────────────────

async def test_page_state_defaults(vm):
    assert vm.page_count == 1
    assert vm.current_page_index == 0
    assert vm.page_of(vm.place(FieldType.LABEL, 10, 10)) == 0


async def test_add_page_inserts_after_current_and_becomes_current(vm, qtbot):
    changed = []
    vm.pages_changed.connect(lambda: changed.append("pages"))
    current = []
    vm.current_page_changed.connect(current.append)

    vm.add_page(after_index=0)  # current is 0

    assert vm.page_count == 2
    assert vm.current_page_index == 1          # the new page is current
    assert vm.template.pages[1].name == "Страница 2"
    assert vm.template.pages[1].fields == []
    assert changed == ["pages"]
    assert current == [1]
    assert vm.dirty is True


async def test_add_page_after_middle_page(vm):
    vm.add_page(after_index=0)   # P1
    vm.add_page(after_index=0)   # insert after P0 → between P0 and P1
    assert vm.page_count == 3
    assert [p.name for p in vm.template.pages] == [
        "Страница 1", "Страница 3", "Страница 2"
    ]
    assert vm.current_page_index == 1


async def test_remove_last_page_is_refused(vm):
    assert vm.remove_page(0) is False
    assert vm.page_count == 1


async def test_remove_nonempty_page_requires_confirm(vm):
    vm.place(FieldType.LABEL, 10.0, 10.0)   # field on page 0
    vm.add_page(after_index=0)               # empty page 1

    assert vm.remove_page(0) is False        # non-empty, no confirm → refused
    assert vm.page_count == 2
    assert vm.template.pages[0].fields != []

    assert vm.remove_page(0, confirmed=True) is True
    assert vm.page_count == 1
    assert vm.template.pages[0].fields == []  # the page's fields are gone
    assert vm.dirty is True


async def test_remove_empty_page_needs_no_confirm(vm):
    vm.add_page(after_index=0)
    assert vm.remove_page(1) is True
    assert vm.page_count == 1


async def test_remove_page_adjusts_current_and_selection(vm):
    a = vm.place(FieldType.LABEL, 10.0, 10.0)      # page 0 (current)
    vm.add_page(after_index=0)                       # page 1, current
    b = vm.place(FieldType.TEXT, 10.0, 10.0)         # field on page 1
    assert vm.selection == b

    vm.remove_page(1, confirmed=True)

    assert vm.page_count == 1
    assert vm.current_page_index == 0
    assert vm.selection is None       # the selected field's page is gone
    assert vm.template.get_field(a) is not None

    # removing the page before current shifts the current page down by one
    vm.remove(a)                      # P0 becomes empty
    vm.add_page(after_index=0)        # [P0, P2] — current: P2 (1)
    vm.add_page(after_index=0)        # [P0, P3, P2] — current: P3 (1)
    vm.remove_page(0)                 # empty P0 goes — P3 shifts to index 0
    assert vm.current_page_index == 0


async def test_move_page_reorders(vm):
    vm.add_page(after_index=0)
    vm.add_page(after_index=1)
    names = [p.name for p in vm.template.pages]

    vm.move_page(0, 2)
    assert [p.name for p in vm.template.pages] == [names[1], names[2], names[0]]

    vm.move_page(2, 0)
    assert [p.name for p in vm.template.pages] == names


async def test_move_page_current_follows_the_page(vm):
    vm.add_page(after_index=0)   # P0, P1; current 1
    assert vm.current_page_index == 1
    vm.move_page(1, 0)           # the current page moves to 0
    assert vm.current_page_index == 0


async def test_rename_page(vm, qtbot):
    vm.add_page(after_index=0)

    assert vm.rename_page(1, "Навыки") is True
    assert vm.template.pages[1].name == "Навыки"

    assert vm.rename_page(1, "   ") is False        # empty name refused
    assert vm.template.pages[1].name == "Навыки"
    assert vm.rename_page(99, "X") is False         # out of range refused
    assert vm.rename_page(-1, "X") is False
    assert vm.dirty is True


async def test_page_operations_survive_save_reload(vm, service):
    vm.add_page(after_index=0)
    fid = vm.place(FieldType.TEXT, 20.0, 20.0, page_index=1)
    vm.rename_page(1, "Вторая")
    vm.set_current_page(0)
    vm.add_page(after_index=0)   # insert between
    await vm.save()

    row = await service._repo.get_by_id(vm.sheet_id)
    saved = SheetTemplate.from_pages_json(row.pages, name=row.name)
    assert [p.name for p in saved.pages] == ["Страница 1", "Страница 3", "Вторая"]
    assert saved.pages[2].fields[0].id == fid

    await vm.reload()
    assert vm.page_count == 3
    assert vm.page_of(fid) == 2


# ── A-playable: orientation (one per template, clamp without scale) ────────

async def test_set_orientation_clamps_fields_without_scaling(vm, qtbot):
    # a field near the bottom of the portrait page
    fid = vm.place(FieldType.TEXTAREA, 100.0, PAGE_HEIGHT_PT - 20)
    before = (vm.template.get_field(fid).w, vm.template.get_field(fid).h)

    vm.set_orientation(ORIENTATION_LANDSCAPE)

    f = vm.template.get_field(fid)
    assert vm.template.page_size == (PAGE_HEIGHT_PT, PAGE_WIDTH_PT)
    assert (f.w, f.h) == before            # no proportional scaling
    assert f.y == PAGE_WIDTH_PT - f.h      # clamped into the shorter page
    assert f.x + f.w <= PAGE_HEIGHT_PT + 1e-6
    assert vm.dirty is True
    # the signal says the layout geometry changed (canvas rebuilds)
    assert vm.template.orientation == ORIENTATION_LANDSCAPE


async def test_set_orientation_same_value_is_noop(vm, qtbot):
    fid = vm.place(FieldType.LABEL, 10.0, 10.0)
    pages = []
    vm.pages_changed.connect(lambda: pages.append(1))
    await vm.save()

    vm.set_orientation("portrait")   # already portrait

    assert pages == []
    assert vm.dirty is False


async def test_switch_back_to_portrait_clamps_wide_fields(vm):
    w, h = PAGE_HEIGHT_PT, PAGE_WIDTH_PT  # landscape size
    fid = vm.place(FieldType.LABEL, w - 80.0, 10.0)  # near the right edge…
    # …of the portrait page (portrait width < w), i.e. clamped on place
    before_portrait_w = vm.template.get_field(fid).w

    vm.set_orientation(ORIENTATION_LANDSCAPE)
    f = vm.template.get_field(fid)
    assert f.x + f.w <= PAGE_HEIGHT_PT + 1e-6        # now it fits (wider page)

    vm.set_orientation("portrait")
    f = vm.template.get_field(fid)
    assert f.x + f.w <= PAGE_WIDTH_PT + 1e-6         # clamped back
    assert f.w == before_portrait_w                  # width never scaled


# ── A-playable: cross-page drag (relocate_field / commit_drag, design D5) ──

PAGE_W = PAGE_WIDTH_PT
PAGE_H = PAGE_HEIGHT_PT
G = GUTTER_PT


async def test_relocate_field_moves_it_to_the_target_page(vm):
    fid = vm.place(FieldType.TEXT, 100.0, 100.0)   # page 0, 120x18
    vm.add_page(after_index=0)                      # page 1 exists
    assert vm.page_of(fid) == 0

    assert vm.relocate_field(fid, 1, 40.0, 60.0) is True

    assert vm.page_of(fid) == 1
    f = vm.template.get_field(fid)
    assert (f.x, f.y) == (40.0, 60.0)
    # end of the target array = topmost on that page
    assert vm.template.pages[1].fields[-1].id == fid
    assert vm.template.pages[0].fields == []


async def test_relocate_field_clamps_into_the_target_page(vm):
    fid = vm.place(FieldType.TEXT, 10.0, 10.0)      # 120x18
    vm.add_page(after_index=0)

    # drop near the bottom-right corner of page 1: top-left is pulled back
    assert vm.relocate_field(fid, 1, PAGE_H - 5.0, PAGE_W - 5.0) is True
    f = vm.template.get_field(fid)
    assert f.x + f.w <= PAGE_W
    assert f.y + f.h <= PAGE_H
    assert vm.page_of(fid) == 1


async def test_relocate_field_bad_targets_are_refused(vm):
    fid = vm.place(FieldType.TEXT, 10.0, 10.0)
    assert vm.relocate_field(fid, 5, 10.0, 10.0) is False    # no such page
    assert vm.relocate_field("nope", 0, 10.0, 10.0) is False # no such field
    assert vm.page_of(fid) == 0
    assert (vm.template.get_field(fid).x, vm.template.get_field(fid).y) == (10.0, 10.0)


def _drag_setup(vm):
    """A 120x18 text field on page 0, a second page, grab at (5, 9) inside it."""
    fid = vm.place(FieldType.TEXT, 100.0, 100.0)
    vm.add_page(after_index=0)
    return fid, 5.0, 9.0


async def test_commit_drag_drop_on_second_sheet_moves_the_field(vm):
    fid, gx, gy = _drag_setup(vm)
    # the cursor lands in the middle of page 1 (local 200, 50)
    drop = (200.0, PAGE_H + G + 50.0)

    result = vm.commit_drag(fid, drop[0], drop[1], gx, gy)

    assert result == 1
    assert vm.page_of(fid) == 1
    f = vm.template.get_field(fid)
    # top-left = drop-local minus the grab offset
    assert (f.x, f.y) == (200.0 - gx, 50.0 - gy)
    assert f.x + f.w <= PAGE_W and f.y + f.h <= PAGE_H        # fully on it


async def test_commit_drag_drop_in_gutter_keeps_the_original_page(vm):
    fid, gx, gy = _drag_setup(vm)
    # the cursor is in the gutter between the pages
    drop_y = PAGE_H + G / 2

    result = vm.commit_drag(fid, 200.0, drop_y, gx, gy)

    assert result == 0
    assert vm.page_of(fid) == 0
    f = vm.template.get_field(fid)
    assert f.y + f.h <= PAGE_H + 1e-6                          # clamped back
    assert f.x + f.w <= PAGE_W


async def test_commit_drag_drop_past_last_page_clamps_back(vm):
    fid, gx, gy = _drag_setup(vm)
    result = vm.commit_drag(fid, 200.0, 2 * PAGE_H + 2 * G + 5.0, gx, gy)

    assert result == 0
    f = vm.template.get_field(fid)
    assert f.y + f.h <= PAGE_H + 1e-6
    assert f.x + f.w <= PAGE_W


async def test_commit_drag_drop_on_same_page_clamps_to_edge(vm):
    fid, gx, gy = _drag_setup(vm)
    # drop far to the right: beyond the page width
    result = vm.commit_drag(fid, PAGE_W + 80.0, 150.0, gx, gy)

    assert result == 0
    f = vm.template.get_field(fid)
    assert f.x + f.w == PAGE_W                                 # clamped to the edge
    assert f.y == 150.0 - gy


async def test_drag_move_follows_cursor_within_own_page(vm):
    fid, gx, gy = _drag_setup(vm)

    vm.drag_move(fid, 150.0, 120.0, gx, gy)

    f = vm.template.get_field(fid)
    assert (f.x, f.y) == (150.0 - gx, 120.0 - gy)
    assert vm.page_of(fid) == 0


async def test_drag_move_over_other_page_holds_clamped_position(vm):
    fid, gx, gy = _drag_setup(vm)
    vm.drag_move(fid, 150.0, 120.0, gx, gy)          # park inside the page
    parked = (vm.template.get_field(fid).x, vm.template.get_field(fid).y)

    # cursor over page 1: the field holds its last in-page position
    vm.drag_move(fid, 150.0, PAGE_H + G + 120.0, gx, gy)

    assert (vm.template.get_field(fid).x, vm.template.get_field(fid).y) == parked
    assert vm.page_of(fid) == 0                        # not relocated yet


async def test_commit_drag_unknown_fields_are_noop(vm):
    assert vm.commit_drag("nope", 10.0, 10.0, 0.0, 0.0) is None
    vm.drag_move("nope", 10.0, 10.0, 0.0, 0.0)


async def test_unloaded_vm_page_mutators_are_noop(service):
    vm = CharacterSheetViewModel(service)
    assert vm.add_page() is None
    assert vm.remove_page(0) is False
    assert vm.remove_page(0, confirmed=True) is False
    assert vm.move_page(0, 1) is False
    assert vm.rename_page(0, "X") is False
    assert vm.set_orientation("landscape") is False
    assert vm.set_current_page(5) is None
    assert vm.relocate_field("x", 0, 1.0, 1.0) is False
    assert vm.commit_drag("x", 1.0, 1.0, 0.0, 0.0) is None
    vm.drag_move("x", 1.0, 1.0, 0.0, 0.0)
    fid = vm.place(FieldType.LABEL, 1.0, 1.0, page_index=1)
    assert fid == ""
    assert vm.page_count == 0
    assert vm.template is None
