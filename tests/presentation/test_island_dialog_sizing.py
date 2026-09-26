"""Island dialogs open big enough for their own content.

QQuickWidget in SizeRootObjectToView hides the scene's implicit size from the
widget layout, so the sizes these windows opened with used to be numbers
hardcoded at porting time — smaller than the content, which squeezed the
sheet-list button row under its own texts and pushed the entity card's action
row below the window (the two regressions this file pins). The islands now
publish their natural size and ``fit_dialog_to_island`` mirrors it onto the
window, capped by the screen.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtWidgets import QApplication, QDialog

from app.application.services.character_sheet_service import CharacterSheetService
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.layout_grid import ceil_to_width_step
from app.presentation.qml import island_size
from app.presentation.qml.island_size import SCREEN_COVER_LIMIT, fit_dialog_to_island
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog
from tests.presentation.qml_helpers import find_item

_LIST_BUTTONS = (
    "createButton",
    "presetButton",
    "openButton",
    "renameButton",
    "deleteButton",
    "closeButton",
)


@pytest.fixture
def service(async_session):
    return CharacterSheetService(CharacterSheetRepository(async_session))


def _screen_cap() -> QSize:
    geometry = QApplication.primaryScreen().availableGeometry()
    return QSize(
        int(geometry.width() * SCREEN_COVER_LIMIT),
        int(geometry.height() * SCREEN_COVER_LIMIT),
    )


class _Scene:
    """Duck-typed island root: the sizer only reads the implicit size."""

    def __init__(self, width: int, height: int) -> None:
        self._width, self._height = width, height

    def implicitWidth(self) -> float:
        return float(self._width)

    def implicitHeight(self) -> float:
        return float(self._height)


def test_fit_opens_at_the_scene_size_never_below_the_floor(qtbot):
    cap = _screen_cap()
    dialog = QDialog()
    qtbot.addWidget(dialog)

    size = fit_dialog_to_island(dialog, _Scene(10, 10), floor=(420, 520))

    assert size == QSize(min(420, cap.width()), min(520, cap.height()))
    assert dialog.size() == size


def test_fit_grows_with_the_content(qtbot):
    cap = _screen_cap()
    dialog = QDialog()
    qtbot.addWidget(dialog)

    size = fit_dialog_to_island(dialog, _Scene(900, 700), floor=(420, 520))

    # The 900 ask runs past the 420 floor, so the width half rides the
    # ui-layout-grid scale and climbs to the next step (900→920); the height
    # is not on the scale and passes through (spec «Естественная ширина…»,
    # OBS-2 close).
    assert size == QSize(min(920, cap.width()), min(700, cap.height()))
    assert dialog.size() == size


def test_fit_climbs_an_off_step_ask_like_the_live_sheets(qtbot):
    """The OBS-2 shapes themselves: an ask above the floor opens on the step
    the live audit expected (620→640 list-class, 817→840 card-class), while
    an on-step ask is left exactly on it (the «без пустоты» half)."""
    cap = _screen_cap()

    for ask, landed in ((620, 640), (817, 840), (500, 520), (520, 520)):
        dialog = QDialog()
        qtbot.addWidget(dialog)
        size = fit_dialog_to_island(dialog, _Scene(ask, 560), floor=(420, 320))
        assert size.width() == min(landed, cap.width()), ask
        assert size.width() % 40 == 0, ask


def test_fit_never_covers_the_whole_screen(qtbot):
    cap = _screen_cap()
    dialog = QDialog()
    qtbot.addWidget(dialog)

    size = fit_dialog_to_island(dialog, _Scene(99999, 99999), floor=(420, 520))

    assert size == cap


def test_fit_opens_a_broken_island_at_the_floor(qtbot):
    """No root object (a scene that failed to load) must not open a 0x0 window."""
    cap = _screen_cap()
    dialog = QDialog()
    qtbot.addWidget(dialog)

    size = fit_dialog_to_island(dialog, None, floor=(420, 520))

    assert size == QSize(min(420, cap.width()), min(520, cap.height()))


class _StubScreen:
    def __init__(self, width: int, height: int) -> None:
        self._geometry = QRect(0, 0, width, height)

    def availableGeometry(self) -> QRect:
        return self._geometry


class _StubDialogWithoutScreen:
    """A dialog whose window cannot name a screen — the unshown/foreign case."""

    def window(self):
        return self

    def screen(self):
        return None


def _app_reporting(screen):
    """Stand-in for ``QGuiApplication`` with a fixed primary screen."""

    class _App:
        @staticmethod
        def primaryScreen():
            return screen

    return _App


def test_screen_limit_falls_back_to_the_primary_screen(monkeypatch):
    """An unshown dialog has no screen of its own — the cap still applies."""
    monkeypatch.setattr(
        island_size, "QGuiApplication", _app_reporting(_StubScreen(1000, 800))
    )

    limit = island_size._screen_limit(_StubDialogWithoutScreen())

    assert limit == QSize(900, 720)  # 0.9 of 1000x800


def test_screen_limit_without_any_screen_imposes_no_cap(monkeypatch):
    """Headless with no screen at all: nothing to cap against, no zero window."""
    monkeypatch.setattr(island_size, "QGuiApplication", _app_reporting(None))

    limit = island_size._screen_limit(_StubDialogWithoutScreen())

    assert limit == QSize(100000, 100000)


def _opened(floor: tuple[int, int], natural: tuple[int, int], cap: QSize) -> QSize:
    """The size a dialog must open with: the content, floored under the scale
    rule (an ask above the floor is climbed to the next 40 step — OBS-2
    close; an ask the floor covers opens at the floor), screen-capped."""
    width = (
        ceil_to_width_step(natural[0]) if natural[0] > floor[0] else floor[0]
    )
    return QSize(
        max(floor[0], min(width, cap.width())),
        max(floor[1], min(natural[1], cap.height())),
    )


def _pump(qtbot) -> None:
    for _ in range(4):
        qtbot.wait(5)


def test_card_scene_asks_for_more_than_the_pinned_size(qtbot):
    """The floor the port pinned is below the card's own content.

    NRI-0018 task 5.2 moved the with-image floor 750→760 onto the
    ui-layout-grid scale; the measured content ask is unchanged, so the
    scene still asks for more than the floor it opens at.
    """
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)

    root = dialog._root

    assert root.implicitHeight() > 550
    assert root.implicitWidth() > 760


def test_card_window_opens_where_the_scene_fits(qtbot):
    cap = _screen_cap()
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)

    root = dialog._root
    natural = (int(round(root.implicitWidth())), int(round(root.implicitHeight())))

    assert dialog.size() == _opened((760, 550), natural, cap)


def test_the_card_at_its_scene_size_shows_the_action_row(qtbot):
    """Given the size the scene asked for, «Отмена» needs no scrolling.

    The window is resized to the scene's own size here, not to the opened one,
    so the check holds on any test screen (an offscreen one may be too short
    for the whole card, and then the scroll legitimately covers the rest).
    """
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    root = dialog._root
    dialog.show()
    dialog.resize(int(root.implicitWidth()), int(root.implicitHeight()))
    _pump(qtbot)

    save_button = find_item(dialog.quick, "entitySaveButton")
    bottom = save_button.mapToScene(QPointF(0, save_button.height())).y()

    assert bottom <= root.height()


def test_sheet_list_scene_asks_for_the_whole_button_row(qtbot, service):
    """The 420 the port pinned could not hold the six actions side by side.

    NRI-0018 put the floor on the scale (420→440) and the OBS-2 close climbs
    the scene's wider ask to the next step — the opened width rides the
    40-grid, whatever the fonts measure offscreen.
    """
    dialog = CharacterSheetListDialog(service)
    qtbot.addWidget(dialog)

    root = dialog._root
    natural = (int(round(root.implicitWidth())), int(round(root.implicitHeight())))

    assert natural[0] > 420
    assert dialog.size() == _opened((440, 520), natural, _screen_cap())
    assert dialog.width() % 40 == 0


def test_sheet_list_buttons_keep_their_own_width_on_both_tabs(qtbot, service):
    cap = _screen_cap()
    dialog = CharacterSheetListDialog(service)
    qtbot.addWidget(dialog)
    dialog.show()
    _pump(qtbot)

    for tab, names in (
        (0, _LIST_BUTTONS),
        # «Создать из пресета…» is an action of the templates tab only.
        (1, tuple(name for name in _LIST_BUTTONS if name != "presetButton")),
    ):
        dialog.vm.setCurrentTab(tab)
        _pump(qtbot)
        for name in names:
            button = find_item(dialog.quick, name)
            assert button.width() >= button.implicitWidth() - 1, name
            origin = button.mapToScene(QPointF(0, 0))
            assert origin.x() + button.width() <= dialog.quick.width() + 1, name
    assert dialog.width() <= cap.width()
