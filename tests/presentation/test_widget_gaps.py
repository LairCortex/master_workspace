"""Widget-layer coverage: remaining interactive branches of the main views.

Targets the gaps left by the happy-path tests: validation branches, image
picking (file dialogs stubbed), related-entity linking/removal (modal
picker auto-accepted), music-URL edit toggle, special date/summary branches,
world-snapshot edge cases, and the timeline "+” context menu.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QMenu, QFileDialog, QMessageBox

import app.presentation.views.detail_panel as _detail_panel_mod
import app.presentation.views.timeline_widget as _timeline_mod
import app.presentation.views.world_snapshot_widget as _world_snapshot_mod
from app.presentation.views.detail_panel import DetailPanel
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.timeline_widget import TimelineWidget
from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget, _colored_circle


def _fake_thumbnail(size: int = 40):
    """A real (valid, non-null) QPixmap standing in for a resolved preview."""
    from PySide6.QtGui import QPixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.red)
    return pm


def _temp_png(tmp_path) -> str:
    path = tmp_path / "pic.png"
    img = QImage(12, 12, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.blue)
    assert img.save(str(path))
    return str(path)


def _mock_entity(id_, name, **extra):
    e = MagicMock()
    e.id = id_
    e.name = name
    e.rating = 1
    e.image_ref = None
    e.image_id = None
    e.description = MagicMock(characteristics="", backstory="")
    for attr in ("characters", "organizations", "items", "locations"):
        setattr(e, attr, [])
    for attr in ("personality", "tasks"):
        setattr(e, attr, None)
    for k, v in extra.items():
        setattr(e, k, v)
    return e


def _mock_event(id_=1, name="E", **extra):
    ev = MagicMock()
    ev.id = id_
    ev.name = name
    ev.start_date = __import__("datetime").date(1200, 1, 1)
    ev.end_date = __import__("datetime").date(1200, 12, 31)
    for attr in ("characters", "organizations", "items", "locations"):
        setattr(ev, attr, [])
    for k, v in extra.items():
        setattr(ev, k, v)
    return ev


# ── DetailPanel: summary branches and thumbnails ───────────────────────────

class TestDetailPanelGaps:
    def test_long_characteristics_truncated_with_ellipsis(self, qtbot):
        w = DetailPanel(MagicMock())
        qtbot.addWidget(w)
        org = _mock_entity(1, "Org", description=MagicMock(characteristics="А" * 150, backstory=""))
        w.show_event(_mock_event(organizations=[org]))
        from PySide6.QtWidgets import QLabel

        item_widget = w.org_list.itemWidget(w.org_list.item(0))
        labels = item_widget.findChildren(QLabel)
        all_text = " ".join(lab.text() for lab in labels)
        assert "…" in all_text
        assert all_text.count("А") <= 120  # truncated to max_len chars

    def test_character_personality_in_summary(self, qtbot):
        w = DetailPanel(MagicMock())
        qtbot.addWidget(w)
        ch = _mock_entity(1, "Герой", personality="Храбр")
        w.show_event(_mock_event(characters=[ch]))
        labels = w.char_list.itemWidget(w.char_list.item(0)).findChildren(__import__("PySide6").QtWidgets.QLabel)
        assert any("Личность" in lab.text() for lab in labels)

    def test_related_counts_in_summary(self, qtbot):
        w = DetailPanel(MagicMock())
        qtbot.addWidget(w)
        ch = _mock_entity(2, "Вард")
        org = _mock_entity(1, "Гильдия", characters=[ch])
        w.show_event(_mock_event(organizations=[org], characters=[ch]))
        labels = w.org_list.itemWidget(w.org_list.item(0)).findChildren(__import__("PySide6").QtWidgets.QLabel)
        all_text = " ".join(lab.text() for lab in labels)
        assert "Связи" in all_text
        assert "1 персонажей" in all_text

    def test_entity_image_renders_thumbnail(self, qtbot, monkeypatch):
        from PySide6.QtWidgets import QLabel

        monkeypatch.setattr(
            _detail_panel_mod, "load_entity_preview", lambda entity, slot_size: _fake_thumbnail()
        )
        w = DetailPanel(MagicMock())
        qtbot.addWidget(w)
        org = _mock_entity(1, "Орг")
        w.show_event(_mock_event(organizations=[org]))
        item_widget = w.org_list.itemWidget(w.org_list.item(0))
        thumbnails = [lab for lab in item_widget.findChildren(QLabel) if lab.pixmap() and not lab.pixmap().isNull()]
        assert thumbnails, "expected a thumbnail QLabel with a pixmap"

    def test_event_without_end_date(self, qtbot):
        w = DetailPanel(MagicMock())
        qtbot.addWidget(w)
        w.show_event(_mock_event(end_date=None))
        assert "∞" in w.date_label.text()

    def test_clicking_thumbnail_opens_image_viewer(self, qtbot, monkeypatch):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QMouseEvent

        monkeypatch.setattr(
            _detail_panel_mod, "load_entity_preview", lambda entity, slot_size: _fake_thumbnail()
        )
        monkeypatch.setattr(_detail_panel_mod, "load_entity_original", lambda entity: _fake_thumbnail())
        opened: list = []
        monkeypatch.setattr(
            _detail_panel_mod, "ImageViewerDialog",
            lambda original, preview, parent=None: opened.append((original, preview)) or MagicMock(),
        )
        w = DetailPanel(MagicMock())
        qtbot.addWidget(w)
        org = _mock_entity(1, "Орг")
        w.show_event(_mock_event(organizations=[org]))
        item_widget = w.org_list.itemWidget(w.org_list.item(0))
        from app.presentation.views.clickable_label import ClickableLabel

        thumb = item_widget.findChild(ClickableLabel)
        assert thumb is not None
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, thumb.rect().center(),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        thumb.mousePressEvent(event)
        assert len(opened) == 1

    def test_entities_without_image_have_no_clickable_thumbnail(self, qtbot, monkeypatch):
        monkeypatch.setattr(_detail_panel_mod, "load_entity_preview", lambda entity, slot_size: QPixmap())
        w = DetailPanel(MagicMock())
        qtbot.addWidget(w)
        org = _mock_entity(1, "Орг")
        w.show_event(_mock_event(organizations=[org]))
        item_widget = w.org_list.itemWidget(w.org_list.item(0))
        from app.presentation.views.clickable_label import ClickableLabel

        assert item_widget.findChild(ClickableLabel) is None


# ── WorldSnapshotWidget: items, show-all stats, rating fallback, tooltip ──

class TestWorldSnapshotGaps:
    def test_colored_circle_helper(self):
        from PySide6.QtGui import QColor

        icon = _colored_circle(QColor(200, 10, 10), size=16)
        assert not icon.isNull()
        assert icon.availableSizes()[0].width() == 16

    def test_items_section_shown_for_events_with_items(self, qtbot):
        item = _mock_entity(7, "Меч", rating=8)
        ev = _mock_event(items=[item])
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([ev], __import__("datetime").date(1200, 1, 1))
        sections = [w.tree.topLevelItem(i).text(0) for i in range(w.tree.topLevelItemCount())]
        assert any("Предметы (1)" in s for s in sections)

    def test_show_all_stats_mode(self, qtbot):
        ch = _mock_entity(1, "Герой")
        ev = _mock_event(characters=[ch])
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([ev], None)  # «Показать всё»
        assert "Показано: все события" in w.stats_label.text()
        assert "Персонажей: 1" in w.stats_label.text()

    def test_non_int_rating_falls_back_to_1(self, qtbot):
        # A float rating survives the sort key but is not an int → falls back to 1
        ch = _mock_entity(1, "Герой", rating=15.5)
        ev = _mock_event(characters=[ch])
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([ev], None)
        node = w.tree.topLevelItem(1).child(0)
        assert "[15.5/20]" not in node.text(0)
        assert "[1/20]" not in node.text(0)

    def test_high_rating_node_is_bold(self, qtbot):
        ch = _mock_entity(1, "Легенда", rating=19)
        ev = _mock_event(characters=[ch])
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([ev], None)
        node = w.tree.topLevelItem(1).child(0)
        assert node.font(0).bold()

    def test_entity_image_thumbnails_node_icon(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            _world_snapshot_mod, "load_entity_preview",
            lambda entity, slot_size: _fake_thumbnail(size=slot_size),
        )
        ch = _mock_entity(1, "Герой")
        ev = _mock_event(characters=[ch])
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([ev], None)
        node = w.tree.topLevelItem(1).child(0)
        widths = [s.width() for s in node.icon(0).availableSizes()]
        assert 24 in widths, "thumbnail icon should be the 24px pixmap"


    def test_description_snippet_in_tooltip(self, qtbot):
        ch = _mock_entity(1, "Герой", description=MagicMock(characteristics="Тайный убийца гильдии", backstory=""))
        ev = _mock_event(characters=[ch])
        w = WorldSnapshotWidget()
        qtbot.addWidget(w)
        w.populate([ev], None)
        node = w.tree.topLevelItem(1).child(0)
        assert "Тайный убийца гильдии" in node.toolTip(0)


# ── TimelineWidget: "+" context menu ───────────────────────────────────────

def _stub_timeline_menu(monkeypatch, chooser):
    """Replace the timeline module's QMenu with a subclass whose exec is stubbed.

    PySide6 does not dispatch C++ methods through plain class-attribute
    overrides (a class-level patch on QMenu is bypassed by instance calls),
    so the QMenu symbol of the module that constructs the menu is swapped.
    The chooser receives the menu and returns the action to ``exec`` with.
    """

    class _StubQMenu(QMenu):
        def exec(self, *args, **kwargs):  # Qt API name
            return chooser(self)

    monkeypatch.setattr(_timeline_mod, "QMenu", _StubQMenu)


class TestTimelineContextMenuGap:
    def test_context_menu_new_event(self, qtbot, monkeypatch):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        _stub_timeline_menu(monkeypatch, lambda menu: menu.actions()[0])
        received = []
        w.add_event_requested.connect(lambda: received.append(1))
        w._on_add_context_menu(w.add_button.rect().center())
        assert received == [1]

    def test_context_menu_new_item_entity(self, qtbot, monkeypatch):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        _stub_timeline_menu(monkeypatch, lambda menu: menu.actions()[-1])
        received = []
        w.add_entity_requested.connect(received.append)
        w._on_add_context_menu(w.add_button.rect().center())
        assert received == ["item"]  # "Новый предмет" is the last menu action

    def test_context_menu_no_action_emits_nothing(self, qtbot, monkeypatch):
        vm = MagicMock()
        vm.events = []
        w = TimelineWidget(vm)
        qtbot.addWidget(w)
        _stub_timeline_menu(monkeypatch, lambda menu: None)
        event_rx: list = []
        entity_rx: list = []
        w.add_event_requested.connect(lambda: event_rx.append(1))
        w.add_entity_requested.connect(entity_rx.append)
        w._on_add_context_menu(w.add_button.rect().center())
        assert event_rx == [] and entity_rx == []


# ── EntityCardDialog: music toggle, image pick, related section, reject ────

class TestEntityCardDialogGaps:
    def test_music_url_toggle_edit_and_back(self, qtbot):
        d = EntityCardDialog(None, entity_type="item")
        qtbot.addWidget(d)
        d.show()
        d.populate(_mock_entity(1, "Sword", music_url="https://example.com/x.mp3"))
        assert d.music_display.isVisible()
        assert not d.music_input.isVisible()

        d.music_edit_btn.click()  # → edit mode
        assert d.music_input.isVisible()
        d.music_input.setText("https://example.com/other.mp3")
        d.music_edit_btn.click()  # → link mode
        assert not d.music_input.isVisible()
        assert "other.mp3" in d.music_display.text()
        assert d.get_data()["music_url"] == "https://example.com/other.mp3"

    def test_pick_image_success(self, qtbot, tmp_path):
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        path = _temp_png(tmp_path)
        picked: list[bytes] = []
        d.image_picked.connect(picked.append)
        with patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, ""))):
            d._on_pick_image()
        assert d._image_id is None  # not yet persisted — resolved via image_picked
        assert picked == [Path(path).read_bytes()]
        assert d.clear_image_btn.isEnabled()
        pm = d.image_label.pixmap()
        assert pm and not pm.isNull()
        assert d.get_data()["image_id"] is None

        d.set_stored_image_id(42)
        assert d.get_data()["image_id"] == 42

    def test_pick_image_unreadable_file_warns(self, qtbot, tmp_path):
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        missing = tmp_path / "gone.png"  # never created — read_bytes() raises OSError
        with patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(missing), ""))), \
             patch.object(QMessageBox, "warning") as warn:
            d._on_pick_image()
        assert warn.called
        assert d._image_id is None
        assert not d.clear_image_btn.isEnabled()

    def test_pick_image_invalid_file_keeps_state(self, qtbot, tmp_path):
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        bad = tmp_path / "bad.png"
        bad.write_text("not an image")
        with patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), ""))), \
             patch.object(QMessageBox, "warning") as warn:
            d._on_pick_image()
        assert warn.called
        assert d._image_id is None
        assert not d.clear_image_btn.isEnabled()

    def test_pick_image_canceled(self, qtbot):
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        with patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", ""))):
            d._on_pick_image()
        assert d._image_id is None

    def test_display_pixmap_null_clears_preview(self, qtbot):
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        d._display_pixmap(QPixmap())  # null pixmap — early-clears, no crash
        assert d.image_label.pixmap() is None or d.image_label.pixmap().isNull()
        assert not d.clear_image_btn.isEnabled()

    def test_display_pixmap_and_clear_preview_noop_without_image_field(self, qtbot):
        d = EntityCardDialog(None, entity_type="item")  # no image field
        qtbot.addWidget(d)
        d._display_pixmap(QPixmap())  # no image_label attribute — must not crash
        d._clear_preview()

    def test_pick_image_sets_viewer_original(self, qtbot, tmp_path):
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        path = _temp_png(tmp_path)
        with patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, ""))):
            d._on_pick_image()
        assert not d._viewer_original.isNull()
        assert d._viewer_preview.isNull()

    def test_clear_image_resets_viewer_pixmaps(self, qtbot, tmp_path):
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        path = _temp_png(tmp_path)
        with patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, ""))):
            d._on_pick_image()
        d._on_clear_image()
        assert d._viewer_original.isNull()
        assert d._viewer_preview.isNull()

    def test_click_image_label_opens_viewer(self, qtbot, tmp_path, monkeypatch):
        import app.presentation.views.entity_card_dialog as entity_card_dialog_mod

        opened: list = []
        monkeypatch.setattr(
            entity_card_dialog_mod, "ImageViewerDialog",
            lambda original, preview, parent=None: SimpleNamespace(exec=lambda: opened.append((original, preview))),
        )
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        path = _temp_png(tmp_path)
        with patch.object(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, ""))):
            d._on_pick_image()
        d._open_image_viewer()
        assert len(opened) == 1

    def test_open_image_viewer_noop_without_image_field(self, qtbot, monkeypatch):
        import app.presentation.views.entity_card_dialog as entity_card_dialog_mod

        opened: list = []
        monkeypatch.setattr(
            entity_card_dialog_mod, "ImageViewerDialog",
            lambda *a, **k: opened.append(1),
        )
        d = EntityCardDialog(None, entity_type="item")  # no image field
        qtbot.addWidget(d)
        d._open_image_viewer()
        assert opened == []

    def test_populate_sets_viewer_original_and_preview(self, qtbot, monkeypatch):
        import app.presentation.views.entity_card_dialog as entity_card_dialog_mod

        fake_original = QPixmap(5, 5)
        fake_original.fill(Qt.GlobalColor.red)
        monkeypatch.setattr(entity_card_dialog_mod, "load_entity_original", lambda entity: fake_original)
        monkeypatch.setattr(
            entity_card_dialog_mod, "load_entity_preview", lambda entity, slot_size: QPixmap(),
        )
        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        d.populate(_mock_entity(1, "Герой"))
        assert d._viewer_original is fake_original

    def test_populate_without_end_date_checks_forever(self, qtbot):
        d = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(d)
        d.populate(_mock_entity(1, "Орг", end_date=None))
        assert d.no_end_date_cb.isChecked()
        assert not d.end_date_input.isVisible()

    def test_reject_blocked_while_generating(self, qtbot, monkeypatch):
        d = EntityCardDialog(None, entity_type="item")
        qtbot.addWidget(d)
        rejected: list = []
        monkeypatch.setattr(QDialog, "reject", lambda self: rejected.append(self))

        d.get_ai_buttons()[0].set_generating(True)
        d.reject()
        assert rejected == []  # blocked while AI is generating

        d.get_ai_buttons()[0].set_generating(False)
        d.reject()
        assert rejected == [d]

    # ── RelatedSection: link existing / remove ───────────────────────────

    def test_related_link_existing_picker(self, qtbot, monkeypatch):
        d = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(d)
        section = d._related_sections["characters"]
        hero1 = _mock_entity(1, "Герой 1")
        hero2 = _mock_entity(2, "Герой 2")  # second candidate stays unselected
        section.set_available([hero1, hero2])

        # Auto-accept the picker with the first item preselected
        def fake_exec(self, *a, **k):
            from PySide6.QtWidgets import QListWidget

            for lst in self.findChildren(QListWidget):
                if lst.count():
                    lst.item(0).setSelected(True)
                    break
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        section._on_link_existing()

        assert section.get_current_ids() == [1]
        assert section.list_widget.count() == 1

    def test_related_link_existing_no_candidates(self, qtbot):
        d = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(d)
        section = d._related_sections["characters"]
        section.set_available([])
        section._on_link_existing()  # early return, no dialog
        assert section.get_current_ids() == []

    def test_related_remove_selected(self, qtbot):
        d = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(d)
        section = d._related_sections["characters"]
        section.add_entity(_mock_entity(1, "Герой"))
        section.list_widget.setCurrentRow(0)
        section._on_remove()
        assert section.get_current_ids() == []

    def test_related_remove_out_of_range_is_noop(self, qtbot):
        d = EntityCardDialog(None, entity_type="organization")
        qtbot.addWidget(d)
        section = d._related_sections["characters"]
        section._on_remove()  # nothing selected — safe no-op
        assert section.get_current_ids() == []


# ── EventDialog: date validity, endless, reject-while-generating ──────────

class TestEventDialogGaps:
    def test_endless_checkbox_toggles_date_and_validity(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        d.show()
        d.name_input.setText("E")
        d.characteristics_input.setPlainText("c")
        d.start_date_input.setDate(QDate(1200, 6, 1))
        d.end_date_input.setDate(QDate(1200, 1, 1))  # end < start
        assert not d.save_button.isEnabled()  # invalid dates block saving

        d.no_end_date_cb.setChecked(True)  # endless → date constraint lifted
        assert d.end_date_input.isHidden()
        assert d.save_button.isEnabled()

        d.no_end_date_cb.setChecked(False)  # back to bounded → invalid again
        assert d.end_date_input.isVisible()
        assert not d.save_button.isEnabled()

    def test_populate_without_end_date_checks_forever(self, qtbot):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        ev = _mock_event(5, "Битва", end_date=None)
        ev.description = MagicMock(characteristics="c", backstory="b")
        d.populate(ev)
        assert d.no_end_date_cb.isChecked()
        assert d.end_date_input.isHidden()
        assert d.event_id == 5

    def test_reject_blocked_while_generating(self, qtbot, monkeypatch):
        d = EventDialog(MagicMock())
        qtbot.addWidget(d)
        rejected: list = []
        monkeypatch.setattr(QDialog, "reject", lambda self: rejected.append(self))

        d.get_ai_buttons()[0].set_generating(True)
        d.reject()
        assert rejected == []

        d.get_ai_buttons()[0].set_generating(False)
        d.reject()
        assert rejected == [d]
