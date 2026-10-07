"""SheetFrame — the widget-side sheet container (NRI-0024 task 1.1, design Д1).

The behavioral half of the sheet contract, pinned identically for both
harnesses (spec modal-sheets «Лист различим в стеке любой глубины»): the
header names the sheet with exactly the windowTitle text, and the header
button closes with the same cancel outcome Esc performs — one path through
``QDialog.reject``, both routes asserted equal, not just present.

The отступы pin is the widget twin of ThemeSheetHeader.qml: title at
``space.md`` from the left, close at ``space.md`` from the right, the row
breathed by ``space.sm`` vertically — the very tokens.json numbers the QML
resolves through Tokens.px; an off-skin frame (design D7, and a bare frame
without any runtime) keeps the token's own numbers, never a crash.

The scrim is the SheetFrame's answer to the islands' sheetScrim layer: the
palette's color.scrim material (the SCRIM_COLOR source qml_palette ships to
QML, imported here rather than invented again) painted over the whole frame,
mouse-transparent so the dim never traps the sheet's own input.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from app.presentation.theme.qml_palette import SCRIM_COLOR
from app.presentation.views.sheet_frame import SheetFrame


def _runtime(tmp_path, *, broken: bool = False):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    tokens_path = tokens_file_path()
    if broken:
        tokens_path = tmp_path / "tokens.json"
        tokens_path.write_text("{not json", encoding="utf-8")
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_path
    )


def _close_button(frame: SheetFrame) -> QPushButton:
    return frame.findChild(QPushButton, "sheetFrameCloseButton")


def _title_label(frame: SheetFrame) -> QLabel:
    return frame.findChild(QLabel, "sheetFrameTitle")


def _scrim(frame: SheetFrame):
    return frame.findChild(type(frame._scrim), "sheetFrameScrim")


def test_header_names_the_sheet_with_the_window_title(qtbot):
    """The header text corresponds to windowTitle, and stays threaded."""
    frame = SheetFrame("Просмотр изображения")
    qtbot.addWidget(frame)
    assert frame.windowTitle() == "Просмотр изображения"
    assert _title_label(frame).text() == "Просмотр изображения"

    frame.setWindowTitle("Changelog")  # later renames ride the same value
    assert _title_label(frame).text() == "Changelog"


def test_close_button_and_escape_share_the_reject_outcome(qtbot):
    """«Закрыть» performs exactly the Esc action (spec: «как Esc»).

    Two identical frames: one leaves through the header button, one through
    the Escape key — the observable outcomes (closed, result == Rejected)
    must be equal, so the sheet can never cancel differently per route.
    """
    by_button = SheetFrame("Лист", None)
    by_escape = SheetFrame("Лист", None)
    qtbot.addWidget(by_button)
    qtbot.addWidget(by_escape)

    by_button.show()
    _close_button(by_button).click()
    assert not by_button.isVisible()
    assert by_button.result() == by_button.DialogCode.Rejected

    by_escape.show()
    QTest.keyClick(by_escape, Qt.Key.Key_Escape)
    assert not by_escape.isVisible()
    assert by_escape.result() == by_button.result()


class _EscapeEater(QWidget):
    """A content widget that CONSUMES Escape (PR-005).

    Live face of the defect: the docs sheet's content is a QQuickWidget island,
    and on the real cocoa display the island's offscreen QQuickWindow accepts
    the Escape (instrumented proof: «key-> QQuickWindow(...) → accepted=True»,
    the event never climbs to the dialog) — so the sheet stayed open. Offscreen
    a QQuickWidget forwards the ignored key upward, so the pin models the same
    observable with a plain widget: focus sits on a child that eats Escape.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ate_escape = False

    def keyPressEvent(self, event):  # noqa: N802 — Qt API
        if event.key() == Qt.Key.Key_Escape:
            self.ate_escape = True
            event.accept()
            return
        super().keyPressEvent(event)


def test_escape_reaches_the_sheet_even_when_the_content_eats_it(qtbot):
    """PR-005: the sheet's Esc result is the frame's own, never the content's
    favour. «Закрыть» = Esc = QDialog.reject (spec «как Esc»), and the route
    must survive a content widget that consumes the key — the live island sheet
    stayed open because QDialog::keyPressEvent only runs on a key that arrives.
    """
    frame = SheetFrame("Changelog")
    qtbot.addWidget(frame)
    eater = _EscapeEater(frame)
    frame.add_content(eater)
    frame.show()
    qtbot.waitExposed(frame)
    frame.activateWindow()
    qtbot.waitUntil(lambda: frame.isActiveWindow(), timeout=2000)
    eater.setFocus()
    assert frame.focusWidget() is eater

    # The frame's filter answers ONLY Escape: any other key rides to the
    # content untouched (the island keeps its own PageUp/PageDown contract).
    QTest.keyClick(frame.windowHandle(), Qt.Key.Key_PageDown)
    assert frame.isVisible()
    assert eater.ate_escape is False

    QTest.keyClick(frame.windowHandle(), Qt.Key.Key_Escape)

    assert not frame.isVisible()  # the sheet's cancel never depends on the content
    assert frame.result() == frame.DialogCode.Rejected


