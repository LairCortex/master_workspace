"""QML invokables over the sheet VMs (change Q3b 1.2).

The QML canvas can only reach a QObject through its meta-object, so the
contract under test is the registration: every sync entry point the island
calls must appear as a Q_INVOKABLE with an argument shape QML can marshal
(strings/doubles/ints/QVariant — never a Python enum). The behaviour of the
underlying methods is pinned by the VM/canvas suites; nothing is renamed or
re-signalled here (task boundary: existing contracts unchanged).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QMetaMethod
from PySide6.QtWidgets import QApplication

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    CharacterSheetFillViewModel,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def slot_signatures(obj) -> set[str]:
    """All method signatures the meta-object offers to QML."""
    meta = obj.metaObject()
    out = set()
    for i in range(meta.methodCount()):
        method = meta.method(i)
        if method.methodType() != QMetaMethod.MethodType.Signal:
            out.add(str(method.methodSignature().data(), "ascii"))
    return out


# ── design VM: every canvas gesture target is invokable ──────────────────────

DESIGN_REQUIRED_SIGNATURES = [
    "place(QString,double,double)",
    "place(QString,double,double,int)",
    "move(QString,double,double)",
    "resize(QString,double,double,double,double)",
    "remove(QString)",
    "set_content(QString,QString)",
    "set_font_size(QString,double)",
    "toggle_checkbox(QString)",
    "apply_number(QString,QString)",
    "set_min_value(QString,QVariant)",
    "set_max_value(QString,QVariant)",
    "set_options(QString,QStringList)",
    "set_image_id(QString,QVariant)",
    "add_page()",
    "add_page(int)",
    "remove_page(int)",
    "remove_page(int,bool)",
    "move_page(int,int)",
    "rename_page(int,QString)",
    "set_orientation(QString)",
    "drag_move(QString,double,double,double,double)",
    "relocate_field(QString,int,double,double)",
    "apply_drag(QString,double,double,double,double)",
    "open_inline(QString)",
    "apply_inline()",
    "cancel_inline()",
    "undo()",
    "redo()",
    "begin_gesture()",
    "begin_gesture(bool)",
    "end_gesture()",
    "begin_edit()",
    "end_edit()",
    "move_selection(double,double)",
    "remove_selection()",
    "apply_drag_selection(double,double,double,double)",
    "apply_drag_selection(double,double,double,double,QVariant)",
    "drag_move_selection(double,double,double,double)",
    "drag_move_selection(double,double,double,double,QVariant)",
    "bring_to_front()",
    "send_to_back()",
    "set_snap_override(QVariant)",
    "set_snap_enabled(bool)",
    "set_tool(QString)",
    "select(QVariant)",
    "toggle_select(QString)",
    "select_ids(QStringList)",
    "select_ids(QStringList,bool)",
    # the scroll channel (Q3b 1.2): QML reports the visible page…
    "set_current_page(int)",
]

FILL_REQUIRED_SIGNATURES = [
    "select(QVariant)",
    "open_inline(QString)",
    "apply_inline()",
    "cancel_inline()",
    "set_text(QString,QString)",
    "set_number(QString,QString)",
    "set_dropdown(QString,QString)",
    "toggle_checkbox(QString)",
    "set_image(QString,QVariant)",
    "clear_image(QString)",
    "set_current_page(int)",
]


@pytest.fixture
async def design_vm(async_session):
    svc = CharacterSheetService(CharacterSheetRepository(async_session))
    row = await svc.create("Лист")
    vm = CharacterSheetViewModel(svc)
    await vm.load(row.id)
    return vm


async def test_design_invokables_registered(design_vm):
    sigs = slot_signatures(design_vm)
    missing = [s for s in DESIGN_REQUIRED_SIGNATURES if s not in sigs]
    assert not missing, f"unregistered design invokables: {missing}"


def test_fill_invokables_registered(qapp, async_session):
    sheet_svc = CharacterSheetService(CharacterSheetRepository(async_session))
    inst_svc = CharacterSheetInstanceService(
        CharacterSheetInstanceRepository(async_session), sheet_svc
    )
    vm = CharacterSheetFillViewModel(inst_svc, sheet_svc)
    sigs = slot_signatures(vm)
    missing = [s for s in FILL_REQUIRED_SIGNATURES if s not in sigs]
    assert not missing, f"unregistered fill invokables: {missing}"


def test_select_accepts_qml_null_and_empty(qapp):
    """Esc / empty-area click arrive as null (or "" from a null id binding)."""
    vm = CharacterSheetViewModel(None)
    vm._selected_ids = ["a"]
    vm.select(None)
    assert vm.selected_ids == []
    vm._selected_ids = ["a"]
    vm.select("")
    assert vm.selected_ids == []


def test_place_resolves_type_string_from_the_catalog(qapp):
    """QML passes no Python enums; the string form must place the right type,
    an unknown string must place nothing with the same '' as 'no template'."""
    vm = CharacterSheetViewModel(None)
    assert vm.place("text", 10, 10) == ""  # no template loaded — same as before
    vm._template = _empty_template()
    field_id = vm.place("checkbox", 10, 20)
    assert field_id
    assert vm.template.get_field(field_id).type.value == "checkbox"
    assert vm.place("not-a-type", 10, 20) == ""
    assert vm.template.pages[0].fields[-1].id == field_id


def _empty_template():
    from app.domain.entities.character_sheet import SheetTemplate

    return SheetTemplate(name="Тест")


def test_visible_page_round_trip(qapp):
    """The scroll channel is sync both ways: set → clamp → read-back property."""
    vm = CharacterSheetViewModel(None)
    vm._template = _empty_template()
    vm.set_current_page(99)
    assert vm.current_page_index == 0
    vm.add_page()
    vm.set_current_page(1)
    assert vm.current_page_index == 1
    vm.set_current_page(-5)
    assert vm.current_page_index == 0


def test_fill_select_and_page_channels(qapp):
    vm = CharacterSheetFillViewModel(None, None)
    seen = []
    vm.selection_changed.connect(seen.append)
    vm.select("x")
    vm.select("")      # QML may hand an empty string — same as null
    assert seen == ["x", None]
    assert vm.selection is None
    from app.domain.entities.character_sheet import SheetTemplate

    vm._template = SheetTemplate(name="Тест")
    vm.set_current_page(3)  # clamped to the only page
    assert vm.current_page_index == 0


# ── 4.3 acceptance: geometry/palette slots' guards and bound rules ────────────
# (these meanings live on the Python side; the Q3a-era widget suites had
# panel-level equivalents — they retire here as VM units, the island only
# renders what these return)


def test_pages_layout_and_page_at_follow_the_domain(qapp):
    from app.domain.entities.character_sheet import (
        GUTTER_PT,
        PAGE_HEIGHT_PT,
        PAGE_WIDTH_PT,
    )

    vm = CharacterSheetViewModel(None)
    assert vm.pages_layout() == {}        # pre-load: the blank-viewport rule
    assert vm.page_at(10.0, 10.0) == {}   # ...and the same without a template
    assert vm.page_names() == []

    vm._template = _empty_template()
    vm.add_page(after_index=0)
    layout = vm.pages_layout()
    assert layout["count"] == 2
    assert layout["width"] == PAGE_WIDTH_PT and layout["height"] == PAGE_HEIGHT_PT
    assert layout["gutter"] == GUTTER_PT
    assert layout["origins"][1] == [0.0, PAGE_HEIGHT_PT + GUTTER_PT]
    assert layout["tapeHeight"] == 2 * PAGE_HEIGHT_PT + GUTTER_PT

    hit = vm.page_at(12.0, PAGE_HEIGHT_PT + GUTTER_PT + 5.0)
    assert hit["page"] == 1 and hit["y"] == pytest.approx(5.0)
    # inside the gutter band — no page (the tape's negative space, D1)
    assert vm.page_at(12.0, PAGE_HEIGHT_PT + GUTTER_PT / 2.0) == {}
    # past the tape end
    assert vm.page_at(12.0, layout["tapeHeight"] + 1.0) == {}
    # rail names mirror the template order (no rail-side copy)
    assert vm.page_names() == [p.name for p in vm.template.pages]


def test_number_bounds_refuse_crossings_and_noops(qapp):
    vm = CharacterSheetViewModel(None)
    vm._template = _empty_template()
    number = vm.place("number", 10, 10)
    label = vm.place("label", 10, 40)

    assert vm.set_min_value("ghost", 1.0) is False      # unknown id
    assert vm.set_min_value(label, 1.0) is False        # not a number field
    assert vm.set_min_value(number, "5") is False       # strings are not nums
    assert vm.set_min_value(number, True) is False      # bools are not nums
    assert vm.set_min_value(number, 5) is True
    assert vm.set_min_value(number, 5) is False         # same value: no-op
    assert vm.set_max_value(number, 10) is True
    assert vm.set_min_value(number, 11) is False        # min may pass max
    assert vm.set_max_value(number, 4) is False         # vice versa as well
    assert vm.set_min_value(number, None) is True       # unbounded again
    assert vm.set_min_value(number, None) is False      # already unbounded
    field = vm.template.get_field(number)
    assert field.min_value is None and field.max_value == 10.0


def test_structure_rebuilds_close_the_open_inline(qapp):
    """The retired canvas's page/orientation guards were VM-side duties:
    every canvas-rebuilding moment ends the inline session and hands the
    selection back to the (possibly gone) field, never leaves an open session
    pointing at a destroyed item."""
    vm = CharacterSheetViewModel(None)
    vm._template = _empty_template()
    fid = vm.place("text", 10, 10)
    vm.open_inline(fid)
    assert vm.inline_field_id == fid

    vm.add_page()
    assert vm.inline_field_id is None
    assert list(vm.selected_ids) == [fid]

    vm.open_inline(fid)
    assert vm.set_orientation("landscape") is True
    assert vm.inline_field_id is None

    vm.open_inline(fid)
    # page 2 exists now; moving it must close the session too
    vm.move_page(1, 0)
    assert vm.inline_field_id is None
    assert list(vm.selected_ids) == [fid]

    # removing the page the inline field lives on: same close, stale-free
    vm.open_inline(fid)
    vm.remove_page(vm.page_of(fid), confirmed=True)
    assert vm.inline_field_id is None
    # the field is gone; the selection the close announced must not dangle
    assert vm.template.get_field(fid) is None


def test_open_inline_needs_exactly_one_selection(qapp):
    """The dblclick handler routes through open_inline; with a multi-selection
    the same rule the old canvas applied holds: nothing opens."""
    vm = CharacterSheetViewModel(None)
    vm._template = _empty_template()
    a = vm.place("text", 10, 10)
    b = vm.place("text", 10, 40)
    vm._selected_ids = [a, b]
    vm.open_inline(a)
    assert vm.inline_field_id is None
    vm._selected_ids = [a, "ghost-field-not-in-template"]
    vm.open_inline("ghost-field-not-in-template")
    assert vm.inline_field_id is None


def test_fill_pages_layout_and_field_props_guards(qapp):
    from app.domain.entities.character_sheet import FieldType, SheetTemplate

    vm = CharacterSheetFillViewModel(None, None)
    assert vm.pages_layout() == {}        # while nothing is loaded
    assert vm.field_props("x") == {}      # ...same for the property panel
    assert vm.page_names() == []

    template = SheetTemplate(name="Тест")
    num = template.add_field(FieldType.NUMBER, (40.0, 40.0))
    num.min_value = 0.0
    num.max_value = 10.0
    vm._template = template
    layout = vm.pages_layout()
    assert layout["count"] == 1 and layout["height"] > 0
    props = vm.field_props(num.id)
    assert props == {"min": 0.0, "max": 10.0, "options": []}
    assert vm.field_props("ghost") == {}  # selected row raced away
