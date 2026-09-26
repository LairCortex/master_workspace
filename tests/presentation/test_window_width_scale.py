"""NRI-0018 task 5.1 (spec ui-layout-grid «Естественная ширина окна берётся
из шкалы кратной 40», «Отступ содержимого листов задан единым токеном»).

Every window and sheet of the app lives on a width scale of 40 px steps and
never opens narrower than its own content; the QML island's ``implicitWidth``
and the Python floor/resize of its facade are the two halves of the same
step and move together (design Д6). This file is the table pin: one row per
window, target from the spec's window table, both halves measured on the
live objects offscreen — the two ``Math.max`` content floors (sheet list,
card) are additionally pinned at their literal because their content may
lawfully exceed the floor (spec: «ширина поднимается к ближайшей ступени
вверх»), so only the floor constant is observable in the source.

Task 5.3 adds the token part: the two exceptions (search bar's 4 px, doc
viewer's 8 px) now inset their content by the shared sheet token ``space.md``
(16 px), the same offset the event sheet uses — measured, not grepped.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog

from app.application.services.calendar_settings_service import CalendarSettingsService
from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import CharacterSheetService
from app.application.services.table_host_service import TableHostService
from app.infrastructure.db.uow import GameSessionUoW
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation import qml as qml_shell
from app.presentation.layout_grid import ceil_to_width_step
from app.presentation.theme import get_default_theme
from tests.presentation.qml_helpers import find_item

#: The one step of the ui-layout-grid width scale.
STEP = 40

#: Spec target table (window → natural width). «карточка 760» is the card's
#: with-image floor, the live-audit width of the card (the without-image
#: floor is not a window from the table and stays the design's, 550).
TARGETS = {
    "sheet-list": 440,
    "table-panel": 440,
    "launcher": 480,
    "preset": 560,
    "llm-setup": 640,
    "xlsx-import": 640,
    "event": 720,
    "image-viewer": 720,
    "doc-viewer": 720,
    "card-floor": 760,
    # «мастер календаря» left the static literal rows: Д7 recounts its floor
    # from the column sum (measured here: 1040, the spec table's row the owner
    # synced on 2026-09-26) — the pin below keeps it on the step without a
    # literal the platform's font metrics could push off.
    "sheet-fill": 1120,
    "sheet-editor": 1280,
}

#: The shared sheet content-inset token (space.md) per tokens.json.
SHEET_MARGIN_PX = 16


def _qml_text(name: str) -> str:
    return (Path(qml_shell.__file__).resolve().parent / name).read_text(
        encoding="utf-8"
    )


def _imp_width(dlg: QDialog) -> int:
    return int(round(dlg._root.implicitWidth()))


@pytest.fixture
def service(async_session):
    return CharacterSheetService(CharacterSheetRepository(async_session))


@pytest.fixture
def sheets(async_session):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    return sheet_svc, inst_svc


# ── the scale itself ─────────────────────────────────────────────────────────


def test_every_target_is_a_step_of_the_scale():
    assert all(width % STEP == 0 for width in TARGETS.values())


def test_the_step_lives_in_one_module():
    """AGENTS «одно знание — одно место» for the scale: the constant and the
    climb live exactly once (OBS-2 close added a second consumer, the shared
    island sizer — this guard stops a third private copy from appearing)."""
    from app.presentation import layout_grid
    from app.presentation.qml import island_size
    from app.presentation.views import calendar_wizard

    assert layout_grid.WIDTH_STEP == STEP
    assert callable(layout_grid.ceil_to_width_step)
    # Both scale consumers ride the shared module rather than a local rule.
    assert island_size.ceil_to_width_step is layout_grid.ceil_to_width_step
    assert calendar_wizard.ceil_to_width_step is layout_grid.ceil_to_width_step
    assert not hasattr(calendar_wizard, "WIDTH_STEP")
    assert not hasattr(calendar_wizard, "_ceil_to_step")


@pytest.mark.parametrize(
    ("value", "climbed"),
    [
        (817, 840),  # the live entity card (OBS-2's card shape)
        (620, 640),  # the live sheet list (OBS-2's list shape)
        (840, 840),  # an exact step is left exactly there (no dead void)
        (0, 0),
        (1, 40),
        (839.7, 840),  # a fractional ask climbs on the rounded-up step
    ],
)
def test_ceil_climbs_values_to_the_nearest_step_upwards(value, climbed):
    """Spec «при несовместимости шкалы и содержимого ширина SHALL подниматься
    к ближайшей ступени вверх», and the opposite half of the scenario: the
    content already on a step opens on exactly that step."""
    from app.presentation.layout_grid import ceil_to_width_step

    assert ceil_to_width_step(value) == climbed


def _scaled_open(asked_w: int, floor_w: int, cap_w: int) -> int:
    """The width the shared sizer ends the window at: the ask (floored, then
    climbed to the step when above the floor — OBS-2 close) screen-capped;
    Qt lifts whatever the cap left back to the window's own minimum."""
    return max(floor_w, min(ceil_to_width_step(asked_w), cap_w))