def test_content_slot_seats_its_widget_below_the_header(qtbot):
    frame = SheetFrame("Стол")
    qtbot.addWidget(frame)
    body = QLabel("посадка")
    frame.add_content(body)

    assert body.parent() is frame.content_layout.parentWidget()
    assert frame.content_layout.indexOf(body) == 0
    frame.resize(480, 360)
    frame.show()
    # The slot lives under the title row, not on top of it.
    title = _title_label(frame)
    header_bottom = title.mapTo(frame, title.rect().bottomLeft()).y()
    content_top = body.mapTo(frame, body.rect().topLeft()).y()
    assert content_top >= header_bottom


def test_header_wears_the_space_tokens_the_qml_header_uses(qtbot, tmp_path):
    """The row margins equal ThemeSheetHeader's отступы: space.md flanking,
    space.sm vertical (the tokens.json numbers the QML reads)."""
    frame = SheetFrame("Документация", theme=_runtime(tmp_path))
    qtbot.addWidget(frame)
    row = frame.findChild(QLabel, "sheetFrameTitle").parent().layout()
    margins = row.contentsMargins()
    assert (margins.left(), margins.right()) == (16, 16)  # space.md
    assert (margins.top(), margins.bottom()) == (8, 8)  # space.sm


def test_off_skin_frames_keep_the_token_numbers(qtbot, tmp_path):
    """D7 degradation for the new chrome: no runtime at all, and a runtime
    whose tokens are invalid — the margins fall back to the token's own
    numbers (16/8), the frame still builds its header, title and close."""
    bare = SheetFrame("Стол")  # no theme
    invalid = SheetFrame("Стол", theme=_runtime(tmp_path, broken=True))
    qtbot.addWidget(bare)
    qtbot.addWidget(invalid)

    for frame in (bare, invalid):
        row = _title_label(frame).parent().layout().contentsMargins()
        assert (row.left(), row.right(), row.top(), row.bottom()) == (16, 16, 8, 8)
        assert _close_button(frame) is not None


