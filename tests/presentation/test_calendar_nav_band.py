"""NRI-0018 group 6 — the calendar navigation row: one 32 px band, era check themed.

Pins the two deltas the live review asked for (NRI-0018 Д8, specs
game-calendar-grid «Строка навигации — единая полоса высот» /
«Оформление сетки именованными классами», ui-widget-catalog «Нативные
индикаторы проверки тематизируются»):

* the row «◀ month | year spin ▶ ☐ до н.э.» sits on ONE band — every control
  is exactly 32 px tall and all five share the row's vertical centre;
* the era checkbox is a STYLE-FACING class (``GameCalendarEraCheck``) whose
  ``::indicator`` block in the generated popup sheet comes from the semantic
  tokens, so no white native OS cell survives on the dark grid. The sync of
  the class name with the sheet is pinned from BOTH sides (rename either one
  and the pair test fails);
* off-skin the sheet is never applied, so the checkbox stays native and
  clickable — no invented colors (ui-widget-catalog «Off-skin не ломается»).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme.compiler import (
    compile_popup_qss,
    load_tokens,
    tokens_file_path,
)
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.views import calendar_grid as calendar_grid_module
from app.presentation.views.calendar_grid import (
    GameCalendarEraCheck,
    GameCalendarGrid,
)

# The row gauge of spec «Строка навигации — единая полоса высот».
BAND = 32

# Every STYLE-FACING name of the grid + its popup-sheet rules. The pair test
# below reads them from BOTH sides: a class renamed in the module or a selector
# renamed in the compiler breaks the same assertion (design D8's «rename only
# together with the sheet», now guarded instead of commented).
STYLE_FACING_GRID_CLASSES = (
    "GameCalendarGrid",
    "GameCalendarCell",
    "GameCalendarIntercalaryChip",
    "GameCalendarDayName",
    "GameCalendarEraCheck",
)


@pytest.fixture
def tokens():
    parsed = load_tokens(tokens_file_path())
    assert parsed is not None
    return parsed


def _shown_grid(**kwargs) -> GameCalendarGrid:
    grid = GameCalendarGrid(**kwargs)
    grid.show()
    QApplication.processEvents()
    return grid


def _centre_y_in(grid: GameCalendarGrid, widget) -> int:
    """Vertical centre of ``widget`` in the grid's coordinate space."""
    return widget.mapTo(
        grid, QPoint(widget.width() // 2, widget.height() // 2)
    ).y()


def _nav_controls(grid: GameCalendarGrid):
    return (
        grid._prev_btn,
        grid._month_combo,
        grid._year_spin,
        grid._next_btn,
        grid._bc_check,
    )


# ── 6.1 — the row stands on one 32 px band ───────────────────────────────────


def test_nav_row_controls_are_pinned_to_the_band(qtbot):
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    # The heights are the widgets' own fixed contract, not a happy sizeHint:
    # each control is clamped to the band on both ends (Д8: стрелки 28→32,
    # setFixedHeight for combo/spinner/checkbox).
    for control in _nav_controls(grid):
        assert (control.minimumHeight(), control.maximumHeight()) == (BAND, BAND), control
    for arrow in (grid._prev_btn, grid._next_btn):
        assert (arrow.minimumWidth(), arrow.maximumWidth()) == (BAND, BAND)


def test_nav_row_controls_share_the_vertical_centre(qtbot):
    grid = _shown_grid()
    qtbot.addWidget(grid)
    centres = [_centre_y_in(grid, control) for control in _nav_controls(grid)]
    for control, centre in zip(_nav_controls(grid), centres):
        assert control.height() == BAND, control
    assert max(centres) - min(centres) <= 1, centres


def test_preview_nav_row_keeps_the_band_without_the_era_flag(qtbot):
    # The wizard's live preview hides the era box (show_era=False) but the
    # remaining row still stands on one band (ui-layout-grid «Ряд строки дат»).
    grid = _shown_grid(interactive=False, show_era=False)
    qtbot.addWidget(grid)
    visible = [c for c in _nav_controls(grid) if c.isVisibleTo(grid)]
    assert grid._bc_check not in visible
    assert len(visible) == 4
    centres = [_centre_y_in(grid, control) for control in visible]
    assert all(c.height() == BAND for c in visible)
    assert max(centres) - min(centres) <= 1, centres


# ── 6.1 — the sheet themes the era checkbox; the class name is pinned ────────


def test_era_check_is_the_named_style_facing_class(qtbot):
    grid = GameCalendarGrid()
    qtbot.addWidget(grid)
    assert isinstance(grid._bc_check, GameCalendarEraCheck)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_popup_sheet_themes_the_era_indicator_from_tokens(tokens, theme):
    sheet = compile_popup_qss(tokens, theme)

    caption = re.search(r"GameCalendarEraCheck\s*\{([^}]*)\}", sheet)
    assert caption, "в листе попапов нет правила подписи чекбокса эры"
    assert f"color: {tokens['color.fg.primary'][theme]};" in caption.group(1)

    box = re.search(r"GameCalendarEraCheck::indicator\s*\{([^}]*)\}", sheet)
    assert box, "в листе попапов нет правила ::indicator чекбокса эры"
    rule = box.group(1)
    assert "width: 16px;" in rule
    assert "height: 16px;" in rule
    assert f"border: 1px solid {tokens['color.border'][theme]};" in rule
    assert f"border-radius: {tokens['radius.sm'][theme]};" in rule
    assert f"background: {tokens['color.bg.canvas'][theme]};" in rule

    checked = re.search(
        r"GameCalendarEraCheck::indicator:checked\s*\{([^}]*)\}", sheet
    )
    assert checked, "выбранное состояние индикатора эры не тематизировано"
    assert tokens["color.accent"][theme] in checked.group(1)


def test_popup_sheet_carries_no_generic_checkbox_rule(tokens):
    # The app-wide sheet reaches every widget, so the era indicator is
    # addressed through the grid's own class name only; a generic QCheckBox
    # rule would repaint EVERY checkbox of the process (W2a D2).
    sheet = compile_popup_qss(tokens, "dark")
    assert "QCheckBox" not in sheet


def test_style_facing_class_names_survive_only_in_synchronized_edits():
    # «Переименование style-facing классов вне синхронной правки листа SHALL
    # ловиться тестом темы» — both directions at once: every name is a class
    # in the module AND a selector in the generated sheet.
    source = Path(calendar_grid_module.__file__).read_text(encoding="utf-8")
    sheet = compile_popup_qss(load_tokens(tokens_file_path()), "dark")
    for name in STYLE_FACING_GRID_CLASSES:
        assert f"class {name}(" in source, f"класс {name} переименован в модуле"
        assert name in sheet, f"селектор {name} пропал из листа попапов"


# ── 6.2 pin — off-skin stays native (ui-widget-catalog «Off-skin не ломается») ─


def test_off_skin_sheet_is_not_applied_so_the_era_check_stays_native(
    qtbot, tmp_path, qapp
):
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad
    )
    assert runtime.is_valid is False
    assert runtime.popup_qss() == ""  # nothing to apply — D7, off-skin

    qapp.setStyleSheet("QToolTip { color: #123456; }")  # stale foreign sheet
    try:
        runtime.attach_app(qapp)
        runtime.apply()
        assert qapp.styleSheet() == ""  # cleared, never half-applied
        grid = GameCalendarGrid()
        qtbot.addWidget(grid)
        grid._bc_check.click()  # native widget, still clickable
        assert grid.is_bc() is True
    finally:
        qapp.setStyleSheet("")
