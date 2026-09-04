"""E2E W4 §6: the «Типы событий…» entry and the event type on the scale.

6.2: the panel's «+» menu opens the types dialog; a rename and a palette
re-color write into the running game immediately (queried straight from the
game's SQLite file) and re-tint the live scale — no restart, no reopening.
The rename is also visible where the type is assigned (spec «Переименование
видно в назначении»).

6.3: assigning «Слух» in the event dialog marks the event's scale row with a
pixel exactly equal to the ``color.chart.3`` token (the seeded color of
Слух); un-assigning returns the row's dot to the muted token («Снятый тип»).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, Qt

from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.event_types_dialog import EventTypesDialog

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db
from tests.ui.test_theme_grab import token_color

SEEDED_ORDER = ["Сюжет", "Побочное", "Слух", "Встреча", "Ров будней", "Находка"]


def _visible_dialog(window, cls):
    for dialog in window.findChildren(cls):
        if dialog.isVisible():
            return dialog
    return None


def _type_dot_pixel(window, name: str):
    """The pixel at the center of the type dot of ``name``'s EVENT card on
    the QML island (probe 6.2/6.3: delegate address + island grab)."""
    event_id = helpers.find_event_id(window, name)
    idx = timeline_probe.index_for_event(window, event_id)
    delegate = timeline_probe.reveal(window, idx)
    dot = next(c for c in delegate.childItems()
               if c.objectName() == "eventTypeDot")
    image = timeline_probe.quick(window).grab().toImage()
    scale = image.width() / max(timeline_probe.quick(window).width(), 1)
    point = timeline_probe.scene_point(window, dot)
    return image.pixelColor(int(point.x() * scale), int(point.y() * scale))


def _row_token_key(window, name: str):
    event_id = helpers.find_event_id(window, name)
    idx = timeline_probe.index_for_event(window, event_id)
    delegate = timeline_probe.reveal(window, idx)
    return delegate.property("tokenKey")


async def _assign_type_via_edit_dialog(window, wait_for, event_name, type_name):
    """Double-click the event, pick ``type_name`` ("Без типа" clears), save."""
    helpers.double_click_timeline_event(window, event_name)
    await wait_for(lambda: (
        (d := _visible_dialog(window, EventDialog)) is not None
        and d.event_id is not None
        and d.type_combo.findText(type_name) != -1
    ))
    dialog = _visible_dialog(window, EventDialog)
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findText(type_name))
    dialog.save_button.click()
    await helpers.wait_until_settled()  # the update task writes through the DB


# ── 6.2 — «Типы событий…» in the «+» menu, immediate effect ─────────────────

async def test_types_menu_entry_edits_apply_to_running_game(
    app, wait_for, menu_qmenu
):
    application, window = app
    db_path = Path(application._db_path)

    # The «+» context menu carries the entry and opens the dialog.
    helpers.pick_menu_action(menu_qmenu, "Типы событий…")
    timeline_probe.click_object(
        window, "addButton", button=Qt.MouseButton.RightButton)
    await wait_for(lambda: _visible_dialog(window, EventTypesDialog) is not None)
    dialog = _visible_dialog(window, EventTypesDialog)
    await wait_for(lambda: dialog.type_names() == SEEDED_ORDER)

    # Rename «Слух» → «Примета» (write-through, no dialog-level save).
    row = dialog.type_names().index("Слух")
    dialog.type_list.setCurrentRow(row)
    dialog.name_input.setText("Примета")
    dialog.name_input.editingFinished.emit()
    await wait_for(lambda: "Примета" in dialog.type_names())
    await helpers.wait_until_settled()

    # Re-color it to palette sample №7 through the swatch row.
    dialog.swatch_buttons[6].click()
    await wait_for(lambda: "Примета" in dialog.type_names())
    await helpers.wait_until_settled()

    # Applied to the game immediately: straight from the game's DB file.
    stored = dict(query_db(
        db_path, "SELECT name, color_index FROM event_types"
    ))
    assert stored["Примета"] == 7
    assert "Слух" not in stored

    dialog.close()

    # An event picks the renamed type through the event dialog — the rename is
    # visible right where types are assigned (spec «Переименование видно в
    # назначении»), and the row re-tints without reopening anything.
    await helpers.create_event_via_ui(
        window, wait_for, "Дракон у мельницы",
        start_date=QDate(1200, 3, 10), end_date=QDate(1200, 3, 12),
    )
    await _assign_type_via_edit_dialog(window, wait_for, "Дракон у мельницы", "Примета")

    await wait_for(
        lambda: _row_token_key(window, "Дракон у мельницы") == "color.chart.7"
    )
    tagged = query_db(
        db_path,
        "SELECT e.name FROM events e JOIN event_types t ON e.event_type_id = t.id"
        " WHERE t.name = 'Примета'",
    )
    assert [r[0] for r in tagged] == ["Дракон у мельницы"]


# ── 6.3 — assigning «Слух» paints the row dot in the token hex ──────────────

async def test_assigning_type_marks_scale_row_in_token_hex(app, wait_for):
    application, window = app
    theme = window.timeline_widget._theme
    await helpers.create_event_via_ui(
        window, wait_for, "Слух у костра",
        start_date=QDate(1200, 1, 20), end_date=QDate(1200, 1, 20),
    )
    # Untyped: the dot is the muted token already (spec «Событие без типа»).
    await wait_for(lambda: (
        _type_dot_pixel(window, "Слух у костра")
        == token_color("color.fg.muted", theme.theme)
    ))

    # «Слух» ships with palette index 3 — after assigning through the dialog
    # the row dot is that token's exact color («Цвет типа равен токену»).
    await _assign_type_via_edit_dialog(window, wait_for, "Слух у костра", "Слух")
    await wait_for(lambda: (
        _type_dot_pixel(window, "Слух у костра")
        == token_color("color.chart.3", theme.theme)
    ))

    # Снятый тип: «Без типа» + save returns the dot to the muted token.
    await _assign_type_via_edit_dialog(window, wait_for, "Слух у костра", "Без типа")
    await wait_for(lambda: (
        _type_dot_pixel(window, "Слух у костра")
        == token_color("color.fg.muted", theme.theme)
    ))
