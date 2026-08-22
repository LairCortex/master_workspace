"""Tests for dialog Views — TDD: tests first with pytest-qt."""
from datetime import date
from unittest.mock import MagicMock

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
        d.music_input.setText("https://example.com/sword-theme.mp3")
        data = d.get_data()
        assert data["name"] == "Sword"
        assert data["music_url"] == "https://example.com/sword-theme.mp3"

    def test_entity_card_populate_music_link(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="character")
        qtbot.addWidget(d)
        entity = MagicMock()
        entity.name = "Bard"
        entity.start_date = date(1200, 1, 1)
        entity.end_date = date(1300, 1, 1)
        entity.tasks = None
        entity.personality = None
        entity.image = None
        entity.music_url = "https://example.com/bard-theme.ogg"
        desc = MagicMock()
        desc.characteristics = ""
        desc.backstory = ""
        entity.description = desc

        d.populate(entity)
        d.show()  # ensure visibility state is active
        assert d.music_display.isVisible()
        assert not d.music_input.isVisible()

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

    @pytest.mark.parametrize(
        ("entity_type", "extra_fields"),
        [
            ("character", ["personality", "tasks"]),
            ("organization", ["tasks"]),
            ("location", ["tasks"]),
            ("item", []),
        ],
    )
    def test_entity_card_fields_driven_by_spec(
        self, qtbot, entity_type, extra_fields
    ):
        """Widget attributes and get_data keys follow _FIELD_SPECS, no branches."""
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type=entity_type)
        qtbot.addWidget(d)
        d.name_input.setText("X")
        data = d.get_data()
        for name in ("personality", "tasks"):
            present = name in extra_fields
            assert bool(getattr(d, f"{name}_input")) == present, entity_type
            assert (name in data) == present, entity_type

    def test_entity_card_image_panel_follows_spec(self, qtbot):
        for entity_type in ("character", "organization", "location"):
            vm = MagicMock()
            d = EntityCardDialog(vm, entity_type=entity_type)
            qtbot.addWidget(d)
            assert d._has_image_field, entity_type
        d = EntityCardDialog(MagicMock(), entity_type="item")
        qtbot.addWidget(d)
        assert not d._has_image_field

    def test_entity_card_extra_fields_roundtrip(self, qtbot):
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type="character")
        qtbot.addWidget(d)
        entity = MagicMock()
        entity.name = "Bard"
        entity.start_date = date(1200, 1, 1)
        entity.end_date = date(1300, 1, 1)
        entity.personality = "Cheerful"
        entity.tasks = "Sing"
        entity.image = None
        entity.music_url = ""
        desc = MagicMock()
        desc.characteristics = ""
        desc.backstory = ""
        entity.description = desc

        d.populate(entity)
        assert d.personality_input.toPlainText() == "Cheerful"
        assert d.tasks_input.toPlainText() == "Sing"

    @pytest.mark.parametrize(
        ("entity_type", "ai_button_count"),
        [("character", 5), ("organization", 4), ("location", 4), ("item", 3)],
    )
    def test_entity_card_ai_buttons_per_type(self, qtbot, entity_type, ai_button_count):
        """One AI button per mention field: 3 common + spec extras."""
        vm = MagicMock()
        d = EntityCardDialog(vm, entity_type=entity_type)
        qtbot.addWidget(d)
        assert len(d.get_ai_buttons()) == ai_button_count
