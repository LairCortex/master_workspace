"""Tests for Views — TDD: tests first with pytest-qt."""
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from app.presentation.views.main_window import MainWindow
from app.presentation.views.timeline_widget import TimelineWidget
from app.presentation.views.detail_panel import DetailPanel
from app.presentation.views.search_bar import SearchBar
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ── MainWindow ────────────────────────────────────────────────────────────

class TestMainWindow:
    def test_main_window_creates(self, qtbot):
        vm_timeline = MagicMock()
        vm_detail = MagicMock()
        vm_search = MagicMock()
        w = MainWindow(
            timeline_vm=vm_timeline,
            detail_vm=vm_detail,
            search_vm=vm_search,
        )
        qtbot.addWidget(w)
        assert w.windowTitle() != ""

    def test_main_window_has_search_bar(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
        )
        qtbot.addWidget(w)
        assert w.search_bar is not None

    def test_main_window_has_timeline(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
        )
        qtbot.addWidget(w)
        assert w.timeline_widget is not None

    def test_main_window_has_detail_panel(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
        )
        qtbot.addWidget(w)
        assert w.detail_panel is not None

    def test_main_window_game_name_in_title(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
            game_name="Моя кампания",
        )
        qtbot.addWidget(w)
        assert "Моя кампания" in w.windowTitle()

    def test_main_window_default_title_without_game(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
        )
        qtbot.addWidget(w)
        assert w.windowTitle() == "НРИ Сценарий Менеджер"

    def test_set_game_name(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
        )
        qtbot.addWidget(w)
        w.set_game_name("Dark Forest")
        assert "Dark Forest" in w.windowTitle()

    def test_switch_game_requested_signal(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
        )
        qtbot.addWidget(w)
        with qtbot.waitSignal(w.switch_game_requested, timeout=1000):
            w.switch_game_action.trigger()

    def test_has_menu_bar(self, qtbot):
        w = MainWindow(
            timeline_vm=MagicMock(),
            detail_vm=MagicMock(),
            search_vm=MagicMock(),
        )
        qtbot.addWidget(w)
        assert w.menuBar() is not None


# ── GameLauncherDialog ─────────────────────────────────────────────────────

class TestGameLauncherDialog:
    @pytest.fixture(autouse=True)
    def _games_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.db.game_manager._resolve_games_dir",
            lambda: tmp_path / "games",
        )
        self._tmp = tmp_path / "games"

    def test_creates(self, qtbot):
        w = GameLauncherDialog()
        qtbot.addWidget(w)
        assert w is not None
        assert "Выбор игры" in w.windowTitle()

    def test_shows_empty_list(self, qtbot):
        w = GameLauncherDialog()
        qtbot.addWidget(w)
        assert w.list_widget.count() == 0

    def test_shows_existing_games(self, qtbot):
        self._tmp.mkdir(parents=True)
        (self._tmp / "Campaign.db").touch()
        (self._tmp / "Test.db").touch()
        w = GameLauncherDialog()
        qtbot.addWidget(w)
        assert w.list_widget.count() == 2

    def test_selected_path_none_by_default(self, qtbot):
        w = GameLauncherDialog()
        qtbot.addWidget(w)
        assert w.selected_path is None

    def test_game_selected_signal_on_open(self, qtbot):
        self._tmp.mkdir(parents=True)
        (self._tmp / "Campaign.db").touch()
        w = GameLauncherDialog()
        qtbot.addWidget(w)
        w.list_widget.setCurrentRow(0)
        with qtbot.waitSignal(w.game_selected, timeout=1000):
            w._on_open()
        assert w.selected_path is not None
        assert "Campaign" in w.selected_path

    def test_has_import_button(self, qtbot):
        w = GameLauncherDialog()
        qtbot.addWidget(w)
        assert hasattr(w, "import_button")
        assert w.import_button.text() == "Импорт"


