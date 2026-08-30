"""Regression tests for the W2b review fixes (screen-side half).

The runtime-side fixes (listener isolation/dedup) live in
``test_theme_apply.py``; here: the per-screen consequences of switching
tokens live — stale item bookkeeping, snapshot rating re-tint, search-header
brushes, undo survival, and the mono rule not being overridden by QSS roots.
"""
from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QApplication

from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime


def _runtime(tmp_path, theme="dark", **token_overrides):
    tokens = json.loads(tokens_file_path().read_text(encoding="utf-8"))
    for key, value in token_overrides.items():
        tokens[key] = value
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(tokens), encoding="utf-8")
    prefs = UiPrefsManager(tmp_path / "ui.json")
    if theme != "dark":
        prefs.save(UiPrefs(theme=theme))
    return ThemeRuntime(prefs=prefs, tokens_path=tokens_path)


def _entity(i=1, rating=5):
    return SimpleNamespace(
        id=i, name=f"E{i}", rating=rating,
        description=None, personality=None, tasks=None, start_date=None,
    )


# ── detail_panel: clear() must not keep dead item bookkeeping ──────────────

class TestDetailPanelClearPrunes:
    def _panel(self, tmp_path, qtbot):
        from app.presentation.views.detail_panel import DetailPanel
        runtime = _runtime(tmp_path)
        panel = DetailPanel(SimpleNamespace(), theme=runtime)
        qtbot.addWidget(panel)
        event = SimpleNamespace(
            id=1, name="E", start_date=datetime.date(2020, 1, 1), end_date=None,
            organizations=[_entity()], characters=[_entity(2)], items=[], locations=[],
        )
        panel.show_event(event)
        return panel

    def test_fill_tracks_live_item_widgets(self, tmp_path, qtbot):
        panel = self._panel(tmp_path, qtbot)
        assert len(panel._item_widgets) == 2

    def test_clear_prunes_immediately(self, tmp_path, qtbot, qapp):
        panel = self._panel(tmp_path, qtbot)
        panel.clear()
        qapp.processEvents()
        from PySide6.QtCore import QEvent
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        panel._prune_item_widgets()
        assert panel._item_widgets == []

    def test_toggle_after_clear_survives(self, tmp_path, qtbot, qapp):
        """The crash-shaped case: theme switch on a cleared panel must be a
        plain no-op, not an exception on a destroyed wrapper."""
        from app.presentation.views.detail_panel import DetailPanel
        runtime = _runtime(tmp_path)
        panel = DetailPanel(SimpleNamespace(), theme=runtime)
        qtbot.addWidget(panel)
        event = SimpleNamespace(
            id=1, name="E", start_date=datetime.date(2020, 1, 1), end_date=None,
            organizations=[_entity()], characters=[], items=[], locations=[],
        )
        panel.show_event(event)
        panel.clear()
        qapp.processEvents()
        assert runtime.toggle() is True


# ── world_snapshot: rating nodes follow a live theme switch ────────────────

class TestSnapshotRatingLiveRetheme:
    def test_node_background_moves_with_token(self, tmp_path, qtbot):
        from PySide6.QtCore import Qt
        from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget
        runtime = _runtime(
            tmp_path,
            **{"color.rating.high": {"light": "#ff0000", "dark": "#0000ff"}},
        )
        widget = WorldSnapshotWidget(theme=runtime)
        qtbot.addWidget(widget)
        event = SimpleNamespace(
            id=1, name="E", start_date=datetime.date(2020, 1, 1), end_date=None,
            characters=[_entity(1, rating=20)],
            organizations=[], items=[], locations=[],
        )
        widget.populate([event], datetime.date(2020, 1, 1))

        def entity_brush():
            tree = widget.tree
            for i in range(tree.topLevelItemCount()):
                section = tree.topLevelItem(i)
                for j in range(section.childCount()):
                    child = section.child(j)
                    data = child.data(0, Qt.ItemDataRole.UserRole)
                    if data and data[0] == "character":  # event nodes carry no tint
                        return child.background(0)
            raise AssertionError("entity node missing")

        dark = QColor(runtime.tokens["color.rating.high"]["dark"])
        dark.setAlpha(220)
        assert entity_brush().color().getRgb() == dark.getRgb()

        assert runtime.toggle() is True
        light = QColor("#ff0000")
        light.setAlpha(220)
        assert entity_brush().color().getRgb() == light.getRgb()

    def test_populate_resets_tracking(self, tmp_path, qtbot):
        from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget
        runtime = _runtime(tmp_path)
        widget = WorldSnapshotWidget(theme=runtime)
        qtbot.addWidget(widget)
        event = SimpleNamespace(
            id=1, name="E", start_date=datetime.date(2020, 1, 1), end_date=None,
            characters=[_entity()], organizations=[], items=[], locations=[],
        )
        widget.populate([event], datetime.date(2020, 1, 1))
        assert widget._rated_nodes
        widget._on_clear()
        assert widget._rated_nodes == []
        assert runtime.toggle() is True  # no stale nodes to touch