# ── one row per window: the two halves on the live objects ──────────────────


def test_table_panel_opens_on_the_step(qtbot):
    from app.presentation.views.table_host.panel import TableHostPanel

    host = TableHostService(MagicMock(), MagicMock())
    panel = TableHostPanel(host, list_ipv4=lambda: ["10.0.0.2"])
    qtbot.addWidget(panel)

    assert panel.size().width() == TARGETS["table-panel"]


def test_launcher_pair_on_the_step(qtbot):
    from app.presentation.views.game_launcher_dialog import GameLauncherDialog

    dlg = GameLauncherDialog(theme=get_default_theme())
    qtbot.addWidget(dlg)

    assert dlg.minimumWidth() == TARGETS["launcher"]
    assert _imp_width(dlg) == TARGETS["launcher"]


def test_preset_pair_on_the_step(qtbot, service):
    from app.presentation.views.character_sheet.preset_dialog import (
        CharacterSheetPresetDialog,
    )

    dlg = CharacterSheetPresetDialog(service)
    qtbot.addWidget(dlg)

    assert dlg.width() == TARGETS["preset"]
    assert _imp_width(dlg) == TARGETS["preset"]


def test_llm_setup_pair_on_the_step(qtbot):
    from app.presentation.views.llm_setup_dialog import LlmConfig, LlmSetupDialog

    dlg = LlmSetupDialog(LlmConfig())
    qtbot.addWidget(dlg)

    assert dlg.minimumWidth() == TARGETS["llm-setup"]
    assert _imp_width(dlg) == TARGETS["llm-setup"]


def test_xlsx_import_trio_on_the_step(qtbot):
    from app.presentation.views.xlsx_import_dialog import XlsxImportDialog

    dlg = XlsxImportDialog()
    qtbot.addWidget(dlg)

    # The opened width is the fit floor capped by the screen — both the
    # window floor and the island's ask are on the step.
    assert dlg.minimumWidth() == TARGETS["xlsx-import"]
    assert _imp_width(dlg) == TARGETS["xlsx-import"]
    assert dlg.size().width() == TARGETS["xlsx-import"]


def test_event_pair_on_the_step(qtbot):
    from app.presentation.views.event_dialog import EventDialog

    dlg = EventDialog(None)
    qtbot.addWidget(dlg)

    assert dlg.minimumWidth() == TARGETS["event"]
    assert _imp_width(dlg) == TARGETS["event"]


def test_image_viewer_pair_on_the_step(qtbot):
    from app.presentation.views.image_viewer_dialog import ImageViewerDialog

    dlg = ImageViewerDialog(QPixmap(20, 20))
    qtbot.addWidget(dlg)

    assert dlg.width() == TARGETS["image-viewer"]
    assert _imp_width(dlg) == TARGETS["image-viewer"]


def test_doc_viewer_trio_on_the_step(qtbot, tmp_path):
    from app.presentation.views.doc_viewer_dialog import DocViewerDialog

    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n", encoding="utf-8")
    dlg = DocViewerDialog("Doc", doc)
    qtbot.addWidget(dlg)

    assert dlg.minimumWidth() == TARGETS["doc-viewer"]
    assert dlg.width() == TARGETS["doc-viewer"]
    assert _imp_width(dlg) == TARGETS["doc-viewer"]


