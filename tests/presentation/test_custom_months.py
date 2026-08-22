"""Tests for custom month names — date formatting, serialization, widgets."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from PySide6.QtCore import QDate

from app.presentation.utils.date_utils import (
    DEFAULT_MONTHS,
    format_game_date,
    get_custom_months,
    month_name,
    months_from_json,
    months_to_json,
    set_custom_months,
)


# ── date_utils ────────────────────────────────────────────────────────────


class TestFormatGameDate:
    def setup_method(self):
        set_custom_months(None)  # reset to defaults

    def test_default_format(self):
        d = date(2026, 3, 15)
        result = format_game_date(d)
        assert result == "15 Март 2026"

    def test_custom_months(self):
        set_custom_months({1: "Зимостой", 2: "Ветрогон", 3: "Молнеград"})
        d = date(2026, 3, 15)
        result = format_game_date(d)
        assert result == "15 Молнеград 2026"

    def test_none_date(self):
        assert format_game_date(None) == "?"
        assert format_game_date(None, "∞") == "∞"

    def test_month_name_default(self):
        set_custom_months(None)
        assert month_name(1) == "Январь"
        assert month_name(12) == "Декабрь"

    def test_month_name_custom(self):
        set_custom_months({1: "Первомес"})
        assert month_name(1) == "Первомес"
        # Other months fallback to default
        assert month_name(2) == "Февраль"

    def test_get_set_roundtrip(self):
        custom = {i: f"Month{i}" for i in range(1, 13)}
        set_custom_months(custom)
        result = get_custom_months()
        assert result == custom

    def test_set_none_resets_to_default(self):
        set_custom_months({1: "Custom"})
        set_custom_months(None)
        assert get_custom_months() == DEFAULT_MONTHS


class TestMonthSerialization:
    def test_to_json(self):
        data = {1: "Зимостой", 2: "Ветрогон"}
        raw = months_to_json(data)
        assert "Зимостой" in raw
        assert "Ветрогон" in raw

    def test_from_json_valid(self):
        raw = '{"1": "Зимостой", "2": "Ветрогон"}'
        result = months_from_json(raw)
        assert result == {1: "Зимостой", 2: "Ветрогон"}

    def test_from_json_none(self):
        assert months_from_json(None) is None
        assert months_from_json("") is None

    def test_from_json_invalid(self):
        assert months_from_json("not json") is None

    def test_roundtrip(self):
        original = {i: f"Месяц_{i}" for i in range(1, 13)}
        raw = months_to_json(original)
        result = months_from_json(raw)
        assert result == original


# ── CustomDateEdit ────────────────────────────────────────────────────────


class TestCustomDateEdit:
    def setup_method(self):
        set_custom_months(None)

    def test_creates(self, qtbot):
        from app.presentation.views.custom_date_edit import CustomDateEdit
        edit = CustomDateEdit()
        qtbot.addWidget(edit)
        assert edit is not None

    def test_text_shows_month_name(self, qtbot):
        from app.presentation.views.custom_date_edit import CustomDateEdit
        edit = CustomDateEdit()
        qtbot.addWidget(edit)
        edit.setDate(QDate(2026, 3, 15))
        text = edit.textFromDateTime(QDate(2026, 3, 15))
        assert "Март" in text
        assert "2026" in text
        assert "15" in text

    def test_text_with_custom_months(self, qtbot):
        from app.presentation.views.custom_date_edit import CustomDateEdit
        set_custom_months({3: "Молнеград"})
        edit = CustomDateEdit()
        qtbot.addWidget(edit)
        text = edit.textFromDateTime(QDate(2026, 3, 15))
        assert "Молнеград" in text

    def test_has_calendar_popup(self, qtbot):
        from app.presentation.views.custom_date_edit import CustomDateEdit
        edit = CustomDateEdit()
        qtbot.addWidget(edit)
        assert edit.calendarPopup() is True


# ── MonthSettingsDialog ───────────────────────────────────────────────────


class TestMonthSettingsDialog:
    def test_creates(self, qtbot):
        from app.presentation.views.month_settings_dialog import MonthSettingsDialog
        dlg = MonthSettingsDialog()
        qtbot.addWidget(dlg)
        assert dlg.windowTitle() == "Названия месяцев"

    def test_creates_with_custom(self, qtbot):
        from app.presentation.views.month_settings_dialog import MonthSettingsDialog
        custom = {1: "Зимостой", 2: "Февраль"}
        dlg = MonthSettingsDialog(current_months=custom)
        qtbot.addWidget(dlg)
        assert dlg._inputs[1].text() == "Зимостой"
        assert dlg._inputs[2].text() == ""  # same as default → empty

    def test_save_emits_signal(self, qtbot):
        from app.presentation.views.month_settings_dialog import MonthSettingsDialog
        dlg = MonthSettingsDialog()
        qtbot.addWidget(dlg)
        dlg._inputs[1].setText("Зимостой")
        with qtbot.waitSignal(dlg.saved, timeout=1000) as blocker:
            dlg._on_save()
        result = blocker.args[0]
        assert result[1] == "Зимостой"
        assert result[2] == "Февраль"  # default

    def test_reset_clears_inputs(self, qtbot):
        from app.presentation.views.month_settings_dialog import MonthSettingsDialog
        dlg = MonthSettingsDialog({1: "Custom"})
        qtbot.addWidget(dlg)
        assert dlg._inputs[1].text() == "Custom"
        dlg._on_reset()
        assert dlg._inputs[1].text() == ""


# ── MainWindow menu ──────────────────────────────────────────────────────


class TestMainWindowMonthSettings:
    def test_has_month_settings_action(self, qtbot):
        from app.presentation.views.main_window import MainWindow
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
            game_name="test",
        )
        qtbot.addWidget(w)
        assert hasattr(w, "month_settings_action")
        assert hasattr(w, "month_settings_requested")
