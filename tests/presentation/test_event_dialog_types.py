"""Event dialog type selector (W4 task 6.3).

The selector is a plain ``QComboBox``: «Без типа» is always the first item,
every active type carries its id (the saved value) and a dot icon of its
chart token. The selector is optional — an event without a type is a valid
state both directions (populate an untyped event, or pick «Без типа» and
save). Dot colors come from the live theme runtime and are repainted on a
live re-theme, off-skin they degrade to the numbered gray sample.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QComboBox

from app.presentation.theme.compiler import CHART_TOKEN_KEYS
from app.presentation.views.event_dialog import EventDialog

from tests.ui.test_theme_grab import make_runtime, token_color

D1 = date(1200, 3, 1)


def _event_type(id_, name, color_index):
    return SimpleNamespace(id=id_, name=name, color_index=color_index, sort_order=0)


def _event(event_type=None):
    return SimpleNamespace(
        id=5, name="Свидание", start_date=D1, end_date=None, description=None,
        event_type=event_type,
        characters=[], locations=[], organizations=[], items=[],
    )


def _make_dialog(qtbot, theme=None):
    dialog = EventDialog(None, theme=theme)  # the dialog never touches the VM
    qtbot.addWidget(dialog)
    return dialog


def _combo(qtbot):
    return _make_dialog(qtbot).type_combo


# ── selector contents and optionality ───────────────────────────────────────

class TestSelectorContents:
    def test_starts_with_only_without_type(self, qtbot):
        combo = _combo(qtbot)
        assert combo.count() == 1
        assert combo.itemText(0) == "Без типа"
        assert combo.currentData() is None

    def test_set_types_appends_active_types_with_ids_and_dots(self, qtbot):
        dialog = _make_dialog(qtbot)
        dialog.set_event_types([
            _event_type(1, "Сюжет", 1), _event_type(3, "Слух", 3),
        ])
        combo = dialog.type_combo
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "Без типа", "Сюжет", "Слух",
        ]
        assert [combo.itemData(i) for i in range(combo.count())] == [None, 1, 3]
        # Each typed item carries its palette index and a dot icon (D5).
        assert combo.itemData(2, Qt.ItemDataRole.UserRole + 1) == 3
        assert not combo.itemIcon(2).isNull()
        assert combo.itemIcon(0).isNull()  # «Без типа» owns no color dot

    def test_selector_is_optional_pick_without_type(self, qtbot):
        dialog = _make_dialog(qtbot)
        dialog.set_event_types([_event_type(3, "Слух", 3)])
        dialog.type_combo.setCurrentIndex(1)
        assert dialog.get_data()["event_type_id"] == 3
        dialog.type_combo.setCurrentIndex(0)  # снятие типа — back to «Без типа»
        assert dialog.get_data()["event_type_id"] is None

    def test_populate_selects_current_type(self, qtbot):
        dialog = _make_dialog(qtbot)
        dialog.set_event_types([
            _event_type(1, "Сюжет", 1), _event_type(3, "Слух", 3),
        ])
        dialog.populate(_event(event_type=_event_type(3, "Слух", 3)))
        assert dialog.type_combo.currentData() == 3

    def test_explicit_current_type_id_selects_without_populate(self, qtbot):
        """The selector can be told the current id directly (the dialog is
        filled before any record lands); an id missing from the set is not a
        selection — the selector drops to «Без типа»."""
        dialog = _make_dialog(qtbot)
        dialog.set_event_types(
            [_event_type(1, "Сюжет", 1), _event_type(3, "Слух", 3)],
            current_type_id=3,
        )
        assert dialog.type_combo.currentData() == 3
        assert dialog.get_data()["event_type_id"] == 3

        dialog.set_event_types([_event_type(1, "Сюжет", 1)], current_type_id=99)
        assert dialog.type_combo.currentData() is None

    def test_populate_untyped_event_selects_without_type(self, qtbot):
        dialog = _make_dialog(qtbot)
        dialog.set_event_types([_event_type(3, "Слух", 3)])
        dialog.populate(_event(event_type=None))
        assert dialog.type_combo.currentData() is None
        assert dialog.type_combo.currentIndex() == 0

    def test_populate_before_types_loads_lands_after_fill(self, qtbot):
        # Call-order independence: populate() may run before the async load.
        dialog = _make_dialog(qtbot)
        dialog.populate(_event(event_type=_event_type(7, "Примета", 2)))
        dialog.set_event_types([_event_type(7, "Примета", 2)])
        assert dialog.type_combo.currentData() == 7

    def test_get_data_without_any_fill_is_none(self, qtbot):
        dialog = _make_dialog(qtbot)
        assert dialog.get_data()["event_type_id"] is None


# ── dot icons: current tokens, live re-theme, off-skin ──────────────────────

class TestSelectorDots:
    def _center(self, combo, row):
        return combo.itemIcon(row).pixmap(QSize(18, 18)).toImage().pixelColor(9, 9)

    def test_dots_use_current_chart_tokens(self, qtbot, tmp_path):
        runtime = make_runtime(tmp_path, "dark")
        dialog = _make_dialog(qtbot, theme=runtime)
        dialog.set_event_types([_event_type(3, "Слух", 3)])
        assert self._center(dialog.type_combo, 1) == token_color("color.chart.3", "dark")

    def test_live_retheme_repaints_dots(self, qtbot, tmp_path):
        runtime = make_runtime(tmp_path, "dark")
        dialog = _make_dialog(qtbot, theme=runtime)
        dialog.set_event_types([_event_type(3, "Слух", 3)])
        assert runtime.toggle()  # dark → light, dialogs repaint in place
        assert self._center(dialog.type_combo, 1) == token_color("color.chart.3", "light")

    def test_set_types_after_theme_change_uses_new_tokens(self, qtbot, tmp_path):
        runtime = make_runtime(tmp_path, "dark")
        dialog = _make_dialog(qtbot, theme=runtime)
        assert runtime.toggle()
        dialog.set_event_types([_event_type(2, "Побочное", 2)])
        assert self._center(dialog.type_combo, 1) == token_color("color.chart.2", "light")

    def test_off_skin_dots_are_numbered_gray_samples(self, qtbot):
        from PySide6.QtGui import QColor
        from PySide6.QtCore import Qt

        dialog = _make_dialog(qtbot, theme=None)
        dialog.set_event_types([_event_type(3, "Слух", 3)])
        image = dialog.type_combo.itemIcon(1).pixmap(QSize(18, 18)).toImage()
        assert image.pixelColor(9, 2) == QColor(Qt.GlobalColor.gray)