def test_card_with_image_floor_on_the_step(qtbot):
    from app.presentation.views.entity_card_dialog import EntityCardDialog

    dlg = EntityCardDialog(None, "character")  # characters have the image field
    qtbot.addWidget(dlg)

    # The Python floor half, and the island asking at least the floor — the
    # live card column is wider than the step and may legitimately push the
    # window up (spec: «при несовместимости шкалы и содержимого ширина
    # поднимается к ближайшей ступени вверх»).
    assert dlg.minimumWidth() == TARGETS["card-floor"]
    assert _imp_width(dlg) >= TARGETS["card-floor"]
    # The QML floor constant moved with its Python half (Д6 sync rule).
    assert "entityCardVm.hasImage ? 760 : 550" in _qml_text("EntityCardRoot.qml")


def test_sheet_list_floor_on_the_step(qtbot, service):
    from app.presentation.views.character_sheet.list_dialog import (
        CharacterSheetListDialog,
    )

    dlg = CharacterSheetListDialog(service)
    qtbot.addWidget(dlg)

    assert dlg._size_floor == (TARGETS["sheet-list"], 520)
    assert _imp_width(dlg) >= TARGETS["sheet-list"]
    assert re.search(r"Math\.max\(\s*440,", _qml_text("SheetListRoot.qml"))
    # OBS-2 close, list half: this content-driven sheet never opens off the
    # scale any more (the live audit measured 620 → the sizer climbs it).
    assert dlg.width() % STEP == 0


class _EmptyEventTypesService:
    # The dialog only needs an awaitable get_event_types to construct (the
    # same stand-in tests/presentation/test_r3_island_lifecycle.py uses).
    async def get_event_types(self):
        return []


async def test_event_types_sheet_opens_climbed_to_the_step(qtbot):
    """The third content-driven sheet of the shared sizer (scene asks
    ``Math.max(460, content)``, python floor 420): its opened width rides
    the scale, too («ширина поднимается к ближайшей ступени вверх»).
    Async: the facade schedules its initial reload on the running loop."""
    from app.presentation.qml import island_size
    from app.presentation.views.event_types_dialog import EventTypesDialog

    dlg = EventTypesDialog(_EmptyEventTypesService())
    qtbot.addWidget(dlg)

    expected = _scaled_open(_imp_width(dlg), 420, island_size._screen_limit(dlg).width())
    assert dlg.width() == expected
    assert expected >= 460  # above the island's own floor, never clipped
    assert expected % STEP == 0, expected


def test_content_driven_windows_open_on_the_scale(qtbot, service):
    """The OBS-2 scenario itself, on the content-driven windows the shared
    sizer serves: when the scene's ask passes the floor, the opened width
    equals the ask climbed to the whole next 40 step — never the raw content
    measure (offscreen the 800-screen cap may bind before the climb, and
    then Qt's own window minimum answers; every outcome ends on the step)."""
    from app.presentation.qml import island_size
    from app.presentation.views.character_sheet.list_dialog import (
        CharacterSheetListDialog,
    )
    from app.presentation.views.entity_card_dialog import EntityCardDialog

    for dlg, floor in (
        (EntityCardDialog(None, "character"), TARGETS["card-floor"]),
        (CharacterSheetListDialog(service), TARGETS["sheet-list"]),
    ):
        qtbot.addWidget(dlg)
        expected = _scaled_open(
            _imp_width(dlg), floor, island_size._screen_limit(dlg).width()
        )
        assert dlg.width() == expected
        assert dlg.width() % STEP == 0, dlg