# ── search_bar: header brushes follow the theme ────────────────────────────

class TestSearchHeaderLiveRetheme:
    def test_header_recolors_after_toggle(self, tmp_path, qtbot):
        from app.presentation.views.search_bar import SearchBar, _HEADER_DATA_ROLE
        runtime = _runtime(
            tmp_path,
            **{"color.border": {"light": "#101010", "dark": "#efefef"}},
        )
        class _Sig:
            def connect(self, _cb):  # SearchBar only connects
                pass

        vm = SimpleNamespace(results={}, results_changed=_Sig())
        bar = SearchBar(vm, theme=runtime)
        qtbot.addWidget(bar)
        vm.results = {"characters": [_entity(3)]}
        bar._show_results()
        header = next(
            bar.results_list.item(i)
            for i in range(bar.results_list.count())
            if bar.results_list.item(i).data(_HEADER_DATA_ROLE)
        )
        before = QColor(header.background().color())
        assert before == QColor("#efefef")
        assert runtime.toggle() is True
        assert QColor(header.background().color()) == QColor("#101010")

    def test_unparsable_border_token_paints_nothing(self, tmp_path, qtbot):
        """A border token Qt cannot parse leaves the header uncoloured —
        ``QColor`` would hand back an invalid (black-rendering) color, and an
        invented black is exactly what D7 forbids."""
        from PySide6.QtCore import Qt
        from app.presentation.views.search_bar import SearchBar, _HEADER_DATA_ROLE

        runtime = _runtime(
            tmp_path,
            **{"color.border": {"light": "#101010", "dark": "не-цвет"}},
        )

        class _Sig:
            def connect(self, _cb):  # SearchBar only connects
                pass

        vm = SimpleNamespace(results={}, results_changed=_Sig())
        bar = SearchBar(vm, theme=runtime)
        qtbot.addWidget(bar)
        vm.results = {"characters": [_entity(3)]}
        bar._show_results()
        header = next(
            bar.results_list.item(i)
            for i in range(bar.results_list.count())
            if bar.results_list.item(i).data(_HEADER_DATA_ROLE)
        )
        assert header.background().style() == Qt.BrushStyle.NoBrush
        # The load-time contract still holds: the other theme's valid value
        # colors the header again after a live switch.
        assert runtime.toggle() is True
        assert QColor(header.background().color()) == QColor("#101010")


# ── attach_theme(on_retheme=…): the screens' content re-render is wired ─────

class TestOnRethemeIsWired:
    """``on_retheme`` exists for the content QSS cannot reach (item brushes,
    rating tints) — every user of it is a production screen, so a dead
    parameter cannot hide behind a test-only callback (W2b review)."""

    def test_screens_subscribe_their_content_callback(self, tmp_path, qtbot):
        from app.presentation.views.detail_panel import DetailPanel
        from app.presentation.views.search_bar import SearchBar
        from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

        runtime = _runtime(tmp_path)

        class _Sig:
            def connect(self, _cb):  # SearchBar only connects
                pass

        panel = DetailPanel(SimpleNamespace(), theme=runtime)
        bar = SearchBar(SimpleNamespace(results={}, results_changed=_Sig()), theme=runtime)
        snapshot = WorldSnapshotWidget(theme=runtime)
        qtbot.addWidget(panel)
        qtbot.addWidget(bar)
        qtbot.addWidget(snapshot)

        callbacks = {
            panel._on_theme_changed,
            bar._retheme_headers,
            snapshot._on_theme_changed,
        }
        assert callbacks <= set(runtime.subscribers)


