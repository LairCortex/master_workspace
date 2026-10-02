"""The image viewer and the «Выберите <тип>» picker as sheets (task 2.5).

Both blocking shows of the application retired with this slice (design Д7):
the picture click and the link picker now ride ``ApplicationWiring.open_sheet``
— WindowModal over the opening layer, the parent chain as the stack, release
on ``finished``. These tests walk exactly the spec scenarios:

* image-display «Просмотр оригинала полного размера» — the viewer is a
  720×600 sheet (design Д6 default) and an original bigger than the sheet
  stays fully reachable through its Flickable («Прокрутка крупного
  изображения»);
* modal-sheets «Цепочка событие — карточка — изображение» — the viewer over
  the card dims it one share, and closing returns exactly to the card;
* the picker rides the same stack over the dialog that opened it; ОК commits,
  Отмена/Esc/header «Закрыть» hand the opener layer back untouched;
* modal-sheets «Прикладные диалоги не входят во вложенный цикл событий» —
  the show paths never call ``QDialog.exec``: the test runs them with
  ``exec`` swapped for a raiser, the offscreen stand-in for the qasync
  journal error «Cannot enter into task» that exec nesting produced.

The connector and the host are built the way ``test_sheet_stack_contract``
builds them: the open paths touch no session, the lock only satisfies the
constructor, and only the top-level host is handed to ``qtbot`` (the sheets
hang C++-owned under it — that is the parent chain the dim walk reads).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QPushButton, QWidget

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.image_viewer_dialog import ImageViewerDialog
from app.presentation.views.sheet_frame import SheetFrame
from app.presentation.wiring import ApplicationWiring
from tests.presentation.qml_helpers import find_item

# One sheet under a parent costs, pinned literally (test_sheet_stack_contract).
UNIT = 0.25


class _StubEntityService:
    async def get_all(self):
        return []


def _make_wiring() -> ApplicationWiring:
    """The connector with exactly what the sheet-open paths touch."""
    app = SimpleNamespace(
        _image_store=None,
        _theme=None,
        _wire_mentions_for_dialog=lambda dialog, handler: None,
        _wire_ai_buttons=lambda dialog: None,
        _get_entity_service=lambda entity_type: _StubEntityService(),
    )
    return ApplicationWiring(
        app, None, None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
    )


def _spy(wiring: ApplicationWiring) -> list[bool]:
    states: list[bool] = []
    wiring.sheet_stack_changed.connect(states.append)
    return states


def _pixmap(width: int = 20, height: int = 20) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill()
    return pixmap


def _host(qtbot) -> QWidget:
    """Main-window stand-in; the stack itself belongs to the connector."""
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    return host


# ── image-display: the viewer sheet (720×600, scroll, close back) ───────────


def test_viewer_is_a_720x600_sheet_reaching_a_large_original_by_scroll(qtbot):
    """Design Д6 default + spec «Прокрутка крупного изображения»: the sheet
    opens at the former window's 720×600, the island Flickable keeps the
    original at full size, so a 1600×2400 picture is scrollable, never clamped."""
    host = _host(qtbot)
    wiring = _make_wiring()
    _spy(wiring)

    viewer = ImageViewerDialog(_pixmap(1600, 2400), parent=host)
    assert viewer.windowTitle() == "Просмотр изображения"
    assert (viewer.width(), viewer.height()) == (720, 600)

    wiring.open_sheet(viewer)
    assert viewer.isVisible()

    flick = find_item(viewer.quick, "viewerScroll")
    qtbot.waitUntil(
        lambda: flick.property("contentHeight") == 2400, timeout=2000
    )
    assert flick.property("contentWidth") == 1600
    # The content outgrows the viewport on both axes — scroll, not clamp.
    assert flick.property("width") < flick.property("contentWidth")
    assert flick.property("height") < flick.property("contentHeight")

    viewer.reject()


def test_viewer_over_the_card_dims_it_and_closes_back_to_the_card(qtbot):
    """Spec «Цепочка событие — карточка — изображение» + «Закрытие окна
    просмотра»: the card builds the viewer and the connector's stack shows it
    over the card; the close lands on the card, the share is lifted, the
    stack is released only when the card itself leaves."""
    host = _host(qtbot)
    wiring = _make_wiring()
    states = _spy(wiring)

    card = EntityCardDialog(None, "character", parent=host)
    # The card's own child-sheet channel, connected exactly as the card
    # factory connects it (wiring._open_entity_card).
    card.sheet_requested.connect(wiring.open_sheet)
    wiring.open_sheet(card)
    assert states == [True]

    card._viewer_original = _pixmap(40, 40)
    card._open_image_viewer()

    viewer = next(v for v in card.findChildren(ImageViewerDialog) if v.isVisible())
    assert viewer.parent() is card  # the parent chain is the stack
    assert card._root.property("sheetScrimAlpha") == pytest.approx(UNIT)
    assert states == [True]  # nested openings do not re-announce

    viewer.reject()  # Esc / header «Закрыть» both land here
    assert not viewer.isVisible()
    assert card.isVisible()  # exactly back to the opening layer
    assert card._root.property("sheetScrimAlpha") == pytest.approx(0.0)
    assert states == [True]  # the card still holds the stack

    card.reject()
    assert states == [True, False]


# ── modal-sheets: the «Выберите <тип>» sheet over its opener ────────────────


def _event_dialog_with_candidates(qtbot, wiring, host) -> tuple[EventDialog, list]:
    dialog = EventDialog(None, parent=host)
    dialog.sheet_requested.connect(wiring.open_sheet)
    wiring.open_sheet(dialog)
    first = SimpleNamespace(id=1, name="Один")
    second = SimpleNamespace(id=2, name="Два")
    dialog.set_available_entities("characters", [first, second])
    return dialog, [first, second]


def _live_picker(opener) -> SheetFrame:
    return next(
        s for s in opener.findChildren(SheetFrame)
        if s.isVisible() and s.windowTitle().startswith("Выберите")
    )


def test_picker_sits_over_the_dialog_and_ok_returns_the_choice_to_it(qtbot):
    """Design Д6: the picker is a «Выберите <тип>» SheetFrame with the list
    and the ОК/Отмена pair, opened on the connector's stack OVER the opening
    sheet — the dialog dims one share while it is up. ОК commits the choice
    into the section and hands the dialog back: scrim lifted, stack held."""
    host = _host(qtbot)
    wiring = _make_wiring()
    states = _spy(wiring)
    dialog, entities = _event_dialog_with_candidates(qtbot, wiring, host)
    assert dialog._root.property("sheetScrimAlpha") == pytest.approx(0.0)

    dialog._open_related_picker("characters", "Персонажи")
    picker = _live_picker(dialog)
    assert picker.parent() is dialog  # the opening layer is its parent
    assert picker.windowTitle() == "Выберите персонажи"
    assert dialog._root.property("sheetScrimAlpha") == pytest.approx(UNIT)
    assert states == [True]  # a child sheet does not re-announce the stack

    items = picker.findChild(QListWidget)
    items.item(0).setSelected(True)
    buttons = picker.findChild(QDialogButtonBox)
    buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    assert not picker.isVisible()
    assert dialog.vm.characters.get_current_ids() == [entities[0].id]
    assert dialog.isVisible()  # returned exactly to the opening layer
    assert dialog._root.property("sheetScrimAlpha") == pytest.approx(0.0)

    dialog.reject()
    assert states == [True, False]


@pytest.mark.parametrize("close_route", ["cancel", "header"])
def test_picker_cancel_and_header_close_hand_the_opener_back(qtbot, close_route):
    """Отмена and the header «Закрыть» (the Esc outcome) both leave the
    section untouched and return to the opening sheet — the picker is a
    sheet, not a decision the opener must consume."""
    host = _host(qtbot)
    wiring = _make_wiring()
    _spy(wiring)
    dialog, _entities = _event_dialog_with_candidates(qtbot, wiring, host)

    dialog._open_related_picker("characters", "Персонажи")
    picker = _live_picker(dialog)
    assert dialog._root.property("sheetScrimAlpha") == pytest.approx(UNIT)

    if close_route == "cancel":
        buttons = picker.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
    else:
        picker.findChild(QPushButton, "sheetFrameCloseButton").click()

    assert not picker.isVisible()
    assert dialog.vm.characters.get_current_ids() == []
    assert dialog.isVisible()
    assert dialog._root.property("sheetScrimAlpha") == pytest.approx(0.0)
    dialog.reject()


# ── modal-sheets: no nested event loop on these paths ───────────────────────


def test_viewer_and_picker_paths_never_enter_a_nested_event_loop(
    qtbot, monkeypatch
):
    """Spec «Прикладные диалоги не входят во вложенный цикл событий», the
    scenario «Просмотр изображения без вложенного цикла»: the whole chain
    card → viewer → close → picker → ОК runs with ``QDialog.exec`` swapped
    for a raiser. The qasync error «Cannot enter into task» was the symptom
    of exactly this nesting — offscreen, an ``exec`` call on any of these
    paths is the same crime and fails the test at once."""

    def _no_exec(self, *args, **kwargs):
        raise AssertionError("вложенный цикл событий: QDialog.exec вызван")

    monkeypatch.setattr(QDialog, "exec", _no_exec)

    host = _host(qtbot)
    wiring = _make_wiring()
    states = _spy(wiring)

    # The viewer chain (the spec scenario): card → viewer → close.
    card = EntityCardDialog(None, "character", parent=host)
    card.sheet_requested.connect(wiring.open_sheet)
    wiring.open_sheet(card)
    card._viewer_original = _pixmap(30, 30)
    card._open_image_viewer()
    viewer = next(v for v in card.findChildren(ImageViewerDialog) if v.isVisible())
    viewer.reject()
    assert card.isVisible()

    # The picker chain: dialog → «Выберите …» → ОК.
    dialog, entities = _event_dialog_with_candidates(qtbot, wiring, host)
    dialog._open_related_picker("characters", "Персонажи")
    picker = _live_picker(dialog)
    items = picker.findChild(QListWidget)
    items.item(1).setSelected(True)
    picker.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Ok
    ).click()
    assert dialog.vm.characters.get_current_ids() == [entities[1].id]

    # Stack fully drained by the two closes.
    dialog.reject()
    card.reject()
    assert states == [True, False]
