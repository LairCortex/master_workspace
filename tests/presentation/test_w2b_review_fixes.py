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

from PySide6.QtGui import QColor

from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from tests.presentation.qml_helpers import find_item


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


# ── detail_panel: clear() empties the stable QML list models ───────────────

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

    def test_fill_populates_stable_models(self, tmp_path, qtbot):
        panel = self._panel(tmp_path, qtbot)
        assert [model.rowCount() for model in panel.vm.models] == [1, 1, 0, 0]

    def test_clear_empties_models_immediately(self, tmp_path, qtbot, qapp):
        panel = self._panel(tmp_path, qtbot)
        panel.clear()
        qapp.processEvents()
        assert [model.rowCount() for model in panel.vm.models] == [0, 0, 0, 0]

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

        roles = {
            name.decode(): role
            for role, name in widget.vm.rowModel.roleNames().items()
        }

        def entity_color():
            for index in range(widget.vm.rowModel.rowCount()):
                model_index = widget.vm.rowModel.index(index, 0)
                if (
                    widget.vm.rowModel.data(model_index, roles["rowKind"])
                    == "entityRow"
                    and widget.vm.rowModel.data(model_index, roles["type"])
                    == "character"
                ):
                    return QColor(
                        widget.vm.rowModel.data(model_index, roles["ratingHex"])
                    )
            raise AssertionError("entity row missing")

        dark = QColor(runtime.tokens["color.rating.high"]["dark"])
        dark.setAlpha(220)
        assert entity_color().getRgb() == dark.getRgb()

        assert runtime.toggle() is True
        light = QColor("#ff0000")
        light.setAlpha(220)
        assert entity_color().getRgb() == light.getRgb()

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
        assert widget.vm.rowModel.rowCount()
        widget._on_clear()
        assert widget.vm.rowModel.rowCount() == 0
        assert runtime.toggle() is True  # no stale nodes to touch


# ── search_bar: header brushes follow the theme ────────────────────────────

class TestSearchHeaderLiveRetheme:
    def test_header_recolors_after_toggle(self, tmp_path, qtbot):
        from app.presentation.views.search_bar import SearchBar
        runtime = _runtime(
            tmp_path,
            **{"color.border": {"light": "#101010", "dark": "#efefef"}},
        )
        vm = SearchViewModel(None)
        bar = SearchBar(vm, theme=runtime)
        qtbot.addWidget(bar)
        vm.results = {"characters": [_entity(3)]}
        vm.setQuery("E3")
        vm._publish_results()
        header = find_item(bar.quick, "searchSectionHeader")
        before = QColor(header.property("color"))
        assert before == QColor("#efefef")
        assert runtime.toggle() is True
        assert QColor(header.property("color")) == QColor("#101010")

    def test_unparsable_border_token_paints_nothing(self, tmp_path, qtbot):
        """A border token Qt cannot parse leaves the header uncoloured —
        ``QColor`` would hand back an invalid (black-rendering) color, and an
        invented black is exactly what D7 forbids."""
        from app.presentation.views.search_bar import SearchBar

        runtime = _runtime(
            tmp_path,
            **{"color.border": {"light": "#101010", "dark": "не-цвет"}},
        )

        vm = SearchViewModel(None)
        bar = SearchBar(vm, theme=runtime)
        qtbot.addWidget(bar)
        vm.results = {"characters": [_entity(3)]}
        vm.setQuery("E3")
        vm._publish_results()
        header = find_item(bar.quick, "searchSectionHeader")
        assert not QColor(header.property("color")).isValid()
        # The load-time contract still holds: the other theme's valid value
        # colors the header again after a live switch.
        assert runtime.toggle() is True
        assert QColor(header.property("color")) == QColor("#101010")


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

        panel = DetailPanel(SimpleNamespace(), theme=runtime)
        bar = SearchBar(SearchViewModel(None), theme=runtime)
        snapshot = WorldSnapshotWidget(theme=runtime)
        qtbot.addWidget(panel)
        qtbot.addWidget(bar)
        qtbot.addWidget(snapshot)

        callbacks = {
            panel.vm.retheme,
            snapshot.vm._on_theme_changed,
        }
        assert callbacks <= set(runtime.subscribers)
        assert bar._palette._runtime is runtime


# ── doc viewer: chrome-attached mono comes from the QSS rule, not setFont ──

class TestDocViewerMonoLive:
    def test_attached_mono_follows_token(self, tmp_path, qtbot):
        from app.presentation.views.main_window import _DocViewerDialog
        from tests.presentation.qml_helpers import find_item

        runtime = _runtime(
            tmp_path,
            **{"font.family.mono": {
                "light": "Monaco, monospace", "dark": "Menlo, monospace",
            }},
        )
        dlg = _DocViewerDialog("t", tmp_path / "missing.md", theme=runtime)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)
        area = find_item(dlg.quick, "docText")
        assert "Menlo" in area.property("font").family()
        assert runtime.toggle() is True

        def monaco() -> bool:
            return "Monaco" in find_item(dlg.quick, "docText").property("font").family()

        qtbot.waitUntil(monaco, timeout=5000)