def test_scrim_is_the_palette_dim_crowning_the_whole_frame(qtbot):
    """The stack dim of a widget sheet: color.scrim (SCRIM_COLOR, the same
    source the islands' palette hands QML) over the whole surface; it crowns
    the content when raised, hides at zero, follows resizes, and the frame
    answers the sheet duck the connector dims through."""
    frame = SheetFrame("Документация")
    qtbot.addWidget(frame)
    frame.resize(420, 300)
    frame.show()
    qtbot.waitExposed(frame)
    scrim = _scrim(frame)

    # Duck contract: the connector hands alphas, never layer counts.
    assert frame.sheet_scrim_alpha == 0.0
    assert not scrim.isVisible()

    opaque_before = frame.grab().toImage().pixelColor(210, 150)
    assert opaque_before.getRgb() != (0, 0, 0, 255)  # zero alpha: the canvas is whole
    frame.set_sheet_scrim_alpha(1.0)
    assert frame.sheet_scrim_alpha == 1.0
    assert scrim.isVisible()
    assert scrim.geometry() == frame.rect()

    opaque_after = frame.grab().toImage().pixelColor(210, 150)
    assert opaque_after.getRgb() == (0, 0, 0, 255)  # SCRIM_COLOR verbatim
    assert SCRIM_COLOR == "#000000"

    # The dim is paint, not a mouse trap: a real click aimed at the close
    # goes through the layer and performs the cancel (EventDialogRoot's
    # rule). The route is the frame's QWindow — the spontaneous route Qt's
    # own mouse-receiver pick sees, where a WA_TransparentForMouseEvents
    # overlay is skipped and the hit lands on the button under it. The
    # QWidget overload of QTest.mouseClick would deliver straight to the
    # widget it is given (no child picking on the offscreen build), which
    # could never prove the dim passes hits through. The frame is top-level,
    # so frame coordinates are window coordinates here.
    close = _close_button(frame)
    QTest.mouseClick(
        frame.windowHandle(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        close.mapTo(frame, close.rect().center()),
    )
    qtbot.waitUntil(lambda: not frame.isVisible())

    # The layer tracks the sheet's size (a sheet grows with the window).
    reopened = SheetFrame("Документация")
    qtbot.addWidget(reopened)
    reopened.show()
    reopened.set_sheet_scrim_alpha(0.5)
    reopened.resize(500, 380)
    assert _scrim(reopened).geometry() == reopened.rect()
    assert pytest.approx(reopened.sheet_scrim_alpha) == 0.5


# ── the sheet edge (live defect, 2026-10-02): no foreign strip above the header ──
#
# The norm the island sheets have carried since NRI-0014 (the corner pin in
# tests/presentation/test_sheet_header_dialogs.py) is that a sheet's own edge
# pixel is the sheet canvas — ``color.bg.surface``, the background every QML
# island sheet shows. The widget-side sheet broke it: the frame attached the
# catalog's WINDOW canvas (``color.bg.canvas``), the header QWidget paints no
# fill of its own, and the island content underneath keeps the sheet surface —
# so the whole header row read as a full-width dark strip at the top of every
# SheetFrame sheet (measured dark grab of «Настройка LLM…»: rows 0-40 #1e1e24,
# from the content on #2a2a32). The three tests below pin the repaired edge:
# the widget branch, the island branch, and the one-place guard for the cause.


def _sheet_edge_probe(frame, qtbot, theme: str) -> None:
    """Show ``frame`` and demand a homogeneous sheet canvas down its whole
    header row: from the first device pixel of the window, across the width,
    and along the caption line — the strip a user reads as «полоса над
    заголовком» would land exactly on these probes."""
    from tests.ui.test_theme_grab import token_color

    surface = token_color("color.bg.surface", theme)
    canvas = token_color("color.bg.canvas", theme)
    assert surface != canvas  # the two backgrounds must be tellable apart

    frame.resize(520, 380)
    frame.show()
    qtbot.waitExposed(frame)
    image = frame.grab().toImage()
    header = frame.header
    caption_y = header.mapTo(frame, header.rect().center()).y()
    xs = (0, 1, 4, image.width() // 2, image.width() - 2)
    for y in (0, 1, caption_y):
        for x in xs:
            assert image.pixelColor(x, y) == surface, (theme, x, y)
    # The seam between chrome and content is invisible: the same token above
    # the header and under it.
    seam = header.mapTo(frame, header.rect().bottomLeft()).y()
    assert image.pixelColor(4, seam + 4) == surface, (theme, seam)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_widget_sheet_edge_is_the_sheet_surface_from_the_top(qtbot, tmp_path, theme):
    """SheetFrame branch: a bare widget sheet carries the sheet canvas from
    its first pixel, so its own header row is no longer a darker band."""
    from tests.ui.test_theme_grab import make_runtime

    frame = SheetFrame("Стол", theme=make_runtime(tmp_path, theme))
    qtbot.addWidget(frame)
    _sheet_edge_probe(frame, qtbot, theme)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_island_sheet_edge_is_the_sheet_surface_from_the_top(qtbot, tmp_path, theme):
    """Island-in-SheetFrame branch («Настройка LLM…»): the island's surface and
    the widget chrome now answer one token, so the seam at the header's bottom
    edge cannot show."""
    from app.infrastructure.llm.config import LlmConfig
    from app.presentation.views.llm_setup_dialog import LlmSetupDialog
    from tests.ui.test_theme_grab import make_runtime

    dlg = LlmSetupDialog(LlmConfig(base_url="http://x", model="m"),
                         theme=make_runtime(tmp_path, theme))
    qtbot.addWidget(dlg)
    _sheet_edge_probe(dlg, qtbot, theme)
    # The island really is the content here (non-vacuity for the seam probe):
    # its first row is the same token the chrome now wears.
    dlg.resize(520, 380)
    dlg.show()
    qtbot.waitExposed(dlg)
    image = dlg.grab().toImage()
    from tests.ui.test_theme_grab import token_color

    assert image.pixelColor(4, dlg.header.height() + 4) == token_color(
        "color.bg.surface", theme
    )


def test_the_sheet_canvas_lives_in_exactly_one_rule_and_one_call_site(tmp_path):
    """One knowledge, one place: the sheet canvas is the catalog's modifier
    (``uiSheet``) read by exactly one compiled rule, stamped by exactly one
    container — the frame every widget sheet rides."""
    from app.presentation.views import sheet_frame as sheet_frame_module

    frame = SheetFrame("Документация", theme=_runtime(tmp_path))
    assert frame.property("uiSheet") == "true"
    assert _runtime(tmp_path).qss().count("uiSheet") == 1

    views_dir = Path(sheet_frame_module.__file__).parent
    callers = sorted(
        path.name for path in views_dir.rglob("*.py")
        if "sheet=True" in path.read_text(encoding="utf-8")
    )
    assert callers == ["sheet_frame.py"]