class TestMainWindowExportAction:
    def test_has_export_action(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = MainWindow(timeline_vm=vm, detail_vm=vm, search_vm=vm)
        qtbot.addWidget(w)
        assert hasattr(w, "export_action")
        assert w.export_action.text() == "Экспорт игры…"

    def test_export_requested_signal(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = MainWindow(timeline_vm=vm, detail_vm=vm, search_vm=vm)
        qtbot.addWidget(w)
        received = []
        w.export_requested.connect(lambda: received.append(True))
        w.export_action.trigger()
        assert len(received) == 1


# ── TimelineWidget ────────────────────────────────────────────────────────

class TestTimelineWidget:
    def test_timeline_creates(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        assert w is not None

    def test_timeline_update_events(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)

        event1 = MagicMock()
        event1.name = "Battle"
        event1.start_date = date(1200, 1, 1)
        event1.end_date = date(1200, 12, 31)
        w.update_events([event1])
        assert w.list_widget.count() == 1

    def test_timeline_has_add_button(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        assert w.add_button is not None
        assert hasattr(w, "add_event_requested")
        assert hasattr(w, "add_entity_requested")

    def test_timeline_has_date_filter(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        assert w.filter_start is not None
        assert w.filter_end is not None
        assert w.filter_button is not None
        assert w.clear_filter_button is not None

    def test_timeline_filter_signal(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)

        from PySide6.QtCore import QDate
        w.filter_start.setDate(QDate(1200, 1, 1))
        w.filter_end.setDate(QDate(1300, 12, 31))

        received = []
        w.filter_changed.connect(lambda s, e: received.append((s, e)))
        w.filter_button.click()

        assert len(received) == 1
        assert received[0][0] == date(1200, 1, 1)
        assert received[0][1] == date(1300, 12, 31)

    def test_timeline_clear_filter_signal(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)

        # Apply first to enable clear button
        w.filter_button.click()
        assert w.clear_filter_button.isEnabled()

        received = []
        w.filter_changed.connect(lambda s, e: received.append((s, e)))
        w.clear_filter_button.click()

        assert len(received) == 1
        assert received[0] == (None, None)
        assert not w.clear_filter_button.isEnabled()


# ── DetailPanel ──────────────────────────────────────────────────────────

class TestDetailPanel:
    def test_detail_panel_creates(self, qtbot):
        vm = MagicMock()
        w = DetailPanel(vm)
        qtbot.addWidget(w)
        assert w is not None

    def test_detail_panel_show_event(self, qtbot):
        vm = MagicMock()
        w = DetailPanel(vm)
        qtbot.addWidget(w)

        event = MagicMock()
        event.name = "Battle"
        event.start_date = date(1200, 1, 1)
        event.end_date = date(1200, 12, 31)
        org = MagicMock()
        org.name = "Org1"
        org.id = 1
        event.organizations = [org]
        event.characters = []
        event.items = []
        event.locations = []
        w.show_event(event)
        assert "Battle" in w.title_label.text()

    def test_detail_panel_clear(self, qtbot):
        vm = MagicMock()
        w = DetailPanel(vm)
        qtbot.addWidget(w)
        w.clear()
        assert w.title_label.text() == ""


# ── SearchBar ────────────────────────────────────────────────────────────

class TestSearchBar:
    def test_search_bar_creates(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        assert w is not None

    def test_search_bar_has_input(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        assert w.search_input is not None

    def test_search_bar_has_results_list(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        assert w.results_list is not None
        assert w.results_list.isHidden()

    def test_search_bar_emits_on_return(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w.search_input.setText("Battle")
        with qtbot.waitSignal(w.search_requested, timeout=1000):
            w.search_input.returnPressed.emit()

    def test_search_bar_no_emit_for_1_char(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w.search_input.setText("B")
        emitted = []
        w.search_requested.connect(lambda q: emitted.append(q))
        w._fire_search()
        assert emitted == []

    def test_search_bar_emits_for_2_chars(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w.search_input.setText("Ba")
        with qtbot.waitSignal(w.search_requested, timeout=1000):
            w._fire_search()

    def test_debounce_timer_starts_on_2_chars(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w._on_text_changed("Ba")
        assert w._debounce_timer.isActive()

    def test_debounce_timer_stops_on_1_char(self, qtbot):
        vm = MagicMock()
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w._on_text_changed("Ba")
        assert w._debounce_timer.isActive()
        w._on_text_changed("B")
        assert not w._debounce_timer.isActive()
        assert w.results_list.isHidden()

    def test_show_results_grouped(self, qtbot):
        vm = MagicMock()
        event = MagicMock()
        event.name = "Battle"
        event.id = 1
        event.start_date = date(1200, 1, 1)
        org = MagicMock()
        org.name = "Guild"
        org.id = 2
        org.start_date = date(1000, 1, 1)
        vm.results = {
            "events": [event],
            "organizations": [org],
            "characters": [],
            "items": [],
            "locations": [],
        }
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w.search_input.setText("Ba")
        w._show_results()
        assert not w.results_list.isHidden()
        # 2 headers + 2 items = 4
        assert w.results_list.count() == 4

    def test_show_results_empty(self, qtbot):
        vm = MagicMock()
        vm.results = {
            "events": [], "organizations": [], "characters": [],
            "items": [], "locations": [],
        }
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w.search_input.setText("xyz")
        w._show_results()
        assert not w.results_list.isHidden()
        assert w.results_list.count() == 1  # "Ничего не найдено"

    def test_result_selected_signal_on_click(self, qtbot):
        vm = MagicMock()
        event = MagicMock()
        event.name = "Battle"
        event.id = 42
        event.start_date = date(1200, 1, 1)
        vm.results = {
            "events": [event],
            "organizations": [], "characters": [],
            "items": [], "locations": [],
        }
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w.search_input.setText("Ba")
        w._show_results()
        # Find the clickable item (skip header at index 0)
        result_item = w.results_list.item(1)
        with qtbot.waitSignal(w.result_selected, timeout=1000) as blocker:
            w.results_list.itemClicked.emit(result_item)
        assert blocker.args == ["event", 42]
        assert w.results_list.isHidden()

    def test_header_click_does_not_emit(self, qtbot):
        vm = MagicMock()
        event = MagicMock()
        event.name = "Battle"
        event.id = 1
        event.start_date = date(1200, 1, 1)
        vm.results = {
            "events": [event],
            "organizations": [], "characters": [],
            "items": [], "locations": [],
        }
        w = SearchBar(vm)
        qtbot.addWidget(w)
        w.search_input.setText("Ba")
        w._show_results()
        header_item = w.results_list.item(0)
        emitted = []
        w.result_selected.connect(lambda t, i: emitted.append((t, i)))
        w._on_result_clicked(header_item)
        assert emitted == []


# ── Timeline double-click ─────────────────────────────────────────────────

class TestTimelineDoubleClick:
    def test_double_click_signal_exists(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        assert hasattr(w, "event_double_clicked")

    def test_double_click_emits_event_id(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        event = MagicMock()
        event.id = 42
        event.name = "Battle"
        event.start_date = date(1200, 1, 1)
        event.end_date = date(1200, 12, 31)
        w.update_events([event])
        received = []
        w.event_double_clicked.connect(lambda eid: received.append(eid))
        item = w.list_widget.item(0)
        w.list_widget.itemDoubleClicked.emit(item)
        assert received == [42]

    def test_detail_panel_no_edit_button(self, qtbot):
        vm = MagicMock()
        w = DetailPanel(vm)
        qtbot.addWidget(w)
        assert not hasattr(w, "edit_button")


# ── EventDialog edit mode ────────────────────────────────────────────────

class TestEventDialogEditMode:
    def _make_event(self, id_=10):
        event = MagicMock()
        event.id = id_
        event.name = "Battle"
        event.start_date = date(1200, 3, 15)
        event.end_date = date(1200, 9, 1)
        event.description = MagicMock(characteristics="Big fight", backstory="Ancient war")
        event.organizations = []
        event.characters = []
        event.items = []
        event.locations = []
        return event

    def test_populate_sets_fields(self, qtbot):
        vm = MagicMock()
        w = EventDialog(vm)
        qtbot.addWidget(w)
        event = self._make_event()
        w.populate(event)
        assert w.name_input.text() == "Battle"
        assert w.event_id == 10
        assert w.characteristics_input.toPlainText() == "Big fight"
        assert w.backstory_input.toPlainText() == "Ancient war"
        assert not w.tabs.isHidden()  # tabs visible in edit mode

    def test_populate_pre_fills_existing_entities(self, qtbot):
        vm = MagicMock()
        w = EventDialog(vm)
        qtbot.addWidget(w)
        org = MagicMock()
        org.id = 1
        org.name = "Guild"
        event = self._make_event()
        event.organizations = [org]
        w.populate(event)
        assert w.org_tab.list_widget.count() == 1
        assert w.org_tab.get_items()[0]["_existing_id"] == 1

    def test_get_data_edit_mode_has_event_id_and_entities(self, qtbot):
        vm = MagicMock()
        w = EventDialog(vm)
        qtbot.addWidget(w)
        event = self._make_event()
        w.populate(event)
        data = w.get_data()
        assert data["event_id"] == 10
        assert "organizations" in data

    def test_get_data_create_mode_no_event_id(self, qtbot):
        vm = MagicMock()
        w = EventDialog(vm)
        qtbot.addWidget(w)
        w.name_input.setText("Test")
        w.characteristics_input.setPlainText("x")
        w.backstory_input.setPlainText("y")
        data = w.get_data()
        assert "event_id" not in data
        assert "organizations" in data


# ── EntityCardDialog related entities ────────────────────────────────────

class TestEntityCardDialogRelated:
    def test_organization_has_all_tabs(self, qtbot):
        w = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(w)
        assert "characters" in w._related_sections
        assert "items" in w._related_sections
        assert "locations" in w._related_sections

    def test_character_has_all_tabs(self, qtbot):
        w = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(w)
        assert "items" in w._related_sections
        assert "locations" in w._related_sections
        assert "organizations" in w._related_sections

    def test_item_has_all_tabs(self, qtbot):
        w = EntityCardDialog(None, entity_type="item")
        qtbot.addWidget(w)
        assert "locations" in w._related_sections
        assert "characters" in w._related_sections
        assert "organizations" in w._related_sections

    def test_location_has_all_tabs(self, qtbot):
        w = EntityCardDialog(None, entity_type="location")
        qtbot.addWidget(w)
        assert "characters" in w._related_sections
        assert "organizations" in w._related_sections
        assert "items" in w._related_sections

    def test_set_available_and_add_entity(self, qtbot):
        w = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(w)
        char = MagicMock()
        char.id = 1
        char.name = "Hero"
        w.set_available_entities("characters", [char])
        w.add_related_entity("characters", char)
        ids = w._related_sections["characters"].get_current_ids()
        assert 1 in ids

    def test_get_data_includes_related_changes(self, qtbot):
        w = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(w)
        char = MagicMock()
        char.id = 3
        char.name = "Mage"
        w.add_related_entity("characters", char)
        w.name_input.setText("Org")
        data = w.get_data()
        assert "related_changes" in data
        assert data["related_changes"]["characters"]["current_ids"] == [3]
        assert "items" in data["related_changes"]
        assert "locations" in data["related_changes"]

    def test_create_related_requested_signal(self, qtbot):
        w = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(w)
        section = w._related_sections["characters"]
        with qtbot.waitSignal(w.create_related_requested, timeout=1000) as blocker:
            section.create_requested.emit()
        assert blocker.args == ["characters", "character"]

    def test_item_link_location(self, qtbot):
        w = EntityCardDialog(None, entity_type="item")
        qtbot.addWidget(w)
        loc = MagicMock()
        loc.id = 5
        loc.name = "Dungeon"
        w.add_related_entity("locations", loc)
        ids = w._related_sections["locations"].get_current_ids()
        assert 5 in ids

    def test_location_link_items(self, qtbot):
        w = EntityCardDialog(None, entity_type="location")
        qtbot.addWidget(w)
        item = MagicMock()
        item.id = 9
        item.name = "Sword"
        w.add_related_entity("items", item)
        ids = w._related_sections["items"].get_current_ids()
        assert 9 in ids


# ── EntityCardDialog image support ────────────────────────────────────────

class TestEntityCardDialogImage:
    def test_character_has_image_panel(self, qtbot):
        w = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(w)
        assert w._has_image_field
        assert hasattr(w, "image_label")
        assert hasattr(w, "pick_image_btn")
        assert hasattr(w, "clear_image_btn")

    def test_location_has_image_panel(self, qtbot):
        w = EntityCardDialog(None, entity_type="location")
        qtbot.addWidget(w)
        assert w._has_image_field
        assert hasattr(w, "image_label")

    def test_organization_has_image_panel(self, qtbot):
        w = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(w)
        assert w._has_image_field

    def test_item_has_no_image_panel(self, qtbot):
        w = EntityCardDialog(None, entity_type="item")
        qtbot.addWidget(w)
        assert not w._has_image_field

    def test_get_data_includes_empty_image(self, qtbot):
        w = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(w)
        w.name_input.setText("Hero")
        data = w.get_data()
        assert "image" in data
        assert data["image"] == ""

    def test_populate_with_image_b64(self, qtbot):
        from app.presentation.utils.image_utils import _image_to_base64
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt
        img = QImage(10, 10, QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.blue)
        b64 = _image_to_base64(img)

        w = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(w)
        entity = MagicMock()
        entity.name = "Hero"
        entity.start_date = date(1200, 1, 1)
        entity.end_date = date(1200, 12, 31)
        entity.personality = "Brave"
        entity.tasks = ""
        entity.image = b64
        entity.description = MagicMock(characteristics="strong", backstory="old")
        entity.items = []
        entity.locations = []
        entity.organizations = []
        w.populate(entity)
        assert w._image_b64 == b64
        assert w.clear_image_btn.isEnabled()

    def test_clear_image(self, qtbot):
        w = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(w)
        w._image_b64 = "some_data"
        w._on_clear_image()
        assert w._image_b64 == ""
        assert not w.clear_image_btn.isEnabled()


# ── Rating support ────────────────────────────────────────────────────────

class TestEntityCardDialogRating:
    def test_rating_spinbox_exists(self, qtbot):
        w = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(w)
        assert hasattr(w, "rating_input")
        assert w.rating_input.minimum() == 1
        assert w.rating_input.maximum() == 20
        assert w.rating_input.value() == 1

    def test_get_data_includes_rating(self, qtbot):
        w = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(w)
        w.name_input.setText("Hero")
        w.rating_input.setValue(15)
        data = w.get_data()
        assert data["rating"] == 15

    def test_populate_sets_rating(self, qtbot):
        w = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(w)
        entity = MagicMock()
        entity.name = "Guild"
        entity.rating = 12
        entity.start_date = date(1200, 1, 1)
        entity.end_date = date(1200, 12, 31)
        entity.tasks = ""
        entity.description = MagicMock(characteristics="", backstory="")
        entity.characters = []
        entity.items = []
        entity.locations = []
        w.populate(entity)
        assert w.rating_input.value() == 12

    def test_default_rating_is_1(self, qtbot):
        w = EntityCardDialog(None, entity_type="item")
        qtbot.addWidget(w)
        data = w.get_data()
        assert data["rating"] == 1


class TestRatingColor:
    def test_rating_1_grey(self):
        from app.presentation.views.detail_panel import rating_to_color
        c = rating_to_color(1)
        # At rating 1 red ≈ green ≈ blue (grey-ish)
        assert abs(c.red() - c.green()) <= 5
        assert abs(c.green() - c.blue()) <= 5

    def test_rating_20_red_dominant(self):
        from app.presentation.views.detail_panel import rating_to_color
        c = rating_to_color(20)
        assert c.red() > c.green()
        assert c.red() > c.blue()

    def test_rating_20_higher_alpha(self):
        from app.presentation.views.detail_panel import rating_to_color
        c1 = rating_to_color(1)
        c20 = rating_to_color(20)
        assert c20.alpha() > c1.alpha()

    def test_mid_rating(self):
        from app.presentation.views.detail_panel import rating_to_color
        c = rating_to_color(10)
        assert c.red() >= c.green()
        assert c.alpha() > 60


# ── WorldSnapshotWidget ──────────────────────────────────────────────────

def _mock_entity(id_, name, entity_type, rating=1, **extra):
    """Helper to create a mock entity with typical attributes."""
    e = MagicMock()
    e.id = id_
    e.name = name
    e.rating = rating
    e.image = None
    e.description = MagicMock(characteristics="", backstory="")
    e.start_date = date(1200, 1, 1)
    e.end_date = date(1200, 12, 31)
    for attr in ("characters", "organizations", "items", "locations", "events"):
        setattr(e, attr, extra.get(attr, []))
    return e


class TestEntityTabWidgetLinking:
    def test_has_link_button(self, qtbot):
        from app.presentation.views.event_dialog import _EntityTabWidget
        w = _EntityTabWidget("персонажа")
        qtbot.addWidget(w)
        assert hasattr(w, "link_button")
        assert "Привязать" in w.link_button.text()

    def test_set_available_entities(self, qtbot):
        from app.presentation.views.event_dialog import _EntityTabWidget
        w = _EntityTabWidget("организацию")
        qtbot.addWidget(w)
        ent = MagicMock()
        ent.id = 1
        ent.name = "Guild"
        w.set_available_entities([ent])
        assert len(w._available_entities) == 1

    def test_populate_existing(self, qtbot):
        from app.presentation.views.event_dialog import _EntityTabWidget
        w = _EntityTabWidget("предмет")
        qtbot.addWidget(w)
        ent = MagicMock()
        ent.id = 5
        ent.name = "Sword"
        w.populate_existing([ent])
        assert w.list_widget.count() == 1
        items = w.get_items()
        assert items[0]["_existing_id"] == 5
        assert items[0]["name"] == "Sword"

    def test_add_new_entity_no_existing_id(self, qtbot):
        from app.presentation.views.event_dialog import _EntityTabWidget
        w = _EntityTabWidget("предмет")
        qtbot.addWidget(w)
        w.name_input.setText("New Item")
        w.chars_input.setText("Sharp")
        w._on_add()
        items = w.get_items()
        assert len(items) == 1
        assert "_existing_id" not in items[0]
        assert items[0]["name"] == "New Item"


class TestWorldSnapshotWidget:
    def test_creates(self, qtbot):
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        assert w.tree is not None
        assert w.date_edit is not None
        assert w.show_button is not None

    def test_empty_state(self, qtbot):
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        assert w.tree.topLevelItemCount() == 1  # placeholder

    def test_populate_no_events(self, qtbot):
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([], date(1200, 1, 1))
        assert w.tree.topLevelItemCount() == 1  # "no events" placeholder

    def test_populate_with_events(self, qtbot):
        loc = _mock_entity(1, "Деревня", "location", rating=5)
        char = _mock_entity(10, "Герой", "character", rating=15, locations=[loc], items=[], organizations=[])
        loc.characters = [char]
        org = _mock_entity(20, "Гильдия", "organization", rating=10)

        event = MagicMock()
        event.id = 100
        event.name = "Битва"
        event.start_date = date(1200, 1, 1)
        event.end_date = date(1200, 12, 31)
        event.locations = [loc]
        event.characters = [char]
        event.organizations = [org]
        event.items = []

        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([event], date(1200, 1, 1))

        # Events section + 1 location = 2 top-level items
        assert w.tree.topLevelItemCount() >= 2

    def test_snapshot_requested_signal(self, qtbot):
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)

        from PySide6.QtCore import QDate
        w.date_edit.setDate(QDate(1200, 6, 15))

        received = []
        w.snapshot_requested.connect(lambda d: received.append(d))
        w.show_button.click()

        assert len(received) == 1
        assert received[0] == date(1200, 6, 15)

    def test_entity_clicked_signal(self, qtbot):
        loc = _mock_entity(1, "Замок", "location")
        event = MagicMock()
        event.id = 100
        event.name = "Осада"
        event.start_date = date(1200, 1, 1)
        event.end_date = date(1200, 12, 31)
        event.locations = [loc]
        event.characters = []
        event.organizations = []
        event.items = []

        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([event], date(1200, 1, 1))

        received = []
        w.entity_clicked.connect(lambda t, i: received.append((t, i)))

        # Find the location node inside the "Локации" section and double-click it
        def _find_node(parent_item, target_data):
            for ci in range(parent_item.childCount()):
                child = parent_item.child(ci)
                if child.data(0, Qt.ItemDataRole.UserRole) == target_data:
                    return child
            return None

        for i in range(w.tree.topLevelItemCount()):
            section = w.tree.topLevelItem(i)
            node = _find_node(section, ("location", 1))
            if node:
                w.tree.itemDoubleClicked.emit(node, 0)
                break

        assert len(received) == 1
        assert received[0] == ("location", 1)

    def test_clear_resets(self, qtbot):
        loc = _mock_entity(1, "Лес", "location")
        event = MagicMock()
        event.id = 1
        event.name = "E"
        event.start_date = date(1200, 1, 1)
        event.end_date = date(1200, 12, 31)
        event.locations = [loc]
        event.characters = []
        event.organizations = []
        event.items = []

        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([event], date(1200, 1, 1))
        assert w.tree.topLevelItemCount() >= 2

        w.clear_button.click()
        # After clear: placeholder only
        assert w.tree.topLevelItemCount() == 1

    def test_stats_label(self, qtbot):
        loc = _mock_entity(1, "Loc", "location")
        char = _mock_entity(2, "Char", "character", locations=[loc], items=[], organizations=[])
        loc.characters = [char]

        event = MagicMock()
        event.id = 1
        event.name = "E"
        event.start_date = date(1200, 1, 1)
        event.end_date = date(1200, 12, 31)
        event.locations = [loc]
        event.characters = [char]
        event.organizations = []
        event.items = []

        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([event], date(1200, 1, 1))
        assert "Персонажей: 1" in w.stats_label.text()
        assert "Локаций: 1" in w.stats_label.text()

    def test_main_window_has_snapshot(self, qtbot):
        vm = MagicMock()
        vm.events = []
        w = MainWindow(timeline_vm=vm, detail_vm=vm, search_vm=vm)
        qtbot.addWidget(w)
        assert hasattr(w, "world_snapshot")
        assert isinstance(w.world_snapshot, WorldSnapshotWidget)

    def test_world_snapshot_show_all_emits_none(self, qtbot):
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        received = []
        w.snapshot_requested.connect(lambda d: received.append(d))
        w.show_all_button.click()
        assert received == [None]