async def test_calendar_wizard_minimum_stays_on_the_scale_after_the_recount(
    qtbot, async_session
):
    from app.presentation.views.calendar_wizard import (
        STEP_COLUMN_MAX_WIDTH,
        CalendarWizardDialog,
    )

    vm = _wizard_vm(async_session)
    dlg = CalendarWizardDialog(vm)
    qtbot.addWidget(dlg)

    # NRI-0018 Д7 replaced the master's static row with the sum of the NEW
    # columns: the content-sized step column (natural sizeHint climbed to
    # the 40 step, capped) plus the preview grid at its own minimum.  The
    # scale half of the promise: the floor is that sum climbed to the next
    # step of 40 («ширина поднимается к ближайшей ступени вверх»), so the
    # window still never opens off the scale.
    column = dlg._step_column.minimumWidth()
    col_margins = dlg._step_column.layout().contentsMargins()
    natural = (
        max(dlg._stack.sizeHint().width(), dlg._footer.sizeHint().width())
        + col_margins.left()
        + col_margins.right()
    )
    assert column == min(-(-natural // STEP) * STEP, STEP_COLUMN_MAX_WIDTH)
    assert (
        dlg._step_column.minimumWidth() + dlg._preview.minimumSizeHint().width()
        <= dlg.minimumWidth()
    )
    assert dlg.minimumWidth() % STEP == 0
    assert dlg.minimumWidth() - dlg.minimumSizeHint().width() < STEP
    # the height of the wizard minimum is not part of the width scale
    assert dlg.minimumHeight() == 620


def _wizard_vm(session):
    from app.presentation.viewmodels.calendar_wizard_viewmodel import (
        CalendarWizardViewModel,
    )

    return CalendarWizardViewModel(
        GameSessionUoW(session, asyncio.Lock()),
        CalendarSettingsService(),
        first_entry=False,
    )


def test_sheet_fill_pair_on_the_step(qtbot, sheets):
    from app.presentation.views.character_sheet.fill_dialog import (
        CharacterSheetFillDialog,
    )

    sheet_svc, inst_svc = sheets
    dlg = CharacterSheetFillDialog(inst_svc, sheet_svc, 1)  # loads nothing
    qtbot.addWidget(dlg)

    assert dlg.width() == TARGETS["sheet-fill"]
    assert _imp_width(dlg) == TARGETS["sheet-fill"]


async def test_sheet_editor_pair_on_the_step(qtbot, service):
    from app.presentation.views.character_sheet.editor_dialog import (
        CharacterSheetEditorDialog,
    )

    row = await service.create("Шаблон")
    dlg = CharacterSheetEditorDialog(service, row.id)
    qtbot.addWidget(dlg)

    assert dlg.width() == TARGETS["sheet-editor"]
    assert _imp_width(dlg) == TARGETS["sheet-editor"]


# ── task 5.3: the former exceptions now carry the shared sheet token ────────


def test_search_bar_content_insets_by_the_sheet_token(qtbot, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.presentation.viewmodels.search_viewmodel import SearchViewModel
    from app.presentation.views.search_bar import SearchBar

    vm = SearchViewModel(SimpleNamespace(search_all=AsyncMock(return_value={})))
    bar = SearchBar(vm, theme=get_default_theme())
    qtbot.addWidget(bar)
    bar.show()
    qtbot.waitExposed(bar)
    for _ in range(4):
        qtbot.wait(5)  # layout-settle turns (convention of test_search_bar_island)

    field = find_item(bar.quick, "searchInput")
    origin = field.mapToScene(QPointF(0, 0))
    bottom = field.mapToScene(QPointF(0, field.height())).y()
    root = bar.quick.rootObject()

    assert origin.x() == SHEET_MARGIN_PX
    # the shorter field centres in the row band of its taller neighbour (the
    # 32 px button), so the leading edges bound the token from above…
    assert origin.y() >= SHEET_MARGIN_PX
    # …and the strip the facade fixes to the island's implicit height must
    # carry the room for the token on both edges (no clipped row bottom).
    assert root.height() - bottom >= SHEET_MARGIN_PX


def test_doc_viewer_content_insets_by_the_sheet_token(qtbot, tmp_path):
    from app.presentation.views.doc_viewer_dialog import DocViewerDialog

    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n" * 40, encoding="utf-8")
    dlg = DocViewerDialog("Doc", doc)
    qtbot.addWidget(dlg)
    dlg.show()
    for _ in range(4):
        qtbot.wait(5)

    scroll = find_item(dlg.quick, "docScroll")
    origin = scroll.mapToScene(QPointF(0, 0))

    assert origin.x() == SHEET_MARGIN_PX
    assert origin.y() == SHEET_MARGIN_PX


def test_launcher_uses_the_same_token_as_the_reformed_exceptions(qtbot):
    """«…как у карточки, события и лаунчера»: the exception's offset equals
    the reference sheet's, measured — not a second literal of its own."""
    from app.presentation.views.game_launcher_dialog import GameLauncherDialog

    dlg = GameLauncherDialog(theme=get_default_theme())
    qtbot.addWidget(dlg)
    dlg.show()
    for _ in range(4):
        qtbot.wait(5)

    button = find_item(dlg.quick, "newButton")
    origin = button.mapToScene(QPointF(0, 0))

    assert origin.x() == SHEET_MARGIN_PX
