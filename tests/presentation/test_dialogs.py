"""Tests for dialog Views — TDD: tests first with pytest-qt."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QDialog

from app.presentation.viewmodels.event_dialog_island_view_model import (
    EntityGenerateProxy,
)
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog
from tests.presentation.qml_helpers import find_item


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
        assert find_item(d.quick, "eventRelatedTabs") is not None

    def test_event_dialog_tabs_are_related_sections_without_inline_form(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        for name in (
            "organizationsRelatedSection",
            "charactersRelatedSection",
            "itemsRelatedSection",
            "locationsRelatedSection",
        ):
            assert find_item(d.quick, name) is not None

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

    def test_event_dialog_ai_buttons_are_qml_controls_with_proxies(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        for field_name in ("Name", "Characteristics", "Backstory"):
            assert find_item(d.quick, f"event{field_name}AiButton") is not None
        assert [button.field_name for button in d.get_ai_buttons()] == [
            "name", "characteristics", "backstory",
        ]


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
        """Each field has a deterministic QML AI control."""
        d = EntityCardDialog(MagicMock(), entity_type="character")
        qtbot.addWidget(d)
        for object_name in (
            "entityNameAiButton",
            "entityCharacteristicsAiButton",
            "entityBackstoryAiButton",
            "entityExtraAiButton_personality",
            "entityExtraAiButton_tasks",
        ):
            assert find_item(d.quick, object_name) is not None


# ── Entity button & close guard (add-generate-entity) ─────────────────────

def _esc() -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)


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
        if kind == "event":
            assert btn is d.vm.entityAi
            assert find_item(d.quick, "eventEntityAiButton") is not None
            return
        assert isinstance(btn, EntityGenerateProxy)
        assert find_item(d.quick, "entityGenerateButton") is not None

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_entity_button_row_sits_at_top_of_form(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        if kind == "event":
            assert find_item(d.quick, "eventEntityAiButton") is not None
            return
        assert find_item(d.quick, "entityGenerateButton") is not None

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_entity_button_not_ready_by_default(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        btn = d.get_entity_button()
        # W2b: the dialog here runs off-skin (no runtime) — state carries the
        # aiState marker, colors only exist with tokens (D3/D7).
        from app.presentation.viewmodels.event_dialog_island_view_model import (
            AI_STATE_DISABLED,
            ai_state_is,
        )

        assert ai_state_is(btn, AI_STATE_DISABLED)
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

        d.keyPressEvent(_esc())

        assert d.isVisible()
        assert guard == []  # ESC is swallowed, not routed through the guard

    @pytest.mark.parametrize("kind", ["event", "card"])
    def test_esc_without_generation_closes(self, qtbot, kind):
        d = _make_dialog(qtbot, kind)
        d.show()
        d.keyPressEvent(_esc())
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


# ── Era-aware date bridges (add-era-aware-dates, task 3.4) ──────────────────


class TestDialogDateEraBridges:
    def test_event_dialog_dates_default_to_today_our_era(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        assert d.vm._start_date == date.today()
        assert d.vm._end_date == date.today()
        data = d.get_data()
        assert data["start_bc"] is False
        assert data["end_bc"] is False

    def test_event_dialog_popup_answer_sets_date_and_era(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        d._date_target = "start"
        d._set_selected_date((date(44, 3, 5), True))
        assert d.vm._start_date == date(44, 3, 5)
        assert d.vm._start_bc is True
        assert "05 Март 44 г. до н.э." == d.vm.startDisplay
        data = d.get_data()
        assert data["start_date"] == date(44, 3, 5)
        assert data["start_bc"] is True

    def test_event_dialog_popup_answer_keeps_untouched_bound_era(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        d._date_target = "end"
        d._set_selected_date((date(100, 12, 31), False))
        assert d.vm._end_bc is False
        d._date_target = "start"
        d._set_selected_date((date(500, 1, 1), True))
        assert d.vm._end_bc is False  # the other bound is not rewritten
        assert d.vm._start_bc is True

    def test_event_dialog_opens_popup_with_current_pair(self, qtbot, monkeypatch):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        opened: list = []
        monkeypatch.setattr(
            d.date_popup, "open_at",
            lambda anchor, current: opened.append(current),
        )
        d._date_target = "start"
        d._set_selected_date((date(44, 3, 5), True))
        d._open_date_popup("start", 1, 2, 3, 4)
        d._open_date_popup("end", 1, 2, 3, 4)
        assert opened[0] == (date(44, 3, 5), True)
        assert opened[1] == (date.today(), False)

    def test_event_dialog_validity_is_chronological_across_eras(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        d.name_input.setText("Через границу")
        d.characteristics_input.setPlainText("Из древности в наше время")
        d._date_target = "start"
        d._set_selected_date((date(100, 1, 1), True))  # 100 г. до н.э.
        d._update_validity()
        assert d.vm.valid  # бессрочное — окон нет, порядок не ломается

        d.vm.set_no_end(False)
        d._date_target = "end"
        d._set_selected_date((date(100, 1, 1), False))  # 100 г. н.э. — позже
        d._update_validity()
        assert d.vm.valid

        d._set_selected_date((date(200, 1, 1), True))  # 200 г. до н.э. — раньше
        d._update_validity()
        assert not d.vm.valid  # зеркальный числовой порядок не обманывает clamp

    def test_event_dialog_populate_reads_era_flags(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        event = SimpleNamespace(
            id=7,
            name="Заговор",
            event_type=None,
            start_date=date(44, 3, 5),
            end_date=None,
            start_bc=1,
            end_bc=0,
            description=None,
        )
        d.populate(event)
        assert d.vm._start_date == date(44, 3, 5)
        assert d.vm._start_bc is True
        data = d.get_data()
        assert data["start_bc"] is True

    def test_entity_card_defaults_are_today_our_era(self, qtbot):
        d = EntityCardDialog(MagicMock(), entity_type="item")
        qtbot.addWidget(d)
        data = d.get_data()
        assert data["start_date"] == date.today()
        assert data["start_bc"] is False
        assert data["end_bc"] is False

    def test_entity_card_popup_answer_pairs_and_get_data(self, qtbot):
        d = EntityCardDialog(MagicMock(), entity_type="item")
        qtbot.addWidget(d)
        d._date_target = "start"
        d._set_selected_date((date(44, 3, 5), True))
        assert d.vm._start_date == date(44, 3, 5)
        assert d.vm._start_bc is True
        assert d.vm.startDisplay == "05 Март 44 г. до н.э."
        data = d.get_data()
        assert data["start_date"] == date(44, 3, 5)
        assert data["start_bc"] is True  # ключи уезжают в сервис **kwargs'ом

    def test_entity_card_opens_popup_with_current_pair(self, qtbot, monkeypatch):
        d = EntityCardDialog(MagicMock(), entity_type="item")
        qtbot.addWidget(d)
        opened: list = []
        monkeypatch.setattr(
            d.date_popup, "open_at",
            lambda anchor, current: opened.append(current),
        )
        d._date_target = "end"
        d._set_selected_date((date(500, 1, 1), True))
        d._open_date_popup("start", 1, 2, 3, 4)
        d._open_date_popup("end", 1, 2, 3, 4)
        assert opened[0] == (date.today(), False)
        assert opened[1] == (date(500, 1, 1), True)

    def test_entity_card_populate_reads_era_flags(self, qtbot):
        d = EntityCardDialog(MagicMock(), entity_type="item")
        qtbot.addWidget(d)
        entity = SimpleNamespace(
            id=3,
            name="Меч",
            rating=1,
            start_date=date(44, 3, 5),
            end_date=date(30, 1, 1),
            start_bc=1,
            end_bc=0,
            music_url="",
            description=None,
        )
        d.populate(entity)
        assert d.vm._start_bc is True
        assert d.vm._end_bc is False
        data = d.get_data()
        assert data["start_bc"] is True
        assert data["end_bc"] is False

    def test_world_snapshot_popup_bridge_is_a_pair_with_today_ce_default(
        self, qtbot
    ):
        from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        # Умолчание моста — «сегодня, н.э.» (design D6).
        assert w.vm._date == date.today()
        assert w.vm._date_bc is False
        # The popup answers with (date, era) through the connected bridge.
        w.date_popup.date_selected.emit((date(44, 3, 5), True))
        assert w.vm._date == date(44, 3, 5)
        assert w.vm._date_bc is True
        assert w.vm.dateDisplay == "05 Март 44 г. до н.э."
        received: list = []
        w.snapshot_requested.connect(received.append)
        w.vm.requestShow()
        assert received == [(date(44, 3, 5), True)]
