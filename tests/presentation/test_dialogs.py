"""Tests for dialog Views — TDD: tests first with pytest-qt."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from PySide6.QtCore import QDate

from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog


# ── EventDialog ──────────────────────────────────────────────────────────

class TestEventDialog:
    def test_event_dialog_creates(self, qtbot):
        vm = MagicMock()
        vm.is_valid = False
        d = EventDialog(vm)
        qtbot.addWidget(d)
        assert d.windowTitle() != ""

    def test_event_dialog_has_required_fields(self, qtbot):
        vm = MagicMock()
        vm.is_valid = False
        d = EventDialog(vm)
        qtbot.addWidget(d)
        assert d.name_input is not None
        assert d.characteristics_input is not None
        assert d.backstory_input is not None
        assert d.start_date_input is not None
        assert d.end_date_input is not None

    def test_event_dialog_save_disabled_initially(self, qtbot):
        vm = MagicMock()
        vm.is_valid = False
        d = EventDialog(vm)
        qtbot.addWidget(d)
        assert not d.save_button.isEnabled()

    def test_event_dialog_save_enabled_when_valid(self, qtbot):
        vm = MagicMock()
        vm.is_valid = True
        d = EventDialog(vm)
        qtbot.addWidget(d)
        d.name_input.setText("Battle")
        d.characteristics_input.setPlainText("Big fight")
        d.backstory_input.setPlainText("Long ago")
        d.start_date_input.setDate(QDate(1200, 1, 1))
        d.end_date_input.setDate(QDate(1200, 12, 31))
        d._update_validity()
        assert d.save_button.isEnabled()

    def test_event_dialog_collects_data(self, qtbot):
        vm = MagicMock()
        vm.is_valid = True
        d = EventDialog(vm)
        qtbot.addWidget(d)
        d.name_input.setText("Battle")
        d.characteristics_input.setPlainText("Big fight")
        d.backstory_input.setPlainText("Long ago")
        d.start_date_input.setDate(QDate(1200, 1, 1))
        d.end_date_input.setDate(QDate(1200, 12, 31))

        data = d.get_data()
        assert data["name"] == "Battle"
        assert data["characteristics"] == "Big fight"
        assert data["backstory"] == "Long ago"
        assert data["start_date"] == date(1200, 1, 1)
        assert data["end_date"] == date(1200, 12, 31)

    def test_event_dialog_has_entity_sections(self, qtbot):
        vm = MagicMock()
        vm.is_valid = False
        d = EventDialog(vm)
        qtbot.addWidget(d)
        assert d.tabs is not None


# ── EntityCardDialog ─────────────────────────────────────────────────────

class TestEntityCardDialog:
    def test_entity_card_creates(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="organization")
        qtbot.addWidget(d)
        assert d.windowTitle() != ""

    def test_entity_card_has_fields(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="character")
        qtbot.addWidget(d)
        assert d.name_input is not None
        assert d.characteristics_input is not None
        assert d.backstory_input is not None

    def test_entity_card_populate(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="organization")
        qtbot.addWidget(d)
        entity = MagicMock()
        entity.name = "Guild"
        entity.start_date = date(1000, 1, 1)
        entity.end_date = date(1500, 12, 31)
        entity.tasks = "Protect"
        desc = MagicMock()
        desc.characteristics = "Secret"
        desc.backstory = "Old"
        entity.description = desc

        d.populate(entity)
        assert d.name_input.text() == "Guild"

    def test_entity_card_get_data(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="item")
        qtbot.addWidget(d)
        d.name_input.setText("Sword")
        d.characteristics_input.setPlainText("Sharp")
        d.backstory_input.setPlainText("Forged")
        d.start_date_input.setDate(QDate(500, 1, 1))
        d.end_date_input.setDate(QDate(3000, 12, 31))
        data = d.get_data()
        assert data["name"] == "Sword"

    def test_entity_card_character_extra_fields(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="character")
        qtbot.addWidget(d)
        assert d.personality_input is not None

    def test_entity_card_location_extra_fields(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="location")
        qtbot.addWidget(d)
        assert d._has_image_field
        assert hasattr(d, "image_label")
