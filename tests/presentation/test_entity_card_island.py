"""Semantic acceptance for the R7 entity-card island."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent, QPixmap
from PySide6.QtWidgets import QDialog

from app.domain import entity_registry
from app.domain.game_calendar import MonthDay
from app.presentation.qml.dialog_image_provider import dialog_image_provider
from app.presentation.views.entity_card_dialog import (
    ROOT_QML,
    EntityCardDialog,
    _FIELD_SPECS,
)
from tests.presentation.qml_helpers import find_item, find_items
from tests.ui.test_theme_grab import make_runtime


@pytest.mark.parametrize("entity_type", tuple(_FIELD_SPECS))
def test_one_root_builds_exact_python_configured_composition(qtbot, entity_type):
    dialog = EntityCardDialog(None, entity_type)
    qtbot.addWidget(dialog)
    assert Path(ROOT_QML).name == "EntityCardRoot.qml"
    assert dialog._root.objectName() == "entityCardRoot"
    image_column = find_item(dialog.quick, "entityImageColumn")
    assert image_column.isVisible() is any(
        spec.kind == "image" for spec in _FIELD_SPECS[entity_type]
    )
    expected_fields = {
        spec.name for spec in _FIELD_SPECS[entity_type] if spec.kind == "mention"
    }
    for name in {"personality", "tasks"}:
        items = find_items(dialog.quick, f"entityExtraField_{name}")
        assert bool(items) is (name in expected_fields)
    expected_relations = {ref.attr for ref in entity_registry.related_refs_for_key(entity_type)}
    for attr in {"characters", "items", "locations", "organizations"}:
        sections = find_items(dialog.quick, f"entityRelatedSection_{attr}")
        assert bool(sections) is (attr in expected_relations)


def test_root_has_deterministic_base_controls_and_no_type_branch():
    source = Path(ROOT_QML).read_text(encoding="utf-8")
    for name in (
        "entityNameField",
        "entityRatingSpin",
        "entityStartDateField",
        "entityEndDateField",
        "entityNoEndCheck",
        "entityCharacteristicsField",
        "entityBackstoryField",
        "entityMusicField",
        "entitySaveButton",
        "entityCancelButton",
    ):
        assert f'objectName: "{name}"' in source
    assert 'entityType === "character"' not in source
    assert 'entityType == "character"' not in source
    assert "#" not in "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("//")
    )


def test_bc_era_facets_and_the_suffix_reach_the_qml_date_fields(qtbot):
    """Task 4.1: the card exposes ready ``startBc``/``endBc`` facets and
    pre-built display strings; the island's date fields paint the «до н.э.»
    suffix straight from Python without deriving an era in QML."""
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.vm.set_dates(
        start=date(44, 3, 5), end=date(44, 1, 1), start_bc=True, end_bc=True
    )
    assert dialog.vm.startBc is True
    assert dialog.vm.endBc is True
    assert dialog.vm.startDisplay.endswith("44 г. до н.э.")
    start_field = find_item(dialog.quick, "entityStartDateField")
    end_field = find_item(dialog.quick, "entityEndDateField")
    assert start_field.property("display") == dialog.vm.startDisplay
    assert start_field.property("display").endswith("44 г. до н.э.")
    assert end_field.property("display").endswith("44 г. до н.э.")


def test_stable_proxy_order_and_roundtrip_for_character(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    edits = dialog.get_mention_edits()
    buttons = dialog.get_ai_buttons()
    assert [button.field_name for button in buttons] == [
        "name",
        "characteristics",
        "backstory",
        "personality",
        "tasks",
    ]
    assert edits == [
        dialog.characteristics_input,
        dialog.backstory_input,
        dialog.personality_input,
        dialog.tasks_input,
    ]
    entity = SimpleNamespace(
        id=4,
        name="Hero",
        rating=30,
        start_date=date(1200, 2, 3),
        end_date=None,
        description=SimpleNamespace(
            characteristics="@[Маг](character:7)",
            backstory="Past",
        ),
        personality="Calm",
        tasks="Quest",
        image_id=None,
        music_url=" https://example.test/theme ",
        items=[],
        locations=[],
        organizations=[],
    )
    dialog.populate(entity)
    result = dialog.get_data()
    assert dialog.populated_entity_id == 4
    assert result["rating"] == 20
    assert result["end_date"] is None
    assert result["characteristics"] == "@[Маг](character:7)"
    assert result["personality"] == "Calm"
    assert result["tasks"] == "Quest"
    assert result["image_id"] is None
    assert set(result["related_changes"]) == {"items", "locations", "organizations"}


def test_save_request_waits_for_explicit_result_and_retries(qtbot):
    dialog = EntityCardDialog(None, "item")
    qtbot.addWidget(dialog)
    seen = []
    dialog.saved.connect(seen.append)
    dialog.name_input.setText("")
    dialog.save_button.click()
    dialog.save_button.click()
    assert len(seen) == 1
    assert dialog.result() == 0
    assert not dialog.save_button.isEnabled()
    dialog.finish_saving(False)
    assert dialog.result() == 0
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    assert len(seen) == 2
    dialog.finish_saving(True)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_saving_and_generation_guard_all_close_paths(qtbot):
    dialog = EntityCardDialog(None, "item")
    qtbot.addWidget(dialog)
    dialog.saved.connect(lambda _data: None)
    dialog.save_button.click()
    dialog.reject()
    dialog._on_cancel_clicked()
    assert dialog.result() == 0
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    dialog.keyPressEvent(event)
    assert event.isAccepted() is False
    dialog.finish_saving(False)
    calls = []
    dialog.set_close_guard(lambda: calls.append(True))
    dialog.get_ai_buttons()[0]._generating = True
    dialog._on_cancel_clicked()
    assert calls == [True]


def test_image_provider_namespace_and_done_cleanup(qtbot):
    first = EntityCardDialog(None, "character")
    second = EntityCardDialog(None, "character")
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    assert first._image_key != second._image_key
    provider = dialog_image_provider()
    first.done(0)
    qtbot.wait(0)
    assert first._image_key not in provider._pixmaps


def test_music_url_opens_only_through_python_bridge(qtbot, monkeypatch):
    dialog = EntityCardDialog(None, "item")
    qtbot.addWidget(dialog)
    opened = []
    monkeypatch.setattr(
        "app.presentation.views.entity_card_dialog.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )
    dialog._set_music_url("https://example.test/music")
    dialog.vm.requestMusicOpen()
    assert opened == ["https://example.test/music"]
    source = Path(ROOT_QML).read_text(encoding="utf-8")
    assert "Qt.openUrlExternally" not in source


def test_removed_widget_implementations_stay_deleted():
    root = Path(__file__).resolve().parents[2]
    removed = (
        "mention_text_edit.py",
        "related_section.py",
        "ai_assist_button.py",
        "clickable_label.py",
        "custom_date_edit.py",
    )
    views = root / "app" / "presentation" / "views"
    assert all(not (views / name).exists() for name in removed)
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "app").rglob("*.py")
    )
    for name in (
        "class MentionTextEdit",
        "class AiAssistButton",
        "class EntityGenerateButton",
        "class ClickableLabel",
        "class CustomDateEdit",
    ):
        assert name not in production
    # Piece C3b retired the Gregorian popup calendar class for good: the
    # popups now compose the game-calendar grid instead.
    assert "class _CustomCalendar" not in production
    assert "class GameCalendarGrid" in production


def test_live_retheme_preserves_card_state_selection_scroll_and_engine(qtbot, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    dialog = EntityCardDialog(None, "character", theme=runtime)
    qtbot.addWidget(dialog)
    relation = SimpleNamespace(id=8, name="Ring")
    dialog.add_related_entity("items", relation)
    dialog.vm.sections["items"].select(0)
    dialog.vm.name = "Keep"
    dialog.vm.hosts["characteristics"].storage = "@[Маг](character:7)"
    scroll = find_item(dialog.quick, "entityCardScroll")
    content = scroll.property("contentItem")
    content.setProperty("contentY", 40.0)
    name_field = find_item(dialog.quick, "entityNameField")
    name_field.forceActiveFocus()
    root = dialog._root
    engine = dialog._engine
    assert runtime.toggle()
    assert dialog._root is root
    assert dialog._engine is engine
    assert dialog.vm.name == "Keep"
    assert dialog.vm.sections["items"].selectedIndex == 0
    assert content.property("contentY") == 40.0
    assert name_field.hasActiveFocus()
    assert dialog.vm.hosts["characteristics"].display == "Маг"
    assert "(character:7)" not in dialog.vm.hosts["characteristics"].display


def test_vm_invokable_edges_and_native_facade_ducks(qtbot, monkeypatch):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    vm = dialog.vm
    vm.setRating(9)
    vm.setNoEnd(True)
    assert vm._rating == 9 and vm._no_end
    vm.set_character_sheet_available(False)
    vm.set_save_locked(True)
    vm.set_save_locked(False)
    vm.setMusicUrl("draft")
    vm.toggleMusicEdit()
    vm.toggleMusicEdit()

    vm.datePopupRequested.disconnect(dialog._open_date_popup)
    with qtbot.waitSignal(vm.datePopupRequested):
        vm.requestDatePopup("end", 1, 2, 3, 4)
    vm.cancelRequested.disconnect(dialog._on_cancel_clicked)
    with qtbot.waitSignal(vm.cancelRequested):
        vm.requestCancel()
    vm.imagePickRequested.disconnect(dialog._on_pick_image)
    with qtbot.waitSignal(vm.imagePickRequested):
        vm.requestImagePick()
    with qtbot.waitSignal(vm.imageClearRequested):
        vm.requestImageClear()
    vm.requestImageOpen()
    vm.set_image_source("image://dialog/test", True)
    vm.imageOpenRequested.disconnect(dialog._open_image_viewer)
    with qtbot.waitSignal(vm.imageOpenRequested):
        vm.requestImageOpen()
    vm.requestCharacterSheet()
    vm.characterSheetRequested.disconnect(dialog.open_character_sheet_requested)
    vm.set_character_sheet_available(True)
    with qtbot.waitSignal(vm.characterSheetRequested):
        vm.requestCharacterSheet()

    dialog.vm.set_dates(start=MonthDay(1200, 1, 2), end=MonthDay(1201, 2, 3))
    assert dialog.vm._start_date == MonthDay(1200, 1, 2)
    assert dialog.vm._end_date == MonthDay(1201, 2, 3)
    assert dialog.end_date_input.isHidden()
    assert dialog.music_input.isHidden() is False
    dialog.music_input.setFocus()
    dialog._set_music_url("https://example.test")
    assert dialog.music_input.isHidden()
    dialog._on_toggle_music_edit()

    pixmap = QPixmap(2, 2)
    pixmap.fill(Qt.GlobalColor.red)
    dialog._display_pixmap(pixmap)
    assert dialog.image_label.text() == ""
    opened = []
    monkeypatch.setattr(dialog, "_open_image_viewer", lambda: opened.append(True))
    dialog.image_label.click()
    assert opened == [True]

    section = dialog._related_sections["items"]
    item = SimpleNamespace(id=2, name="Ring")
    section.set_entities([item])
    assert section._available == []
    assert section.get_current_ids() == [2]


def test_save_guard_saving_close_and_date_routes(qtbot, monkeypatch):
    dialog = EntityCardDialog(None, "item")
    qtbot.addWidget(dialog)
    dialog.saved.connect(lambda _data: None)
    dialog._on_save()
    dialog._on_save()
    close = QCloseEvent()
    dialog.closeEvent(close)
    assert not close.isAccepted()
    dialog.finish_saving(False)

    opened = []
    monkeypatch.setattr(
        dialog.date_popup,
        "open_at",
        lambda anchor, current: opened.append((anchor, current)),
    )
    dialog._open_date_popup("end", 1, 2, 30, 40)
    # Since piece C3b (design D3) the popup bridge carries the dialog's own
    # coordinate pair — the grid paints it, no picture-only clamp.
    assert opened[-1][1] == (dialog.vm._end_date, dialog.vm._end_bc)
    dialog._date_target = "start"
    dialog._set_selected_date(date(1300, 1, 1))
    dialog._date_target = "end"
    dialog._set_selected_date(date(1301, 2, 2))
    assert dialog.vm._start_date == MonthDay(1300, 1, 1)
    assert dialog.vm._end_date == MonthDay(1301, 2, 2)
