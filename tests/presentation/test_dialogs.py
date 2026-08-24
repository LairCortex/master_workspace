"""Tests for dialog Views — TDD: tests first with pytest-qt."""
from datetime import date
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate, QEvent

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

    def test_event_dialog_tabs_are_related_sections_without_inline_form(self, qtbot):
        from app.presentation.views.related_section import RelatedSection

        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        for tab in (d.org_tab, d.char_tab, d.item_tab, d.loc_tab):
            assert isinstance(tab, RelatedSection)
            # no inline creation form inside the tab
            assert not hasattr(tab, "name_input")
            assert not hasattr(tab, "add_button")

    @pytest.mark.parametrize(
        ("tab_attr", "attr", "entity_type"),
        [
            ("org_tab", "organizations", "organization"),
            ("char_tab", "characters", "character"),
            ("item_tab", "items", "item"),
            ("loc_tab", "locations", "location"),
        ],
    )
    def test_event_dialog_create_button_emits_request(self, qtbot, tab_attr, attr, entity_type):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        section = getattr(d, tab_attr)
        received: list[tuple[str, str]] = []
        d.create_related_requested.connect(lambda a, t: received.append((a, t)))
        section.create_button.click()
        assert received == [(attr, entity_type)]

    def test_event_dialog_set_available_entities(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        ent = MagicMock()
        ent.id = 1
        ent.name = "Guild"
        d.set_available_entities("organizations", [ent])
        assert d.org_tab.get_current_ids() == []
        assert len(d.org_tab._available) == 1
        d.set_available_entities("no-such-attr", [ent])  # guard: unknown attr is ignored
        assert len(d.org_tab._available) == 1

    def test_event_dialog_add_related_entity_in_get_data(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        char = MagicMock()
        char.id = 7
        char.name = "Hero"
        d.add_related_entity("characters", char)
        data = d.get_data()
        assert data["characters"] == [{"_existing_id": 7}]
        assert data["organizations"] == []
        assert data["items"] == []
        assert data["locations"] == []

    def test_event_dialog_ai_buttons_sit_right_of_field_in_row(self, qtbot):
        """Each button is the last widget of its field's row layout (right side)."""
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        for field_name, widget in [
            ("name", d.name_input),
            ("characteristics", d.characteristics_input),
            ("backstory", d.backstory_input),
        ]:
            row_layout = d._ai_row_layouts[field_name]
            widgets = [row_layout.itemAt(i).widget() for i in range(row_layout.count())]
            assert row_layout.itemAt(0).widget() is widget
            btn = next(b for b in d.get_ai_buttons() if b.field_name == field_name)
            assert widgets[-1] is btn


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

    def test_entity_card_ai_buttons_sit_right_of_field_in_row(self, qtbot):
        """Each button is the last widget of its field's row layout (right side)."""
        d = EntityCardDialog(MagicMock(), entity_type="character")
        qtbot.addWidget(d)
        for field_name, widget in [
            ("name", d.name_input),
            ("characteristics", d.characteristics_input),
            ("backstory", d.backstory_input),
            ("personality", d.personality_input),
            ("tasks", d.tasks_input),
        ]:
            row_layout = d._ai_row_layouts[field_name]
            widgets = [row_layout.itemAt(i).widget() for i in range(row_layout.count())]
            assert widget in widgets
            btn = next(b for b in d.get_ai_buttons() if b.field_name == field_name)
            assert widgets[-1] is btn
            # The field is stretched; the button takes the fixed right slot.
            assert row_layout.itemAt(0).widget() is widget


# ── Entity button & close guard (add-generate-entity) ─────────────────────

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from app.presentation.views.ai_assist_button import EntityGenerateButton

_ESC = lambda: QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)


def _make_dialog(qtbot, kind: str = "event"):
    if kind == "event":
        d = EventDialog(MagicMock())
    else:
        d = EntityCardDialog(MagicMock(), entity_type="character")
    qtbot.addWidget(d)
    return d


class TestDialogEntityButton:
    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_entity_button_present(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        btn = d.get_entity_button()
        assert isinstance(btn, EntityGenerateButton)
        # stretch + button: the rightmost widget of its row
        row = d._entity_row
        widgets = [
            row.itemAt(i).widget() for i in range(row.count())
            if row.itemAt(i).widget() is not None
        ]
        assert widgets[-1] is btn

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_entity_button_row_sits_at_top_of_form(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        if kind == "event":
            first = d.layout().itemAt(0)
        else:
            first = d._form_layout.itemAt(0)
        assert first is not None
        assert first.layout() is d._entity_row

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_entity_button_not_ready_by_default(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        btn = d.get_entity_button()
        assert "128,128,128" in btn.styleSheet()
        assert btn.isEnabled()  # clickable — the click shows the hint
        assert not btn.is_cancelling

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_entity_button_states_follow_generation(self, qtbot, kind):
        """Inactive while any field generates (single or batch), active after."""
        d = _make_dialog(qtbot, kind)
        btn = d.get_entity_button()
        btn.update_llm_state("ready", True)
        assert btn.isEnabled() and not btn.is_cancelling

        btn.set_single_in_flight(True)
        assert not btn.isEnabled()

        btn.set_single_in_flight(False)
        assert btn.isEnabled()

        btn.set_wave_running(True)
        assert btn.is_cancelling and btn.isEnabled()

        btn.set_wave_running(False)
        assert not btn.is_cancelling and btn.isEnabled()


class TestDialogSaveLock:
    def test_event_dialog_save_locked_overrides_validity(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        d.name_input.setText("Battle")
        d.characteristics_input.setPlainText("Big fight")
        d._update_validity()
        assert d.save_button.isEnabled()

        d.set_save_locked(True)
        assert not d.save_button.isEnabled()

        d.set_save_locked(False)
        assert d.save_button.isEnabled()

    def test_entity_card_save_locked(self, qtbot):
        d = EntityCardDialog(MagicMock(), entity_type="character")
        qtbot.addWidget(d)
        assert d.save_button.isEnabled()
        d.set_save_locked(True)
        assert not d.save_button.isEnabled()
        d.set_save_locked(False)
        assert d.save_button.isEnabled()


class TestDialogCloseGuard:
    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_esc_during_generation_does_not_close(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        d.show()
        guard: list = []
        d.set_close_guard(lambda: guard.append(1))
        d.get_ai_buttons()[0].set_generating(True)

        d.keyPressEvent(_ESC())

        assert d.isVisible()
        assert guard == []  # ESC is swallowed, not routed through the guard

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_esc_without_generation_closes(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        d.show()
        d.keyPressEvent(_ESC())
        assert not d.isVisible()
        assert d.result() == QDialog.DialogCode.Rejected

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_synthetic_close_during_generation_goes_to_guard(self, qtbot, kind):
        """X / any close event during generation: silently swallowed into the
        guard (no close, no default handling)."""
        d = _make_dialog(qtbot, kind)
        d.show()
        guard: list = []
        d.set_close_guard(lambda: guard.append(1))
        d.get_ai_buttons()[0].set_generating(True)

        event = QCloseEvent()
        d.closeEvent(event)

        # the guard handled it: the dialog stays open
        assert guard == [1]
        assert d.isVisible()

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_close_without_generation_passes_freely(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        d.show()
        guard: list = []
        d.set_close_guard(lambda: guard.append(1))

        d.close()

        assert guard == []
        assert not d.isVisible()

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_cancel_button_during_generation_goes_to_guard(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        d.show()
        guard: list = []
        d.set_close_guard(lambda: guard.append(1))
        d.get_ai_buttons()[0].set_generating(True)

        d.cancel_button.click()

        assert guard == [1]
        assert d.isVisible()

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_cancel_button_without_generation_closes(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        d.show()
        d.cancel_button.click()
        assert not d.isVisible()
