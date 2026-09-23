"""Unit tests for the plain edit-state carriers (audit B4, task 6.5.2).

No QApplication: these classes were extracted precisely so the
history/selection/clipboard semantics can be pinned without Qt.
"""
from __future__ import annotations

from app.presentation.viewmodels.sheet_edit_state import (
    FieldClipboard,
    LayoutHistory,
    SelectionModel,
)


class TestLayoutHistory:
    def test_empty_history_has_nothing_to_undo_or_redo(self):
        history = LayoutHistory(limit=3)
        assert history.can_undo is False
        assert history.can_redo is False

    def test_push_undo_enables_undo_and_takes_return_fifo_last(self):
        history = LayoutHistory(limit=3)
        history.push_undo(("a", "p"))
        history.push_undo(("b", "p"))
        assert history.can_undo is True
        assert history.take_undo() == ("b", "p")
        assert history.take_undo() == ("a", "p")
        assert history.can_undo is False

    def test_undo_push_drops_oldest_beyond_limit(self):
        history = LayoutHistory(limit=2)
        history.push_undo(("a", "p"))
        history.push_undo(("b", "p"))
        history.push_undo(("c", "p"))
        # "a" fell off the bottom; only the two newest checkpoints remain
        assert history.take_undo() == ("c", "p")
        assert history.take_undo() == ("b", "p")
        assert history.can_undo is False

    def test_undo_push_clears_redo_by_default(self):
        history = LayoutHistory(limit=3)
        history.push_redo("current")
        assert history.can_redo is True
        history.push_undo(("a", "p"))
        assert history.can_redo is False

    def test_push_undo_with_clear_redo_false_keeps_redo_branch(self):
        # the redo() path: parking the current layout as the undo counterpart
        # of the entry about to be taken from the redo branch
        history = LayoutHistory(limit=3)
        history.push_redo("redo-entry")
        history.push_undo(("a", "p"), clear_redo=False)
        assert history.can_redo is True
        assert history.take_redo() == "redo-entry"

    def test_push_redo_is_uncapped(self):
        history = LayoutHistory(limit=1)
        history.push_redo("one")
        history.push_redo("two")
        assert history.take_redo() == "two"
        assert history.take_redo() == "one"

    def test_drop_top_if_matches_discards_unchanged_head(self):
        history = LayoutHistory(limit=3)
        history.push_undo(("x", "p"))
        assert history.drop_top_if_matches(("x", "p")) is True
        assert history.can_undo is False
        # with no matching head it is a no-op (and reports that)
        history.push_undo(("y", "p"))
        assert history.drop_top_if_matches(("z", "p")) is False
        assert history.can_undo is True

    def test_drop_top_if_matches_on_empty_history(self):
        assert LayoutHistory(limit=3).drop_top_if_matches(("x", "p")) is False

    def test_clear_empties_both_branches(self):
        history = LayoutHistory(limit=3)
        history.push_undo(("a", "p"))
        history.push_undo(("b", "p"), clear_redo=False)
        history.push_redo("r")
        history.clear()
        assert history.can_undo is False
        assert history.can_redo is False


class TestSelectionModel:
    def test_starts_empty_with_no_primary(self):
        sel = SelectionModel()
        assert sel.ids == []
        assert sel.primary is None

    def test_set_replaces_content_and_keeps_order(self):
        sel = SelectionModel()
        sel.set(["b", "a"])
        assert sel.ids == ["b", "a"]
        sel.ids.append("c")  # live list by contract — the VM mutates in place
        assert sel.ids == ["b", "a", "c"]

    def test_primary_only_for_exactly_one_id(self):
        sel = SelectionModel()
        sel.set(["only"])
        assert sel.primary == "only"
        sel.set(["one", "two"])
        assert sel.primary is None  # multi has no canonical label

    def test_set_can_empty_the_selection(self):
        sel = SelectionModel()
        sel.set(["x"])
        sel.set([])
        assert sel.ids == []
        assert sel.primary is None


class TestFieldClipboard:
    def test_starts_empty(self):
        clip = FieldClipboard()
        assert clip.items == []
        assert not clip.items

    def test_set_items_replaces_content(self):
        clip = FieldClipboard()
        field_a, field_b = object(), object()
        clip.set_items([(field_a, 0)])
        assert clip.items == [(field_a, 0)]
        clip.set_items([(field_b, 1), (field_a, 2)])
        assert clip.items == [(field_b, 1), (field_a, 2)]

    def test_items_list_is_live_for_the_copy_fill_loop(self):
        clip = FieldClipboard()
        clip.set_items([])
        clip.items.append(("f", 3))  # copy() fills through the live getter
        assert clip.items == [("f", 3)]
