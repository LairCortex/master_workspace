"""Tests for the shared RelatedSection widget.

Covers the contract both dialogs rely on: add / get_current_ids, the
multi-select «Привязать существующего» picker (modal exec auto-accepted),
«Отвязать», and the create_requested signal.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtWidgets import QDialog, QListWidget

from app.presentation.views.related_section import RelatedSection


def _entity(id_: int, name: str) -> MagicMock:
    e = MagicMock()
    e.id = id_
    e.name = name
    return e


def _stub_picker_exec(monkeypatch, rows: int | list[int]) -> None:
    """Auto-accept the next QDialog.exec() with the given picker row(s) selected."""

    def fake_exec(self, *a, **k):
        want = {rows} if isinstance(rows, int) else set(rows)
        for lst in self.findChildren(QListWidget):
            if lst.count():
                for i in range(lst.count()):
                    lst.item(i).setSelected(i in want)
                break
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)


class TestRelatedSection:
    def test_add_entity_appears_in_list(self, qtbot):
        s = RelatedSection("characters", "character", "Персонажи")
        qtbot.addWidget(s)
        s.add_entity(_entity(1, "Герой"))
        assert s.list_widget.count() == 1
        assert s.list_widget.item(0).text() == "Герой"
        assert s.get_current_ids() == [1]

    def test_set_entities_replaces_list(self, qtbot):
        s = RelatedSection("characters", "character", "Персонажи")
        qtbot.addWidget(s)
        s.add_entity(_entity(1, "A"))
        s.set_entities([_entity(2, "B")])
        assert s.list_widget.count() == 1
        assert s.get_current_ids() == [2]

    def test_set_available_feeds_candidates(self, qtbot):
        s = RelatedSection("locations", "location", "Локации")
        qtbot.addWidget(s)
        s.set_available([_entity(1, "Лес"), _entity(2, "Речка")])
        assert len(s._available) == 2

    def test_link_existing_multi_select(self, qtbot, monkeypatch):
        s = RelatedSection("locations", "location", "Локации")
        qtbot.addWidget(s)
        s.set_available([_entity(1, "Лес"), _entity(2, "Речка")])
        _stub_picker_exec(monkeypatch, [0, 1])
        s.link_button.click()
        assert s.get_current_ids() == [1, 2]
        assert s.list_widget.count() == 2

    def test_link_existing_single_select(self, qtbot, monkeypatch):
        s = RelatedSection("locations", "location", "Локации")
        qtbot.addWidget(s)
        s.set_available([_entity(1, "Лес"), _entity(2, "Речка")])
        _stub_picker_exec(monkeypatch, 1)
        s.link_button.click()
        assert s.get_current_ids() == [2]

    def test_link_existing_excludes_already_linked(self, qtbot, monkeypatch):
        s = RelatedSection("characters", "character", "Персонажи")
        qtbot.addWidget(s)
        s.set_entities([_entity(1, "Герой")])
        s.set_available([_entity(1, "Герой"), _entity(2, "Гость")])
        _stub_picker_exec(monkeypatch, 0)  # the only candidate left is id 2
        s.link_button.click()
        assert s.get_current_ids() == [1, 2]

    def test_link_existing_no_candidates_no_dialog(self, qtbot, monkeypatch):
        opened: list = []
        monkeypatch.setattr(QDialog, "exec", lambda self, *a, **k: opened.append(self))
        s = RelatedSection("characters", "character", "Персонажи")
        qtbot.addWidget(s)
        s.set_available([_entity(1, "Герой")])
        s.set_entities([_entity(1, "Герой")])  # already linked → no candidates
        s.link_button.click()
        assert opened == []
        assert s.get_current_ids() == [1]

    def test_remove_selected(self, qtbot):
        s = RelatedSection("characters", "character", "Персонажи")
        qtbot.addWidget(s)
        s.add_entity(_entity(1, "Герой"))
        s.add_entity(_entity(2, "Гость"))
        s.list_widget.setCurrentRow(0)
        s.remove_button.click()
        assert s.get_current_ids() == [2]

    def test_remove_out_of_range_is_noop(self, qtbot):
        s = RelatedSection("characters", "character", "Персонажи")
        qtbot.addWidget(s)
        s.remove_button.click()  # nothing selected — safe no-op
        assert s.get_current_ids() == []

    def test_create_button_emits_create_requested(self, qtbot):
        s = RelatedSection("items", "item", "Предметы")
        qtbot.addWidget(s)
        received: list = []
        s.create_requested.connect(lambda: received.append(1))
        s.create_button.click()
        assert received == [1]
