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


# ── detail_panel: neutral tint + off-skin list-model rows ──────────────────

def test_rating_tint_is_transparent_with_invalid_endpoints():
    from app.presentation.theme.rating import rating_to_color

    assert rating_to_color(10, _BrokenRatingRuntime()).alpha() == 0


def test_offskin_detail_row_has_transparent_tint():
    from types import SimpleNamespace
    from app.presentation.viewmodels.detail_panel_view_model import DetailRowsModel

    model = DetailRowsModel(runtime=None)
    model.set_entities(
        [SimpleNamespace(id=1, name="Имя", rating=1, description=None)],
        "organization",
    )
    tint = model.data(model.index(0, 0), DetailRowsModel.RatingTintRole)
    assert tint == "#00000000"


# ── image_viewer_dialog: themed attach (lines 87–88) ───────────────────────

def test_image_viewer_with_theme_attaches_the_chrome_sheet(qtbot, runtime):
    from PySide6.QtGui import QPixmap

    from app.presentation.views.image_viewer_dialog import ImageViewerDialog

    dlg = ImageViewerDialog(QPixmap(10, 10), theme=runtime)
    qtbot.addWidget(dlg)
    # The dialog's own context, never the shared engine root: names written
    # there are one global slot, nulled for every live island when this
    # short-lived viewer dies.
    assert dlg._context.contextProperty("imageViewerVm") is dlg.vm
    assert dlg._engine.rootContext().contextProperty("imageViewerVm") is None


# ── doc viewer with no usable theme ───────────────────────────────────────

def test_doc_viewer_survives_broken_default_theme(qtbot, tmp_path, monkeypatch):
    from app.presentation.views.doc_viewer_dialog import DocViewerDialog
    import app.presentation.views.doc_viewer_dialog as doc_mod

    def boom():
        raise RuntimeError("no usable theme in this test")

    monkeypatch.setattr(doc_mod, "get_default_theme", boom)
    doc = tmp_path / "doc.md"
    doc.write_text("текст документа", encoding="utf-8")
    dlg = DocViewerDialog("Doc", doc, theme=None)
    qtbot.addWidget(dlg)
    assert dlg.vm.text == "текст документа"


# ── world_snapshot_widget: off-skin retheme remains transparent ─────────────

def test_world_snapshot_offskin_retheme_is_safe(qtbot):
    from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

    widget = WorldSnapshotWidget(theme=None)
    qtbot.addWidget(widget)
    widget.vm._on_theme_changed()
    assert widget.vm.rowModel.rowCount() == 0
