"""Glyph consumers ride the library square (change nri-0018-grid-alignment-and-card,
task 1.3; spec qml-components «Все мелкие действия — один квадрат»).

Runtime half: every small glyph action of the islands measures exactly the
library's 32×32 square where it is actually rendered —

* the sheet-header close («✕», header of the event dialog),
* the entity-card music edit («✎»),
* the timeline scale add («+», migrated off the root's local ``squareSide``),
* the editor page rail («↑↓−+») and the event-types arrows («↑↓»).

Source half (the task's grep pin): islands carry NO glyph geometry of their
own any more — the ``squareSide`` knob is gone, no ``ThemeButton`` instance
still wears a mute glyph (the classification is the very scanner the 4.1 a11y
guard ships), and no ``ThemeIconButton``/``ThemeAiButton`` usage site (island
or library) states a size: a width/height/Layout size on a usage would
re-introduce a private gauge next to the component's own constant (design Д1
«одно знание — одно место»). The scanner runs on the comment-masked,
string-blanked view (the qml_a11y_scan helpers) and only counts depth-1
properties of the usage block, so names in comments and geometry inside
nested blocks cannot launder a size in or out.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.application.services.character_sheet_service import CharacterSheetService
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation import qml as qml_shell
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.character_sheet_viewmodel import CharacterSheetViewModel
from app.presentation.viewmodels.event_types_view_model import EventTypesViewModel
from app.presentation.viewmodels.timeline_viewmodel import TimelineViewModel
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item
from tests.presentation.test_sheet_window_islands_qml import load_editor
from tests.qml_a11y_scan import (
    blank_string_contents,
    depths,
    mask_qml,
    stock_instances,
)
from tests.ui.test_theme_grab import make_runtime

QML_ROOT = Path(qml_shell.__file__).resolve().parent
SIDE = 32

USAGE_TYPES = ("ThemeIconButton", "ThemeAiButton")

# Sizes a usage site must never state — the component owns the gauge (Д1).
_USAGE_SIZE_RE = re.compile(
    r"(?<![.\w])(width|height|squareSide"
    r"|Layout\.(?:fill|minimum|maximum|preferred)(?:Width|Height))\s*:"
)


def _assert_square_glyph(item, where: str) -> None:
    assert (item.width(), item.height()) == (SIDE, SIDE), where
    assert (item.implicitWidth(), item.implicitHeight()) == (SIDE, SIDE), where


# ── source scanner (the grep pin) ─────────────────────────────────────────────

def _iter_blocks(text: str, type_name: str):
    """Yield (body_start, body_end, dep) for every ``type_name { … }`` block,
    on the comment-masked / string-blanked view (positions map 1:1)."""
    masked = mask_qml(text)
    struct = blank_string_contents(masked)
    dep = depths(struct)
    open_re = re.compile(rf"(?<![\w]){re.escape(type_name)}\s*\{{")
    for m in open_re.finditer(struct):
        open_idx = m.end() - 1
        depth = 1
        for k in range(open_idx + 1, len(struct)):
            if struct[k] == "{":
                depth += 1
            elif struct[k] == "}":
                depth -= 1
                if depth == 0:
                    yield open_idx + 1, k, dep
                    break


def _depth1_size_hits(text: str, type_name: str) -> list[str]:
    """Depth-1 size properties declared inside every usage block."""
    masked = mask_qml(text)
    dep = depths(blank_string_contents(masked))
    hits: list[str] = []
    for body_start, body_end in ((s, e) for s, e, _ in _iter_blocks(text, type_name)):
        body_depth = dep[body_start]
        for prop in _USAGE_SIZE_RE.finditer(masked, body_start, body_end):
            if dep[prop.start()] == body_depth:
                line = masked.count("\n", 0, prop.start()) + 1
                hits.append(f"{type_name} line {line}: {prop.group(1)}")
    return hits


def test_icon_button_usages_state_no_sizes():
    violations: list[str] = []
    for qml_file in sorted(QML_ROOT.rglob("*.qml")):
        text = qml_file.read_text(encoding="utf-8")
        for type_name in USAGE_TYPES:
            violations += _depth1_size_hits(text, type_name)
    assert violations == []


def test_no_foreign_glyph_knobs_or_glyph_wearing_theme_buttons():
    assert "squareSide" not in "".join(
        p.read_text(encoding="utf-8") for p in QML_ROOT.rglob("*.qml")
    )
    offenders: list[str] = []
    for qml_file in sorted(QML_ROOT.rglob("*.qml")):
        text = qml_file.read_text(encoding="utf-8")
        for inst in stock_instances(text):
            if inst.type_name == "ThemeButton" and inst.text_kind == "glyph":
                offenders.append(f"{qml_file.name} line {inst.line}")
    assert offenders == []


def test_sheet_header_close_glyph_is_the_library_icon_button():
    """✕ transplanted inside the component: ThemeSheetHeader now crowns its
    sheet with the library square button — role/name/Press stay exactly as
    pinned in test_sheet_header_accessibility, only the gauge is the
    component's own."""
    text = (QML_ROOT / "nri" / "components" / "ThemeSheetHeader.qml").read_text(
        encoding="utf-8"
    )
    closes = [
        (start, end)
        for start, end, _ in _iter_blocks(text, "ThemeIconButton")
        if "✕" in text[start:end]
    ]
    assert len(closes) == 1
    body = text[closes[0][0]:closes[0][1]]
    assert 'objectName: "sheetHeaderClose"' in body
    assert 'Accessible.name: "Закрыть"' in body


