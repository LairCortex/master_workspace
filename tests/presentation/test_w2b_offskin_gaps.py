"""Off-skin and defensive-branch fillers for the W2b themed views (D7).

Every test drives a guard no UI flow reaches on its own: unparsable token
pass-through, off-skin paint/refresh short-circuits, and retheme loops that
must survive widgets whose C++ side died. These are the branches the CI
100% coverage gate counts; behavior asserted is the documented D7 contract
(no invented colors off-skin), never new semantics.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime


@pytest.fixture
def runtime(tmp_path):
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )


class _BrokenRatingRuntime:
    """Runtime-shaped stub whose rating token endpoints are unparsable."""

    is_valid = True
    theme = "dark"
    tokens = {
        "color.rating.low": {"dark": "bogus-low"},
        "color.rating.high": {"dark": "bogus-high"},
    }


class _BadAccentRuntime:
    """Runtime-shaped stub that only carries an unparsable accent token."""

    is_valid = True
    theme = "dark"
    tokens = {"color.accent": {"dark": "definitely-not-a-color"}}

    def add_listener(self, listener) -> None:  # noqa: D102 — stub contract
        pass


class _DeadWrapper:
    """Stand-in for an item wrapper whose C++ side is already deleted."""

    def retheme(self) -> None:
        raise RuntimeError("wrapped C++ object has been deleted")


class _DeadNode:
    """Stand-in for a tree node removed from the tree since populate."""

    def setBackground(self, *args) -> None:  # noqa: N802
        raise RuntimeError("wrapped C++ object has been deleted")


# ── ai_assist_button: _rgba pass-through (line 37) ─────────────────────────

def test_unparsable_token_value_is_passed_through_verbatim():
    from app.presentation.views.ai_assist_button import _rgba

    assert _rgba("bogus-color", 0.5) == "bogus-color"


# ── detail_panel: rating tint + off-skin paint + dead-wrapper loop ─────────

def test_rating_tint_is_transparent_with_invalid_endpoints():
    from app.presentation.views.detail_panel import rating_to_color

    assert rating_to_color(10, _BrokenRatingRuntime()).alpha() == 0


def test_offskin_entity_item_paints_no_tint(qtbot):
    from app.presentation.views.detail_panel import _EntityItemWidget

    widget = _EntityItemWidget("Имя", "краткое описание", rating=1, runtime=None)
    qtbot.addWidget(widget)
    widget.resize(220, 60)
    assert widget._bg_color.alpha() == 0  # D7: no invented color off-skin
    widget.grab()  # paintEvent must take the alpha==0 early return


def test_detail_panel_retheme_loop_drops_dead_wrappers(qtbot):
    from app.presentation.views.detail_panel import DetailPanel

    panel = DetailPanel(detail_vm=MagicMock(), theme=None)
    qtbot.addWidget(panel)
    survivor = MagicMock()
    dead = _DeadWrapper()
    panel._item_widgets = [survivor, dead]
    panel._on_theme_changed()
    assert panel._item_widgets == [survivor]  # dead wrapper pruned, loop done


# ── image_viewer_dialog: themed attach (lines 87–88) ───────────────────────

def test_image_viewer_with_theme_attaches_the_chrome_sheet(qtbot, runtime):
    from PySide6.QtGui import QPixmap

    from app.presentation.views.image_viewer_dialog import ImageViewerDialog

    dlg = ImageViewerDialog(QPixmap(10, 10), theme=runtime)
    qtbot.addWidget(dlg)
    assert 'uiRole="chrome"' in dlg.chrome.styleSheet()


# ── main_window: doc viewer with no usable theme (lines 92–93) ─────────────

def test_doc_viewer_survives_broken_default_theme(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPlainTextEdit

    from app.presentation.views import main_window as main_window_module
    from app.presentation.views.main_window import _DocViewerDialog

    def boom():
        raise RuntimeError("no usable theme in this test")

    monkeypatch.setattr(main_window_module, "get_default_theme", boom)
    doc = tmp_path / "doc.md"
    doc.write_text("текст документа", encoding="utf-8")
    dlg = _DocViewerDialog("Doc", doc, theme=None)
    qtbot.addWidget(dlg)
    edit = dlg.findChild(QPlainTextEdit)
    assert edit.toPlainText() == "текст документа"


# ── mention_text_edit: refresh_content guards (lines 229, 232) ─────────────

def test_refresh_content_offskin_is_noop(qtbot):
    from app.presentation.views.mention_text_edit import MentionTextEdit

    edit = MentionTextEdit()
    qtbot.addWidget(edit)
    edit.setContent("@Имя и текст")
    edit.refresh_content()  # theme None → early return, no anchors changed


def test_refresh_content_with_invalid_accent_is_noop(qtbot):
    from app.presentation.views.mention_text_edit import MentionTextEdit

    edit = MentionTextEdit(theme=_BadAccentRuntime())
    qtbot.addWidget(edit)
    edit.setContent("@Имя и текст")
    before = edit.document().toHtml()
    edit.refresh_content()  # accent unparsable → early return before pass 1
    assert edit.document().toHtml() == before


# ── world_snapshot_widget: dead-node prune (lines 105–106) ─────────────────

def test_world_snapshot_retheme_drops_dead_nodes(qtbot):
    from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

    widget = WorldSnapshotWidget(theme=None)
    qtbot.addWidget(widget)
    widget._rated_nodes = [(_DeadNode(), 5)]
    widget._on_theme_changed()
    assert widget._rated_nodes == []
