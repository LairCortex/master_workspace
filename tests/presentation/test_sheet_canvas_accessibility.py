"""Accessibility contract of the sheet canvas (change
nri-0012-qml-accessibility, task 2.5, design D7).

The production SheetCanvas.qml runs on the island loader of
test_sheet_canvas_island (fixtures/services imported from there). The face is
the per-instance Loader item (active only for the annotated kinds): role by
model.type, name = the delivered content with the type as fallback, the image
description spelled out, Accessible.checked driving the checkbox state, and
one Press replaying the CURRENT mode's single-click branch — design selects
the field on a recording (mock) VM, fill re-enters the very onFillPress the
mouse drives (inline open for text, toggle WITHOUT opening for checkboxes).
The heading (label) and divider (line) stay out of the tree: their delegate
roots keep no accessible interface, which ``queryAccessibleInterface``
answers with None offscreen (design F1/F6). The reused inline editor names
itself «Редактирование поля» at its application root.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QAccessible
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from app.domain.enums.field_type import FieldType
from app.presentation.qml.sheet_font import register_sheet_font
from app.presentation.viewmodels.character_sheet_fill_viewmodel import (
    CharacterSheetFillViewModel,
)
from app.presentation.viewmodels.character_sheet_viewmodel import (
    CharacterSheetViewModel,
)
from tests.presentation.qml_helpers import find_item, walk_items
from tests.presentation.test_sheet_canvas_island import (  # noqa: F401
    SHEET_CANVAS_QML,
    _pump,
    place,
    services,
)


class MockDesignVM(CharacterSheetViewModel):
    """The real designer VM recording the QML-facing select presses — the
    «select на мок-VM» the task pins without faking the canvas's data seam."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.select_calls: list = []

    @Slot("QVariant")
    def select(self, field_id):
        self.select_calls.append(field_id)
        super().select(field_id)


class MockFillVM(CharacterSheetFillViewModel):
    """Fill-side mock: records the three QML-facing presses the canvas drives."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.select_calls: list = []
        self.open_inline_calls: list = []
        self.toggle_calls: list = []

    @Slot("QVariant")
    def select(self, field_id):
        self.select_calls.append(field_id)
        super().select(field_id)

    @Slot(str)
    def open_inline(self, field_id):
        self.open_inline_calls.append(field_id)
        super().open_inline(field_id)

    @Slot(str, result=bool)
    def toggle_checkbox(self, field_id):
        self.toggle_calls.append(field_id)
        return super().toggle_checkbox(field_id)


@pytest.fixture
async def mock_vm(services):
    sheet_svc, _ = services
    row = await sheet_svc.create("Лист")
    view_model = MockDesignVM(sheet_svc)
    await view_model.load(row.id)
    return view_model


@pytest.fixture
async def mock_fill_case(services):
    """The island suite's fill template on the recording fill VM."""
    sheet_svc, inst_svc = services
    row = await sheet_svc.create("Шаблон")
    template = await sheet_svc.load(row.id)
    text_f = template.add_field(FieldType.TEXT, (40.0, 40.0))
    text_f.content = "Иван"
    chk = template.add_field(FieldType.CHECKBOX, (40.0, 120.0))
    chk.content = "true"
    await sheet_svc.update_pages(row.id, template)
    inst = await inst_svc.create("Лист героя", row.id)
    fvm = MockFillVM(inst_svc, sheet_svc)
    await fvm.load(inst.id)
    return fvm, {"text": text_f.id, "chk": chk.id}


