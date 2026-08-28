"""E2E: create → open → place label+text → save → close → reopen (task 8.1).

The real user path: menu → list → editor; tools from the palette, placement
by canvas clicks, field text through the property panel, saving through the
«Сохранить» button. The reopened template must have the same field
ids/content/geometry, and drawing the layout must NOT create a Character
entity (the sheet is a template, not a filled character).

A-playable additions (task 7.1):
- a field dragged onto the second page of the tape keeps its page across
  save / close / reopen;
- a schema_version 1 (A1) row opens without loss and the first save bumps
  the stored ``schema_version`` to 2.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from app.domain.entities.character_sheet import GUTTER_PT, PAGE_HEIGHT_PT
from app.domain.enums.field_type import FieldType
from app.presentation.views.character_sheet.editor_dialog import (
    CharacterSheetEditorDialog,
)
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog
from app.presentation.views.character_sheet.presets.catalog import (
    MORK_BORG_LICENSE_TEXT,
)

from tests.ui.conftest import query_db


# ── helpers ─────────────────────────────────────────────────────────────────

def _click_canvas(editor: CharacterSheetEditorDialog, scene_x: float, scene_y: float) -> None:
    """Click the canvas at the given page (scene) point."""
    view = editor.canvas
    pos = view.mapFromScene(QPointF(scene_x, scene_y))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def _editor_name(application) -> str:
    editor = application._sheet_editor
    if editor is None or editor.view_model.template is None:
        return ""
    return editor.view_model.template.name


def _layout(editor: CharacterSheetEditorDialog) -> list[tuple]:
    """Field tuples (id, type, x, y, w, h, content) of the in-memory template."""
    return [
        (f.id, f.type, f.x, f.y, f.w, f.h, f.content)
        for f in editor.view_model.template.page.fields
    ]


async def wait_editor(app, wait_for, name: str) -> CharacterSheetEditorDialog:
    application, _window = app
    await wait_for(lambda: _editor_name(application) == name)
    return application._sheet_editor


# ── the scenario ────────────────────────────────────────────────────────────

async def test_layout_survives_save_and_reopen(app, dialog_input, wait_for, qtbot):
    application, window = app
    chars_before = query_db(
        application._db_path, "SELECT COUNT(*) FROM characters"
    )[0][0]

    # Create: menu → list → «Создать»
    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg: CharacterSheetListDialog = application._sheet_list_dialog
    dialog_input["answer"] = ("Иван", True)
    list_dlg.create_button.click()
    editor = await wait_editor(app, wait_for, "Иван")
    qtbot.wait(50)  # canvas fitted after show/resize

    # Place a label and a text field through palette tools + canvas clicks.
    editor.palette.label_button.click()
    _click_canvas(editor, 100.0, 100.0)
    await wait_for(lambda: editor.canvas.item_count() == 1)
    label_id = editor.view_model.selection
    editor.properties_panel.content_edit.setPlainText("Имя")
    await wait_for(lambda: editor.view_model.template.get_field(label_id).content == "Имя")

    editor.palette.text_button.click()
    _click_canvas(editor, 100.0, 200.0)
    await wait_for(lambda: editor.canvas.item_count() == 2)
    text_id = editor.view_model.selection
    editor.properties_panel.content_edit.setPlainText("Иван Петров")
    await wait_for(
        lambda: editor.view_model.template.get_field(text_id).content == "Иван Петров"
    )

    before = _layout(editor)  # dirty in memory, not yet in the DB
    assert len(before) == 2
    assert editor.view_model.dirty

    # Save through the window's button.
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)
    saved = _layout(editor)
    assert saved == before

    # Close (not dirty) and reopen from the list.
    editor.close()
    await wait_for(lambda: application._sheet_editor is None)

    row = next(
        i for i in range(list_dlg.list_widget.count())
        if list_dlg.list_widget.item(i).text() == "Иван"
    )
    list_dlg.list_widget.setCurrentRow(row)
    list_dlg.open_button.click()
    editor2 = await wait_editor(app, wait_for, "Иван")

    reopened = _layout(editor2)
    assert reopened == before  # same ids, content and geometry

    # The layout is a template: no Character entity was created.
    chars_after = query_db(
        application._db_path, "SELECT COUNT(*) FROM characters"
    )[0][0]
    assert chars_after == chars_before


def _drag_canvas(editor: CharacterSheetEditorDialog,
                 from_scene: tuple[float, float],
                 to_scene: tuple[float, float], qtbot) -> None:
    """Press at the first scene point, move (through the middle), release at
    the second — a cross-page drag of the field under the cursor."""
    view = editor.canvas
    p0 = view.mapFromScene(QPointF(*from_scene))
    pm = view.mapFromScene(
        QPointF((from_scene[0] + to_scene[0]) / 2, (from_scene[1] + to_scene[1]) / 2)
    )
    p1 = view.mapFromScene(QPointF(*to_scene))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=p0)
    qtbot.wait(1)
    QTest.mouseMove(view.viewport(), pos=pm)
    qtbot.wait(1)
    QTest.mouseMove(view.viewport(), pos=p1)
    qtbot.wait(1)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=p1)
    qtbot.wait(1)


# ── 7.1a: a field dragged onto the second page survives save and reopen ─────

async def test_field_on_second_page_survives_save_and_reopen(app, dialog_input, wait_for, qtbot):
    application, window = app

    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg: CharacterSheetListDialog = application._sheet_list_dialog
    dialog_input["answer"] = ("Лента", True)
    list_dlg.create_button.click()
    editor = await wait_editor(app, wait_for, "Лента")
    qtbot.wait(50)  # canvas fitted after show/resize

    # A text field on page 1, and a second page from the rail.
    editor.palette.text_button.click()
    _click_canvas(editor, 100.0, 100.0)
    await wait_for(lambda: editor.canvas.item_count() == 1)
    field_id = editor.view_model.selection

    editor.rail.add_button.click()
    await wait_for(lambda: editor.view_model.page_count == 2)
    # the new page is current and empty; the canvas shows the tape
    assert editor.view_model.current_page_index == 1
    assert editor.view_model.template.pages[1].fields == []

    # Drag the field across the gutter onto the second sheet (it becomes a
    # field of that page: coordinates from the drop point, then clamped).
    drop_y = PAGE_HEIGHT_PT + GUTTER_PT + 150.0
    _drag_canvas(editor, (110.0, 109.0), (150.0, drop_y), qtbot)
    await wait_for(lambda: editor.view_model.page_of(field_id) == 1)

    # Save, close, reopen: the field stays on page 2 with the same id.
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)
    editor.close()
    await wait_for(lambda: application._sheet_editor is None)

    row = next(i for i in range(list_dlg.list_widget.count())
               if list_dlg.list_widget.item(i).text() == "Лента")
    list_dlg.list_widget.setCurrentRow(row)
    list_dlg.open_button.click()
    editor2 = await wait_editor(app, wait_for, "Лента")

    assert editor2.view_model.page_count == 2
    page1 = editor2.view_model.template.pages[0]
    page2 = editor2.view_model.template.pages[1]
    assert page1.fields == []
    assert [f.id for f in page2.fields] == [field_id]
    assert page2.fields[0].x > 0 and page2.fields[0].y > 0
    # the field is clamped onto its (new) page, not in the gutter
    page_w, page_h = editor2.view_model.template.page_size
    f = page2.fields[0]
    assert 0 <= f.x and f.x + f.w <= page_w
    assert 0 <= f.y and f.y + f.h <= page_h


# ── 7.1b: a v1 row opens without loss; the first save writes version 2 ──────

async def test_v1_sheet_open_and_save_writes_version_2(app, dialog_input, wait_for, qtbot):
    application, _window = app

    # A stored A1 row: schema_version 1, one page object without a name.
    pages_v1 = json.dumps(
        [{
            "fields": [{
                "id": "v1field", "type": "label",
                "x": 10.0, "y": 10.0, "w": 72.0, "h": 18.0,
                "font_size": 10.0, "content": "Привет",
            }]
        }],
        ensure_ascii=False,
    )
    now = datetime.utcnow().isoformat(sep=" ")
    conn = sqlite3.connect(str(application._db_path))
    try:
        conn.execute(
            "INSERT INTO character_sheets "
            "(name, schema_version, orientation, pages, created_at, updated_at) "
            "VALUES ('Старый', 1, 'portrait', ?, ?, ?)",
            (pages_v1, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    application._window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg: CharacterSheetListDialog = application._sheet_list_dialog
    await wait_for(lambda: list_dlg.list_widget.count() == 1)
    assert list_dlg.list_widget.item(0).text() == "Старый"
    list_dlg.list_widget.setCurrentRow(0)

    list_dlg.open_button.click()
    editor = await wait_editor(app, wait_for, "Старый")

    # v1 loads without loss: the field is there, one page «Страница 1».
    template = editor.view_model.template
    assert len(template.pages) == 1
    assert template.pages[0].name == "Страница 1"
    fields = template.pages[0].fields
    assert len(fields) == 1
    assert (fields[0].id, fields[0].content) == ("v1field", "Привет")
    assert (fields[0].x, fields[0].w) == (10.0, 72.0)

    # The first save bumps the stored row to schema_version 2. (The sheet was
    # not edited, so wait on the written row itself, not on the dirty flag.)
    editor.save_button.click()
    await wait_for(
        lambda: query_db(
            application._db_path,
            "SELECT schema_version FROM character_sheets WHERE name = 'Старый'",
        )[0][0] == 2
    )
    assert editor.view_model.dirty is False

    version, pages = query_db(
        application._db_path,
        "SELECT schema_version, pages FROM character_sheets WHERE name = 'Старый'",
    )[0]
    assert version == 2
    data = json.loads(pages)
    assert data[0].get("name") == "Страница 1"
    assert data[0]["fields"][0]["id"] == "v1field"


# ── A-editor: rubber-band two fields → duplicate → undo → save ─────────────

async def test_marquee_duplicate_undo_save(app, dialog_input, wait_for, qtbot):
    application, window = app

    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg: CharacterSheetListDialog = application._sheet_list_dialog
    dialog_input["answer"] = ("Макет", True)
    list_dlg.create_button.click()
    editor = await wait_editor(app, wait_for, "Макет")
    qtbot.wait(50)

    editor.palette.label_button.click()
    _click_canvas(editor, 100.0, 100.0)
    await wait_for(lambda: editor.canvas.item_count() == 1)
    editor.palette.text_button.click()
    _click_canvas(editor, 200.0, 200.0)
    await wait_for(lambda: editor.canvas.item_count() == 2)

    _drag_canvas(editor, (90.0, 90.0), (330.0, 230.0), qtbot)
    await wait_for(lambda: len(editor.view_model.selected_ids) == 2)

    ids_before = [f.id for f in editor.view_model.template.page.fields]
    editor.duplicate_action.trigger()
    await wait_for(lambda: editor.canvas.item_count() == 4)
    assert len(editor.view_model.template.page.fields) == 4

    editor.undo_action.trigger()
    await wait_for(lambda: editor.canvas.item_count() == 2)
    assert [f.id for f in editor.view_model.template.page.fields] == ids_before

    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)
    row = query_db(
        application._db_path,
        "SELECT pages FROM character_sheets WHERE name = 'Макет'",
    )[0][0]
    saved = json.loads(row)
    assert [f["id"] for f in saved[0]["fields"]] == ids_before


async def test_instance_fill_survives_save_and_reopen(
    app, dialog_input, dialog_item, wait_for, qtbot,
):
    application, window = app
    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg: CharacterSheetListDialog = application._sheet_list_dialog
    dialog_input["answer"] = ("Макет", True)
    list_dlg.create_button.click()
    editor = await wait_editor(app, wait_for, "Макет")
    qtbot.wait(50)

    editor.palette.text_button.click()
    _click_canvas(editor, 100.0, 100.0)
    await wait_for(lambda: editor.canvas.item_count() == 1)
    text_id = editor.view_model.selection
    editor.properties_panel.content_edit.setPlainText("Иван")
    await wait_for(
        lambda: editor.view_model.template.get_field(text_id).content == "Иван"
    )
    editor.save_button.click()
    await wait_for(lambda: not editor.view_model.dirty)
    editor.close()
    await wait_for(lambda: application._sheet_editor is None)

    list_dlg.tabs.setCurrentIndex(1)
    dialog_item["answer"] = ("Макет", True)
    dialog_input["answer"] = ("Лист", True)
    list_dlg.create_button.click()
    await wait_for(
        lambda: application._sheet_fill is not None
        and application._sheet_fill.view_model.template is not None
        and application._sheet_fill.view_model.name == "Лист"
    )
    fill = application._sheet_fill
    field = fill.view_model.template.get_field(text_id)
    assert field is not None, text_id
    assert fill.view_model.set_text(text_id, "Пётр") is True
    assert fill.view_model.dirty
    fill.save_button.click()
    await wait_for(lambda: not fill.view_model.dirty)
    fill.close()
    await wait_for(lambda: application._sheet_fill is None)

    list_dlg.tabs.setCurrentIndex(1)
    list_dlg.instance_list.setCurrentRow(0)
    list_dlg.open_button.click()
    await wait_for(
        lambda: application._sheet_fill is not None
        and application._sheet_fill.view_model.template is not None
    )
    fill2 = application._sheet_fill
    assert fill2.view_model.display_value(text_id) == "Пётр"
    rows = query_db(
        application._db_path,
        'SELECT name, "values" FROM character_sheet_instances',
    )
    assert rows[0][0] == "Лист"
    assert json.loads(rows[0][1])[text_id] == "Пётр"

# ── C: preset → snapshot → clean Design → close → name in the list ─────────────


async def test_create_from_preset_opens_clean_design(app, wait_for, qtbot):
    application, window = app

    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg: CharacterSheetListDialog = application._sheet_list_dialog

    # «Создать из пресета…» — only on the «Шаблоны» tab (the default one).
    assert list_dlg.preset_button.isVisibleTo(list_dlg)
    list_dlg.preset_button.click()
    await wait_for(
        lambda: list_dlg.preset_dialog is not None
        and list_dlg.preset_dialog.isVisible()
    )
    preset = list_dlg.preset_dialog

    # Two bundled presets; pick Mörk Borg: full 3PP license + name from title.
    assert preset.preset_list.count() == 2
    preset.preset_list.setCurrentRow(1)
    await wait_for(lambda: preset.name_edit.text() == "Mörk Borg")
    assert "Third Party License" in preset.license_view.toPlainText()
    assert "©2019" in preset.license_view.toPlainText()

    preset.ok_button.click()

    # Design of the new template opens clean (dirty cleared on load).
    editor = await wait_editor(app, wait_for, "Mörk Borg")
    qtbot.wait(50)  # canvas fitted after show/resize
    assert editor.view_model.dirty is False
    template = editor.view_model.template
    assert len(template.pages) == 1

    # The preset's layout is on the canvas (a field is in its place).
    contents = {f.content for f in template.page.fields}
    assert "Сила" in contents
    assert MORK_BORG_LICENSE_TEXT in contents  # the license is on the sheet

    # The snapshot is a regular template row in the current game's DB.
    version, pages = query_db(
        application._db_path,
        "SELECT schema_version, pages FROM character_sheets WHERE name = 'Mörk Borg'",
    )[0]
    assert version == 2
    assert len(json.loads(pages)) == 1

    # Close (clean) — the list keeps the name.
    editor.close()
    await wait_for(lambda: application._sheet_editor is None)
    names = [
        list_dlg.list_widget.item(i).text()
        for i in range(list_dlg.list_widget.count())
    ]
    assert "Mörk Borg" in names


# ── C: a copied preset (snapshot) behaves like any template: instances fill ─


async def test_copied_preset_instance_fills_and_saves(
    app, dialog_input, dialog_item, wait_for, qtbot,
):
    """копия → лист: an instance of the preset snapshot fills, saves and
    reopens with the value — the copy needs nothing special (task 5.1)."""
    application, window = app
    window.char_sheets_action.trigger()
    await wait_for(lambda: application._sheet_list_dialog is not None)
    list_dlg: CharacterSheetListDialog = application._sheet_list_dialog

    list_dlg.preset_button.click()
    await wait_for(
        lambda: list_dlg.preset_dialog is not None
        and list_dlg.preset_dialog.isVisible()
    )
    preset = list_dlg.preset_dialog
    preset.preset_list.setCurrentRow(1)  # Mörk Borg
    await wait_for(lambda: preset.name_edit.text() == "Mörk Borg")
    preset.ok_button.click()

    editor = await wait_editor(app, wait_for, "Mörk Borg")
    editor.close()
    await wait_for(lambda: application._sheet_editor is None)

    list_dlg.tabs.setCurrentIndex(1)
    dialog_item["answer"] = ("Mörk Borg", True)
    dialog_input["answer"] = ("Лист", True)
    list_dlg.create_button.click()
    await wait_for(
        lambda: application._sheet_fill is not None
        and application._sheet_fill.view_model.template is not None
        and application._sheet_fill.view_model.name == "Лист"
    )
    fill = application._sheet_fill

    # The snapshot's stable field ids carry over: the «Имя» field (the first
    # text field of the layout) is editable in the fill.
    name_field = next(
        f for f in fill.view_model.template.page.fields
        if f.type == FieldType.TEXT
    )
    assert fill.view_model.set_text(name_field.id, "Гаррик") is True
    assert fill.view_model.dirty
    fill.save_button.click()
    await wait_for(lambda: not fill.view_model.dirty)
    fill.close()
    await wait_for(lambda: application._sheet_fill is None)

    list_dlg.tabs.setCurrentIndex(1)
    list_dlg.instance_list.setCurrentRow(0)
    list_dlg.open_button.click()
    await wait_for(
        lambda: application._sheet_fill is not None
        and application._sheet_fill.view_model.template is not None
    )
    assert application._sheet_fill.view_model.display_value(name_field.id) == "Гаррик"
    rows = query_db(
        application._db_path,
        'SELECT name, "values" FROM character_sheet_instances',
    )
    assert rows[0][0] == "Лист"
    assert json.loads(rows[0][1])[name_field.id] == "Гаррик"