# ── mention editor: live re-tint keeps the undo history ────────────────────

class TestMentionRetintUndo:
    def test_undo_history_survives_theme_switch(self, qtbot, tmp_path):
        from app.presentation.views.mention_text_edit import MentionTextEdit
        runtime = _runtime(
            tmp_path,
            **{"color.accent": {"light": "#11eeaa", "dark": "#aa11ee"}},
        )
        edit = MentionTextEdit(theme=runtime)
        qtbot.addWidget(edit)
        edit.setContent("Текст с @[Артас](character:42) внутри")
        assert not edit.document().isUndoAvailable()  # fresh document

        assert runtime.toggle() is True
        # The new accent reached the document…
        assert "color:#11eeaa" in edit.toHtml()
        # …and the switch itself was the only (undoable) document mutation:
        # a full setHtml rebuild would have left no history at all, while the
        # content edit *before* the switch is still revertible together with it.
        assert edit.document().isUndoAvailable()
        edit.document().undo()
        text = edit.getContent()
        assert "Текст с @[Артас](character:42) внутри" in text

    def test_theme_switch_does_not_dirty_the_document(self, qtbot, tmp_path):
        """A repaint is not user content: switching the theme must not make an
        open entity card "dirty" (closing it would warn about colors nobody
        typed), and it must not clear dirt the user really made either."""
        from app.presentation.views.mention_text_edit import MentionTextEdit
        runtime = _runtime(
            tmp_path,
            **{"color.accent": {"light": "#11eeaa", "dark": "#aa11ee"}},
        )
        edit = MentionTextEdit(theme=runtime)
        qtbot.addWidget(edit)
        edit.setContent("Текст с @[Артас](character:42) внутри")
        assert not edit.document().isModified()

        assert runtime.toggle() is True
        assert "color:#11eeaa" in edit.toHtml()  # the repaint did happen
        assert not edit.document().isModified()

        edit.insertPlainText(" ещё")
        assert edit.document().isModified()
        assert runtime.toggle() is True
        assert edit.document().isModified()  # a real edit stays dirty

    def test_off_skin_switch_touches_nothing(self, tmp_path, qtbot):
        """No tokens → no invented colors, and the toggle stays silent (D7)."""
        from app.presentation.views.mention_text_edit import MentionTextEdit
        tokens_path = tmp_path / "tokens.json"
        tokens_path.write_text("{ broken", encoding="utf-8")
        runtime = ThemeRuntime(
            prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_path
        )
        edit = MentionTextEdit(theme=runtime)
        qtbot.addWidget(edit)
        edit.setContent("@[A](character:1)")
        assert "color:#aa11ee" not in edit.toHtml()
        assert runtime.toggle() is False  # invalid tokens: no-op (W1 D7)


# ── doc viewer: chrome-attached mono comes from the QSS rule, not setFont ──

class TestDocViewerMonoLive:
    def test_attached_mono_follows_token(self, tmp_path, qtbot):
        from PySide6.QtWidgets import QPlainTextEdit
        from app.presentation.views.main_window import _DocViewerDialog
        runtime = _runtime(
            tmp_path,
            **{"font.family.mono": {
                "light": "Monaco, monospace", "dark": "Menlo, monospace",
            }},
        )
        dlg = _DocViewerDialog("t", tmp_path / "missing.md", theme=runtime)
        qtbot.addWidget(dlg)
        edit = dlg.findChild(QPlainTextEdit)
        dlg.show()
        qtbot.waitExposed(dlg)
        assert "Menlo" in edit.font().families()
        assert runtime.toggle() is True
        # Live: the current theme's family is in effect at the next polish.
        assert "Monaco" in edit.font().families()