def load_canvas(qtbot, vm, mode: str | None = None) -> QQuickWidget:
    register_sheet_font()
    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    widget.resize(700, 700)
    vm.setParent(widget)
    widget.setInitialProperties({"vm": vm})
    widget.setSource(QUrl.fromLocalFile(str(SHEET_CANVAS_QML)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    if mode is not None:
        widget.rootObject().setProperty("mode", mode)
    widget.show()
    _pump(6)
    return widget


def delegate(widget, fid: str):
    return find_item(widget, f"sheetField-{fid}")


def face_item(widget, fid: str):
    matches = [
        i for i in walk_items(delegate(widget, fid))
        if i.objectName() == "fieldA11yFaceItem"
    ]
    assert len(matches) <= 1
    return matches[0] if matches else None


def iface_of(item):
    return QAccessible.queryAccessibleInterface(item)


def press(item) -> None:
    iface = iface_of(item)
    assert iface is not None, "face item carries no accessibility interface"
    actions = iface.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


def design_ids(vm):
    return {
        "label": place(vm, FieldType.LABEL, 40, 40),
        "text": place(vm, FieldType.TEXT, 40, 90),
        "textarea": place(vm, FieldType.TEXTAREA, 40, 140),
        "number": place(vm, FieldType.NUMBER, 40, 190),
        "checkbox": place(vm, FieldType.CHECKBOX, 40, 240),
        "dropdown": place(vm, FieldType.DROPDOWN, 40, 290),
        "image": place(vm, FieldType.IMAGE, 40, 340),
        "rect": place(vm, FieldType.RECT, 40, 390),
        "line": place(vm, FieldType.LINE, 40, 440),
    }


def test_role_by_type_and_name_from_content_with_type_fallback(qtbot, mock_vm):
    w = load_canvas(qtbot, mock_vm)
    ids = design_ids(mock_vm)
    _pump(2)
    mock_vm.set_content(ids["label"], "Метка")
    mock_vm.set_content(ids["text"], "текст")
    mock_vm.set_content(ids["textarea"], "абзац")
    mock_vm.set_content(ids["number"], "12")
    mock_vm.set_options(ids["dropdown"], ["эльф", "орк"])
    mock_vm.set_content(ids["dropdown"], "орк")
    mock_vm.toggle_checkbox(ids["checkbox"])  # default → "true"
    _pump(3)

    text_face = iface_of(face_item(w, ids["text"]))
    assert text_face.role() == QAccessible.Role.EditableText
    assert text_face.text(QAccessible.Name) == "текст"
    assert iface_of(face_item(w, ids["textarea"])).role() == QAccessible.Role.EditableText
    assert iface_of(face_item(w, ids["number"])).role() == QAccessible.Role.EditableText

    check_face = iface_of(face_item(w, ids["checkbox"]))
    assert check_face.role() == QAccessible.Role.CheckBox
    # The checkbox content IS its value — its name keeps the type (design map).
    assert check_face.text(QAccessible.Name) == "checkbox"
    assert bool(check_face.state().checked) is True

    assert iface_of(face_item(w, ids["image"])).role() == QAccessible.Role.Button
    assert iface_of(face_item(w, ids["image"])).text(
        QAccessible.Description) == "Открыть изображение"
    # The remaining clickable kinds get the plain button face.
    assert iface_of(face_item(w, ids["dropdown"])).role() == QAccessible.Role.Button
    assert iface_of(face_item(w, ids["dropdown"])).text(QAccessible.Name) == "орк"
    assert iface_of(face_item(w, ids["rect"])).role() == QAccessible.Role.Button


def test_heading_and_divider_stay_out_of_the_tree(qtbot, mock_vm):
    w = load_canvas(qtbot, mock_vm)
    ids = design_ids(mock_vm)
    _pump(2)

    for kind in ("label", "line"):
        # An inactive Loader: no face item was ever created for the kind.
        assert face_item(w, ids[kind]) is None
        # And the bare delegate keeps NO interface at all (F1: no attached →
        # absent; no NoRole stub, no ignored node).
        assert iface_of(delegate(w, ids[kind])) is None

    # The clickable delegates' roots are equally bare — one face per field,
    # the paint layers underneath are unannotated.
    assert iface_of(delegate(w, ids["text"])) is None


def test_design_press_selects_the_field_on_the_mock_vm(qtbot, mock_vm):
    w = load_canvas(qtbot, mock_vm)
    ids = design_ids(mock_vm)
    _pump(2)
    mock_vm.select_calls.clear()

    press(face_item(w, ids["text"]))

    # Design mode's accessibility Press == the design branch's select, once,
    # with no inline, no tools, no extra channels.
    assert mock_vm.select_calls == [ids["text"]]
    assert w.rootObject().property("inlineId") == ""


def test_fill_press_on_text_opens_the_inline_editor(qtbot, mock_fill_case):
    fvm, ids = mock_fill_case
    w = load_canvas(qtbot, fvm, mode="fill")
    _pump(2)

    press(face_item(w, ids["text"]))

    # The existing fill branch verbatim (onFillPress): select + open_inline.
    assert fvm.select_calls == [ids["text"]]
    assert fvm.open_inline_calls == [ids["text"]]
    assert w.rootObject().property("inlineId") == ids["text"]

    # The reused штатный TextField names itself at its application root; the
    # value slot stays the editor's own text (design D6/F3).
    editor = find_item(w, "sheetInlineEditor")
    editor_iface = iface_of(editor)
    assert editor_iface is not None
    assert editor_iface.text(QAccessible.Name) == "Редактирование поля"


def test_fill_press_on_checkbox_toggles_without_opening(qtbot, mock_fill_case):
    fvm, ids = mock_fill_case
    w = load_canvas(qtbot, fvm, mode="fill")
    _pump(2)

    check_face = iface_of(face_item(w, ids["chk"]))
    assert bool(check_face.state().checked) is True  # template default

    press(face_item(w, ids["chk"]))

    # Fill checkbox: exactly the toggle — select + toggle_checkbox — and zero
    # inline openings; the checkbox stays a checkbox, never an editor.
    assert fvm.select_calls == [ids["chk"]]
    assert fvm.toggle_calls == [ids["chk"]]
    assert fvm.open_inline_calls == []
    assert w.rootObject().property("inlineId") == ""
    _pump(2)
    # Accessible.checked follows the model's content after the toggle.
    assert bool(iface_of(face_item(w, ids["chk"])).state().checked) is False