# ── islands on the shared shell engine (facade-identical context) ─────────────

def _load_island(qtbot, qapp, tmp_path, source: Path, context: dict):
    """An island root on the production shell (setup_qml_shell: one import
    path, the Nri scope, the palette bridge), sized to its implicit root like
    the island suites do, so the layout settles at the real open size."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    runtime = make_runtime(tmp_path, "dark")
    palette = QmlPalette(runtime)
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    palette.setParent(widget)
    widget.rootContext().setContextProperty("islandPalette", palette)
    for name, value in context.items():
        if isinstance(value, QObject):  # raw-pointer lifetime: die with the widget
            value.setParent(widget)
        widget.rootContext().setContextProperty(name, value)
    widget.setSource(QUrl.fromLocalFile(str(source)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    root = widget.rootObject()
    widget.resize(
        int(root.property("implicitWidth")), int(root.property("implicitHeight"))
    )
    widget.grab()
    return widget


# ── runtime: the glyph measures the square where it is rendered ───────────────

def test_sheet_header_close_is_the_library_square(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.quick.grab()
    _assert_square_glyph(find_item(dialog.quick, "sheetHeaderClose"), "✕")


def test_entity_card_music_edit_glyph_is_the_square(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.quick.grab()
    _assert_square_glyph(find_item(dialog.quick, "entityMusicEditButton"), "✎")


def test_timeline_add_glyph_is_the_square(qtbot, qapp, tmp_path):
    """«+» of the scale lost its local ``squareSide: 30`` — the header square
    is the library gauge now."""
    widget = _load_island(
        qtbot, qapp, tmp_path, QML_ROOT / "TimelineRoot.qml",
        {"vm": TimelineViewModel(None)},
    )
    _assert_square_glyph(find_item(widget, "addButton"), "timeline +")


def test_event_types_arrows_are_the_squares(qtbot, qapp, tmp_path):
    vm = EventTypesViewModel()
    vm.set_rows([
        SimpleNamespace(id=11, name="Сюжет", color_index=1, sort_order=0),
        SimpleNamespace(id=12, name="Побочное", color_index=2, sort_order=1),
    ])
    widget = _load_island(
        qtbot, qapp, tmp_path, QML_ROOT / "EventTypesRoot.qml",
        {"eventTypesVm": vm},
    )
    for name in ("typeUpButton", "typeDownButton"):
        _assert_square_glyph(find_item(widget, name), name)


@pytest.fixture
async def rail_vm(async_session):
    sheet_svc = CharacterSheetService(CharacterSheetRepository(async_session))
    row = await sheet_svc.create("Лист")
    view_model = CharacterSheetViewModel(sheet_svc)
    await view_model.load(row.id)
    return view_model


@pytest.fixture
def rail_palette(tmp_path):
    return QmlPalette(make_runtime(tmp_path, "dark"))


def test_editor_rail_glyphs_are_the_squares(qtbot, rail_vm, rail_palette):
    widget = load_editor(qtbot, rail_vm, rail_palette)
    for name in ("railUpButton", "railDownButton", "railDeleteButton", "railAddButton"):
        _assert_square_glyph(find_item(widget, name), name)
