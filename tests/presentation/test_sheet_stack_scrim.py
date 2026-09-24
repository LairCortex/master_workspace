"""Stack depth of island sheets (change nri-0014-window-contract-and-docs,
task 4.3; defect CR5, spec qml-shell «Лист главного окна показан заголовком
и различим в стеке»).

The scenario pins the reading rule «лист под ним явно темнее»: when a child
sheet is opened over a parent sheet, the parent receives an extra dim — an
overlay of the ``color.scrim`` palette entry whose alpha grows with the number
of layers under it. The stack owner is the connector (design D3): these tests
drive the one opening site a sheet-over-sheet stack has, the wiring's related-
create popup, so the whole mechanism (counting, depth arithmetic, the release
on close) runs exactly as in the app, without a game DB behind it.

The numbers are pinned literally (the test-qml-palette convention for theme
alphas): one sheet under a parent dims it by 0.25, two by 0.50; closing one
child drops the parent back one step and closing the last one lifts the scrim
entirely (alpha 0, overlay not even painted — a top sheet keeps the untouched
wireframe the pixel contract pins).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.wiring import ApplicationWiring
from tests.presentation.qml_helpers import find_item

# The dim one sheet under a parent costs, pinned literally in the test rather
# than imported (renumbering the constant must be a deliberate choice).
UNIT = 0.25


class _StubEntityService:
    async def get_all(self):
        return []


def _make_wiring() -> ApplicationWiring:
    """The connector with exactly what the related-create path touches.

    The popup path reads only these collaborators off the application (the
    mention/AI glue is the composition root's), and ``_spawn`` never runs
    here: no sheet is saved in this module, the session lock is only
    required by the wiring constructor.
    """
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


def _visible_cards(host) -> list[EntityCardDialog]:
    return [d for d in host.findChildren(EntityCardDialog) if d.isVisible()]


def _scrim(dialog):
    """(threaded alpha, overlay painted?, overlay opacity) of the sheet."""
    item = find_item(dialog.quick, "sheetScrim")
    return (
        dialog._root.property("sheetScrimAlpha"),
        item.property("visible"),
        item.property("opacity"),
    )


async def test_child_sheet_dims_the_parent_and_closing_lifts_the_dim(qtbot):
    parent = EventDialog(None)
    qtbot.addWidget(parent)

    wiring = _make_wiring()
    # A top sheet carries no dim: the overlay is not even painted.
    assert _scrim(parent) == (pytest.approx(0.0), False, pytest.approx(0.0))

    await wiring._open_related_create_dialog(parent, "items", "item")
    child = _visible_cards(parent)[0]
    assert child.parent() is parent

    # Two sheets are open: the parent's overlay is visible with alpha above
    # zero — the task's offscreen reading of «различима глубина стека».
    alpha, painted, opacity = _scrim(parent)
    assert painted is True
    assert alpha > 0.0
    assert alpha == pytest.approx(UNIT)
    assert opacity == pytest.approx(UNIT)

    # Closing the child lifts the dim through the single finished channel,
    # whichever close route the user took (reject is Esc/«Отмена»/header ✕).
    child.reject()
    assert not child.isVisible()
    assert _scrim(parent) == (pytest.approx(0.0), False, pytest.approx(0.0))


async def test_two_open_sheets_grow_the_dim_and_each_close_peels_one(qtbot):
    parent = EntityCardDialog(None, entity_type="character")
    qtbot.addWidget(parent)
    wiring = _make_wiring()

    await wiring._open_related_create_dialog(parent, "items", "item")
    await wiring._open_related_create_dialog(parent, "items", "item")
    first, second = _visible_cards(parent)

    assert _scrim(parent)[0] == pytest.approx(2 * UNIT)
    # The child sheets themselves are top of their own stack: undimmed.
    assert _scrim(first)[0] == pytest.approx(0.0)

    first.reject()
    assert _scrim(parent)[0] == pytest.approx(UNIT)  # peeled one layer
    second.reject()
    assert _scrim(parent) == (pytest.approx(0.0), False, pytest.approx(0.0))


async def test_deep_stack_dims_the_lower_sheet_harder(qtbot):
    """«Нижний лист затемнён сильнее верхнего» — per-ancestor dim.

    A sheet opened over a card that itself hovers over the event sheet dims
    every ancestor under it: the event sheet sits two layers down and must
    read clearly darker than the card under the cursor's sheet.
    """
    event_sheet = EventDialog(None)
    qtbot.addWidget(event_sheet)
    wiring = _make_wiring()

    await wiring._open_related_create_dialog(event_sheet, "items", "item")
    card = _visible_cards(event_sheet)[0]
    await wiring._open_related_create_dialog(card, "items", "item")
    nested = _visible_cards(card)[0]

    event_alpha = _scrim(event_sheet)[0]
    card_alpha = _scrim(card)[0]
    assert card_alpha == pytest.approx(UNIT)
    assert event_alpha == pytest.approx(2 * UNIT)
    assert event_alpha > card_alpha  # the lower layer is visibly darker
    assert _scrim(nested)[0] == pytest.approx(0.0)

    nested.reject()
    assert _scrim(event_sheet)[0] == pytest.approx(UNIT)
    assert _scrim(card) == (pytest.approx(0.0), False, pytest.approx(0.0))

    card.reject()
    assert _scrim(event_sheet) == (pytest.approx(0.0), False, pytest.approx(0.0))


async def test_lift_of_a_dead_island_is_silent(qtbot):
    """The teardown race the full-suite e2e walk into (nri-0014 4.3 review).

    Closing a game releases an island one loop turn after its dialog closes
    (IslandDialogMixin), but child sheets may leave later — their lazy lift
    then reaches a scene whose C++ item is already gone. That stray lift is
    pure paint loss for a dying sheet: it must be dropped silently, never
    raised into the Qt event loop (the xlsx publish_* drop contract).
    """
    parent = EventDialog(None)
    qtbot.addWidget(parent)
    wiring = _make_wiring()

    await wiring._open_related_create_dialog(parent, "items", "item")
    child = _visible_cards(parent)[0]
    assert _scrim(parent)[0] == pytest.approx(UNIT)

    # The release step the closing island's one-shot performs: the scene dies
    # while the child sheet is still open above it.
    parent.release_island()

    child.reject()  # before the fix: RuntimeError inside the signal emission
    assert not child.isVisible()
    # Bookkeeping still peeled: the connector forgets the sheet despite the
    # dead scene (proves the lift ran to the end of its walk, not around it).
    assert wiring._sheet_scrim_units == {}


async def test_the_scrim_paints_the_palette_dim_covering_the_sheet(
    qtbot, tmp_path
):
    """The overlay is the color.scrim entry, not an invented hex.

    With a valid theme runtime the scrim rectangle resolves to the palette's
    dim color (the compiler stays the only color engine) and covers the whole
    sheet — the dim belongs to the sheet's full surface, not a corner strip.
    """
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    parent = EventDialog(None, theme=runtime)
    qtbot.addWidget(parent)
    wiring = _make_wiring()

    await wiring._open_related_create_dialog(parent, "items", "item")

    item = find_item(parent.quick, "sheetScrim")
    color = item.property("color")  # QColor, resolved from the palette entry
    assert color.name() == "#000000"
    root = parent._root
    assert item.property("width") == root.property("width")
    assert item.property("height") == root.property("height")

    _visible_cards(parent)[0].reject()
