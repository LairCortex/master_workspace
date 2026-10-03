"""Offscreen pins of the entity-preview island (NRI-0022 tasks 4.1–4.5;
multi-pane and the pin since NRI-0025 tasks 4.1–4.3).

The VM unit files pin the composition rules; this file proves the live island:
the pane stack (equal shares, own Flickable each, the pane's 32 px band fixed
above its scroll, the first band holding the columns' header axis), the single
pane filling the column (the zero-pins mode painted like today), the pin button
in the band with its four fixed name/tooltip formulations and its Press riding
the component seat, the empty live area hint under the pins (no band of its
own), the self-explaining fully empty column, the read-only set through the
real QML items, the picture slot with its viewer gesture (the 4096 card
posture), the compact relation sections with their Press contract («Переходит
к сущности»), and the RichText mention anchors whose click feeds the one
selection bus. The facade is dumb — the tests drive it with the slot frames
the group-5 wiring hands in (show_slots/clear in; entity/pin requests out);
since the connector switched, a zero-pins frame is the one-live-card feed.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt, QUrl, Signal
from PySide6.QtGui import QAccessible, QImage, QPixmap
from PySide6.QtQml import QQmlEngine, qmlAttachedPropertiesObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.presentation.qml.tooltip_shim import Nri
from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.utils import image_utils
from app.presentation.views import entity_preview as preview_module
from app.presentation.views.entity_preview import EntityPreviewWidget
from tests.presentation.qml_helpers import find_item, find_items, track, walk_items
from tests.presentation.test_panel_header_band import BAND, TOP_MARGIN


def _token_px(key: str) -> float:
    """Numeric value of a spacing token (both themes carry the same one)."""
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None, "the token file must stay valid for the pins"
    light, dark = tokens[key]["light"], tokens[key]["dark"]
    assert light == dark, (key, light, dark)
    return float(light.removesuffix("px"))


class _NowStub(QObject):
    """Duck of the game-«now» VM the composition root hands the widget."""

    nowChanged = Signal()

    def __init__(self, coord, is_bc: bool = False) -> None:
        super().__init__()
        self.coord = coord
        self.is_bc = is_bc


def _desc(characteristics: str = "", backstory: str = ""):
    return SimpleNamespace(characteristics=characteristics, backstory=backstory)


def _entity(entity_type: str = "character", **overrides):
    base = dict(
        id=4,
        name="Банн",
        rating=8,
        start_date=date(1200, 1, 1),
        end_date=None,
        start_bc=False,
        end_bc=False,
        description=_desc("Крепкий", "Долгая история"),
        music_url="https://example.com/song",
        image_ref=None,
        items=[],
        locations=[],
        organizations=[],
    )
    if entity_type == "character":
        base["personality"] = "Упрямый"
        base["tasks"] = "Найти брата"
    if entity_type in ("organization", "location"):
        base["tasks"] = "Держать оборону"
    base.update(overrides)
    return SimpleNamespace(**base)


def _preview(
    qtbot,
    entity_type: str | None = None,
    entity=None,
    now_vm=None,
    size=(420, 1400),
) -> EntityPreviewWidget:
    """A shown preview island. The tall default frame keeps the whole read-
    only composition (the 240-px picture slot included) inside the viewport,
    so scene-addressed clicks reach every row; the scroll rule gets its own
    deliberately short-viewport test."""
    widget = EntityPreviewWidget(now_date_vm=now_vm)
    qtbot.addWidget(widget)
    widget.resize(*size)
    if entity is not None:
        widget.show_slots([], (entity_type or "character", entity))
    widget.show()
    QApplication.processEvents()
    return widget


def _visible(widget, name) -> list[bool]:
    items = find_items(widget.quick, name)
    items.sort(key=lambda i: i.mapToScene(QPointF(0, 0)).y())
    return [bool(i.property("visible")) for i in items]


def _accessible(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def _press(item) -> None:
    actions = _accessible(item).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


def _click(widget, item, *, pos: QPointF | None = None) -> None:
    point = pos or QPointF(item.width() / 2, item.height() / 2)
    scene = item.mapToScene(point)
    QTest.mouseClick(
        widget.quick,
        Qt.MouseButton.LeftButton,
        pos=QPoint(round(scene.x()), round(scene.y())),
    )
    QApplication.processEvents()


# ── task 4.1: the island face — band, headers, empty state ──────────────────


def test_island_root_contract_and_minimal_child_context(qtbot):
    widget = _preview(qtbot)
    root = widget.quick.rootObject()
    assert root.objectName() == "entityPreviewRoot"

    context = QQmlEngine.contextForObject(root)
    assert context.contextProperty("entityPreviewVm") is widget.vm
    assert context.contextProperty("islandPalette") is widget._palette
    # NRI-0025 task 4.2: the pin declares Nri.tooltip, so the island gained
    # its own tooltip bridge (the detail-panel/timeline pattern) — still no
    # other names: VM + palette + bridge are the whole surface (spec
    # qml-shell «Нативный шим всплывающих подсказок для островов»).
    bridge = widget._tooltip_bridge
    assert context.contextProperty("tooltipBridge") is bridge


def test_empty_state_explains_itself_without_a_type_title(qtbot):
    widget = _preview(qtbot)

    # In the empty state the one band reads the plain word (spec «Заголовок
    # предпросмотра — единственная строка заголовка», «Пустая колонка
    # подписана одним словом»).
    band = find_item(widget.quick, "previewBandTitle")
    assert band.property("text") == "Карточка"
    assert band.property("visible") is True
    assert bool(find_item(widget.quick, "previewHeaderBand").property("visible")) is True

    hint = find_item(widget.quick, "previewEmptyHint")
    assert hint.property("visible") is True
    # NRI-0025 (delta entity-preview «Подсказка не обещает средний столбец»):
    # the entity arrives from relations, search and the middle column alike,
    # so the hint no longer points at the middle column.
    assert hint.property("text") == (
        "Выберите сущность — здесь появится её карточка"
    )
    # the themed face: the library's muted italic HintText (the detail
    # panel's empty-hint posture, task 4.1 «тематизированная подсказка»)
    assert hint.metaObject().className().startswith("HintText")
    # The empty live-area sibling exists in the tree but stays silent here —
    # the zero-pane column is not the «empty live area» state (task 4.3).
    assert bool(find_item(widget.quick, "previewLiveEmptyHint").property("visible")) is False

    # The second headline is gone from the island at all (the reader's fix
    # 2026-09-28); with zero panes the Repeater instantiates no pane, so no
    # scroll, no card markup and no pin exist (the empty face is the whole
    # column, spec preview-pins «При отсутствии закреплений»).
    assert find_items(widget.quick, "previewTitle") == []
    assert find_items(widget.quick, "previewScroll") == []
    assert find_items(widget.quick, "previewPaneBand_0") == []
    assert widget.vm.panes == []


@pytest.mark.parametrize(
    "type_key, label",
    [
        ("organization", "Организация"),
        ("character", "Персонаж"),
        ("item", "Предмет"),
        ("location", "Локация"),
    ],
)
def test_a_shown_entity_renames_the_band_and_hides_the_hint(
    qtbot, type_key, label
):
    widget = _preview(qtbot, type_key, _entity(type_key))

    # Since NRI-0025 the card's band is the PANE'S own title line — titled by
    # the registry type name AND the shown entity's name after the middle dot
    # (reader's fix 2026-10-03; the name field inside stays, the duplicate is
    # the point). No inner «Карточка…» duplicate exists. The column-wide
    # «Карточка» band steps off the axis (checkpoint п.2: from the first pane
    # the first band holds it).
    assert find_item(widget.quick, "previewPaneTitle").property("text") == (
        f"Карточка: {label} · Банн"
    )
    assert bool(find_item(widget.quick, "previewHeaderBand").property("visible")) is False
    assert find_items(widget.quick, "previewTitle") == []
    assert find_item(widget.quick, "previewEmptyHint").property("visible") is False
    assert _visible(widget, "previewScroll") == [True]


def test_clear_returns_the_column_to_the_hint(qtbot):
    widget = _preview(qtbot, "character", _entity())
    assert find_item(widget.quick, "previewEmptyHint").property("visible") is False

    widget.clear()
    QApplication.processEvents()
    assert find_item(widget.quick, "previewEmptyHint").property("visible") is True
    assert find_item(widget.quick, "previewBandTitle").property("text") == "Карточка"
    assert bool(find_item(widget.quick, "previewHeaderBand").property("visible")) is True
    assert widget.vm.panes == []


# ── task 4.2: the read-only composition on the live island ──────────────────


def test_character_renders_the_full_card_field_set(qtbot):
    widget = _preview(
        qtbot,
        "character",
        _entity(),
        now_vm=_NowStub(date(1203, 1, 1)),
    )
    assert find_item(widget.quick, "previewName").property("text") == "Банн"
    assert find_item(widget.quick, "previewRating").property("text") == "Рейтинг: 8/20"
    assert (
        find_item(widget.quick, "previewDates").property("text")
        == "01 Январь 1200 — Бессрочно"
    )
    assert find_item(widget.quick, "previewAge").property("text") == "Возраст: 3 года"
    assert find_item(widget.quick, "previewMusicLabel").property("text") == "Музыка:"
    assert (
        find_item(widget.quick, "previewMusic").property("text")
        == "https://example.com/song"
    )

    # The four text sections, in render order, captions included.
    for key, caption in (
        ("characteristics", "Характеристики:"),
        ("backstory", "Предыстория:"),
        ("personality", "Личность:"),
        ("tasks", "Задачи:"),
    ):
        block = find_item(widget.quick, f"previewSection_{key}")
        labels = [
            i for i in walk_items(block) if i.objectName() == "previewSectionLabel"
        ]
        assert [i.property("text") for i in labels] == [caption]
        assert block.property("visible") is True


def test_identity_band_seats_the_short_fields_right_of_the_picture(qtbot):
    # Live fix 4.6 (the reader's sketch): the card opens with a band — the
    # picture top-left, the short lines to its right — and only below it the
    # long sections run full width.
    widget = _preview(
        qtbot,
        "character",
        _entity(),
        now_vm=_NowStub(date(1203, 1, 1)),
    )
    picture = find_item(widget.quick, "previewImageBlock")
    top_left = picture.mapToScene(QPointF(0, 0))
    for name in ("previewName", "previewRating", "previewDates", "previewAge"):
        pos = find_item(widget.quick, name).mapToScene(QPointF(0, 0))
        assert pos.x() >= top_left.x() + picture.width(), name
        assert top_left.y() <= pos.y() < top_left.y() + picture.height(), name
    # The long text starts under the whole band, not beside the picture.
    section = find_item(widget.quick, "previewSection_characteristics")
    assert section.mapToScene(QPointF(0, 0)).y() >= top_left.y() + picture.height()


@pytest.mark.parametrize("width", [420, 720])
def test_picture_takes_half_the_band_and_scales_with_the_column(qtbot, width):
    # The reader's sketch rule (live fix 2026-09-28): no fixed-pixel cap —
    # the picture block is exactly half of the identity band and its height
    # keeps the portrait 4:3 proportion, so dragging the splitter resizes
    # the picture together with the column.
    widget = _preview(qtbot, "character", _entity(), size=(width, 1600))
    row = find_item(widget.quick, "previewIdentityRow")
    picture = find_item(widget.quick, "previewImageBlock")
    assert abs(picture.width() - row.width() / 2) <= 1.0
    assert abs(picture.height() - picture.width() * 4 / 3) <= 1.0


def test_the_content_breathes_the_token_inset_off_every_border(qtbot):
    """Live bug 2026-09-30 (the user's screenshot): every text of the shown
    card glued itself to a border — the «Карточка: …» band to the column's
    left edge, the long sections to the canvas hairline on the right, the last
    relation block to the bottom. The whole content now rides one token
    (space.sm — the padding the library card exposes for its children): the
    header line steps in by it, and the scroll viewport sits one padding plus
    the 1px hairline inside the canvas on all four sides, so nothing paints on
    a border. The band's TOP inset stays the shared space.xs (the header axis
    of the three columns, pinned in test_panel_header_band.py)."""
    widget = _preview(
        qtbot,
        "character",
        _linked_character(),
        now_vm=_NowStub(date(1203, 1, 1)),
        size=(420, 1600),  # tall enough that the composition never scrolls
    )
    pad = _token_px("space.sm")
    # The zero-pins single pane's canvas carries the objectName the old
    # single-card column wore (previewCanvas became the empty-live panel).
    canvas = find_item(widget.quick, "previewPaneCanvas")
    scroll = find_item(widget.quick, "previewScroll")
    canvas_pos = canvas.mapToScene(QPointF(0, 0))
    scroll_pos = scroll.mapToScene(QPointF(0, 0))
    inset = 1 + pad  # the card's hairline + its content padding

    # The viewport is inset by the padding on every side of the canvas…
    assert abs(scroll_pos.x() - (canvas_pos.x() + inset)) <= 1.0
    assert abs(scroll_pos.y() - (canvas_pos.y() + inset)) <= 1.0
    assert abs(canvas_pos.x() + canvas.width() - inset
               - (scroll_pos.x() + scroll.width())) <= 1.0
    assert abs(canvas_pos.y() + canvas.height() - inset
               - (scroll_pos.y() + scroll.height())) <= 1.0

    # …the band caption steps in by the padding from the island's frame…
    band_title = find_item(widget.quick, "previewPaneTitle")
    band_pos = band_title.mapToScene(QPointF(0, 0))
    assert abs(band_pos.x() - (_token_px("space.xs") + pad)) <= 1.0

    # …and every readable line of the card stays inside the padded rect, the
    # long sections and the music link included (nothing cut at the edge).
    viewport_right = scroll_pos.x() + scroll.width()
    viewport_bottom = scroll_pos.y() + scroll.height()
    readable = [find_item(widget.quick, name) for name in (
        "previewName", "previewRating", "previewDates", "previewAge",
        "previewMusic",
    )]
    readable += [
        *find_items(widget.quick, "previewSectionText"),
        *find_items(widget.quick, "previewRelatedLabel"),
        *_related_rows(widget),
    ]
    assert len(readable) >= 10
    for item in readable:
        pos = item.mapToScene(QPointF(0, 0))
        assert pos.x() >= scroll_pos.x() - 1.0, item.objectName()
        assert pos.x() + item.width() <= viewport_right + 1.0, item.objectName()
        assert pos.y() >= scroll_pos.y() - 1.0, item.objectName()
        assert (
            item.mapToScene(QPointF(0, item.height())).y()
            <= viewport_bottom + 1.0
        ), item.objectName()


def test_body_text_reads_two_px_above_the_md_token(qtbot):
    # The readability step-up (the reader's request 2026-09-28): every
    # readable line of the card — the short fields, a section body, the
    # music link — rides the skin's md plus two px (13 + 2), while the
    # library titles keep the shared look.
    widget = _preview(
        qtbot,
        "character",
        _entity(),
        now_vm=_NowStub(date(1203, 1, 1)),
    )
    section_texts = [
        i
        for i in walk_items(find_item(widget.quick, "previewSection_backstory"))
        if i.objectName() == "previewSectionText"
    ]
    assert len(section_texts) == 1
    readable = {
        "previewRating": find_item(widget.quick, "previewRating"),
        "previewDates": find_item(widget.quick, "previewDates"),
        "previewAge": find_item(widget.quick, "previewAge"),
        "previewMusic": find_item(widget.quick, "previewMusic"),
        "previewSectionText": section_texts[0],
    }
    for name, item in readable.items():
        assert int(item.property("font").pixelSize()) == 15, name


def test_no_editable_control_lives_on_the_island(qtbot):
    # Read-only by contract (spec «редактируемых контролов … быть НЕ SHALL»):
    # no input control of any kind is instantiated anywhere in the scene —
    # the rows are plain Text/Item/MouseArea faces.
    widget = _preview(qtbot, "character", _entity())
    classes = sorted(
        i.metaObject().className() for i in walk_items(widget.quick.rootObject())
    )
    forbidden = (
        "TextField",
        "TextArea",
        "TextInput",
        "TextEdit",
        "SpinBox",
        "CheckBox",
        "Switch",
        "Slider",
        "ComboBox",
        "Dial",
        "TabButton",
        "RadioButton",
    )
    offenders = [c for c in classes for f in forbidden if f in c]
    assert offenders == []


@pytest.mark.parametrize("type_key", ["organization", "item", "location"])
def test_types_without_a_field_never_paint_its_row(qtbot, type_key):
    widget = _preview(qtbot, type_key, _entity(type_key))
    # «Личность» is the character's attribute — never built for the others.
    assert find_items(widget.quick, "previewSection_personality") == []
    if type_key == "item":
        # Spec scenario «У предмета нет чужих полей».
        assert find_items(widget.quick, "previewSection_tasks") == []
        assert find_items(widget.quick, "previewSection_characteristics") != []
    else:
        assert find_items(widget.quick, "previewSection_tasks") != []


def test_absent_values_leave_their_rows_out(qtbot):
    entity = _entity(description=_desc("", ""), personality="", tasks="", music_url="")
    widget = _preview(qtbot, "character", entity)
    # The text sections are Repeater children — no value, no item at all.
    for name in (
        "previewSection_characteristics",
        "previewSection_backstory",
        "previewSection_personality",
        "previewSection_tasks",
    ):
        assert find_items(widget.quick, name) == [], name
    # The music pair is a fixed row of the composition — an absent link
    # leaves it out of sight.
    assert _visible(widget, "previewMusicLabel") == [False]
    assert _visible(widget, "previewMusic") == [False]


def test_long_text_stays_scrollable(qtbot):
    entity = _entity(description=_desc("К " * 4000, "длинная предыстория"))
    widget = _preview(qtbot, "character", entity, size=(420, 520))
    scroll = find_item(widget.quick, "previewScroll")
    # The whole composition is one column inside the flickable; a long field
    # pushes the content past the viewport, so a scroll range exists and the
    # content actually moves when scrolled (task 4.2 «прокрутка длинного
    # текста»).
    assert scroll.property("contentHeight") > scroll.property("height")
    scroll.setProperty("contentY", 100.0)
    assert scroll.property("contentY") > 0.0


# ── task 4.3: the picture slot and its viewer gesture ───────────────────────


class _ViewerRecorder:
    """Stand-in viewer: the constructor records the (original, preview,
    parent, theme) package; the sheet show is the panel's ``sheet_requested``
    emission (NRI-0024 task 2.5 — the viewer left exec())."""

    calls: list = []

    def __init__(self, original, preview, parent=None, theme=None):
        type(self).calls.append((original, preview, parent, theme))


@pytest.fixture()
def viewer_recorder(monkeypatch):
    _ViewerRecorder.calls = []
    monkeypatch.setattr(preview_module, "ImageViewerDialog", _ViewerRecorder)
    monkeypatch.setattr(preview_module, "load_entity_original", lambda e: "original")
    monkeypatch.setattr(
        preview_module,
        "load_entity_preview",
        lambda e, slot_size: ("preview", slot_size),
    )
    return _ViewerRecorder.calls


def _written_preview(tmp_path, monkeypatch):
    """A real preview file through the shared pipeline (no load monkeypatch):
    the VM's slot-size load and the QML file URL both run for real."""
    sha = "a" * 64
    image_dir = tmp_path / "images"
    preview_file = image_dir / sha[:2] / f"{sha}.preview.webp"
    preview_file.parent.mkdir(parents=True)
    img = QImage(20, 20, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.red)
    assert img.save(str(preview_file))
    monkeypatch.setattr(image_utils, "_image_dir", image_dir)
    return SimpleNamespace(sha256=sha, ext="png")


def test_image_slot_paints_and_click_opens_the_card_viewer(
    qtbot, tmp_path, monkeypatch, viewer_recorder
):
    image_ref = _written_preview(tmp_path, monkeypatch)
    widget = _preview(qtbot, "location", _entity("location", image_ref=image_ref))

    image = find_item(widget.quick, "previewImage")
    assert image.property("visible") is True
    assert ".preview.webp" in str(image.property("source"))
    assert (
        find_item(widget.quick, "previewImagePlaceholder").property("visible")
        is False
    )

    requested: list = []
    widget.sheet_requested.connect(requested.append)
    _click(widget, find_item(widget.quick, "previewImageMouseArea"))
    assert len(requested) == 1
    assert isinstance(requested[0], _ViewerRecorder)
    original, preview, parent, _theme = viewer_recorder[0]
    assert original == "original"
    # The 4096 slot the card's viewer uses (the picture's click rides the
    # same full-size posture, task 4.3).
    assert preview == ("preview", 4096)
    assert parent is widget
    # The picture click never selects or loads anything (the island has no
    # selection; the wiring owns the bus).
    assert widget.vm.panes[0]["nameText"] == "Банн"


def test_image_press_action_opens_the_same_viewer(
    qtbot, tmp_path, monkeypatch, viewer_recorder
):
    image_ref = _written_preview(tmp_path, monkeypatch)
    widget = _preview(qtbot, "character", _entity(image_ref=image_ref))
    image = find_item(widget.quick, "previewImage")

    iface = _accessible(image)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Description) == "Открыть изображение"

    requested: list = []
    widget.sheet_requested.connect(requested.append)
    _press(image)
    assert len(requested) == 1
    assert isinstance(requested[0], _ViewerRecorder)


def test_missing_link_shows_the_no_image_placeholder(qtbot):
    widget = _preview(qtbot, "character", _entity())
    placeholder = find_item(widget.quick, "previewImagePlaceholder")
    assert placeholder.property("text") == "Нет изображения"
    assert placeholder.property("visible") is True
    assert find_item(widget.quick, "previewImage").property("visible") is False
    # With nothing painted the picture is not a target either (its MouseArea
    # is disabled and leaves the scene).
    assert find_item(widget.quick, "previewImageMouseArea").property("enabled") is False


def test_unavailable_file_degrades_to_the_placeholder_and_the_viewer_survives(
    qtbot, tmp_path, monkeypatch, viewer_recorder
):
    # The broken-file half of task 4.3: a link whose preview file is absent
    # rides the shared pipeline — a null pixmap arrives, so the slot paints
    # the placeholder even though the entity "has" an image.
    monkeypatch.setattr(image_utils, "_image_dir", tmp_path / "images")
    widget = _preview(
        qtbot,
        "character",
        _entity(image_ref=SimpleNamespace(sha256="b" * 64, ext="png")),
    )
    assert widget.vm.panes[0]["imageSource"] == ""
    assert (
        find_item(widget.quick, "previewImagePlaceholder").property("visible") is True
    )
    # The picture itself is not clickable (nothing is painted), so the open
    # arrives the way the accessibility press drives it; the click then hands
    # the viewer the real (null) loads, never an exception — its own
    # unavailable flag answers (pinned in tests/test_image_viewer.py).
    monkeypatch.setattr(preview_module, "load_entity_original", lambda e: QPixmap())
    monkeypatch.setattr(
        preview_module, "load_entity_preview", lambda e, slot_size: QPixmap()
    )
    requested: list = []
    widget.sheet_requested.connect(requested.append)
    # The pane names itself on the request (the NRI-0025 per-pane gesture).
    widget.vm.requestImageFor("character", 4, False)
    assert len(requested) == 1
    assert isinstance(requested[0], _ViewerRecorder)
    original, preview, _, _ = viewer_recorder[0]
    assert original.isNull() and preview.isNull()


# ── task 4.4: compact relation sections with the transition contract ────────


def _linked_character():
    character = _entity()
    character.items = [SimpleNamespace(id=11, name="Кинжал")]
    character.locations = [
        SimpleNamespace(id=12, name="Пещера"),
        SimpleNamespace(id=13, name="Замок"),
    ]
    return character


def _related_rows(widget):
    rows = find_items(widget.quick, "previewRelatedRow")
    rows.sort(key=lambda r: r.mapToScene(QPointF(0, 0)).y())
    return rows


def test_relation_sections_follow_the_registry_and_skip_the_empty_ones(qtbot):
    widget = _preview(qtbot, "character", _linked_character())

    assert find_items(widget.quick, "previewRelatedSection_items") != []
    assert find_items(widget.quick, "previewRelatedSection_locations") != []
    # «Нет связей — нет блока»: the empty organizations section is not built.
    assert find_items(widget.quick, "previewRelatedSection_organizations") == []

    labels = {
        i.property("text")
        for i in walk_items(widget.quick.rootObject())
        if i.objectName() == "previewRelatedLabel"
    }
    assert labels == {"Предметы:", "Локации:"}

    assert [r.property("text") for r in _related_rows(widget)] == [
        "Кинжал",
        "Пещера",
        "Замок",
    ]


def test_an_entity_without_links_paints_no_relation_block(qtbot):
    widget = _preview(qtbot, "character", _entity())
    assert find_items(widget.quick, "previewRelatedRow") == []
    assert [
        i.objectName()
        for i in walk_items(widget.quick.rootObject())
        if i.objectName().startswith("previewRelatedSection_")
    ] == []


def test_relation_row_click_selects_through_the_bus(qtbot):
    widget = _preview(qtbot, "character", _linked_character())
    requested = track(widget.entity_requested)

    _click(widget, _related_rows(widget)[1])  # «Пещера» — first locations row

    assert requested == [("location", 12)]
    # The island never loads or shows the target itself (design D2): the bus
    # is the whole story until the wiring answers.
    assert widget.vm.panes[0]["nameText"] == "Банн"


def test_relation_row_press_carries_the_transition_contract(qtbot):
    widget = _preview(qtbot, "character", _linked_character())
    requested = track(widget.entity_requested)

    row = _related_rows(widget)[0]  # «Кинжал»
    iface = _accessible(row)
    assert iface.role() == QAccessible.Role.ListItem  # the library row's role
    assert iface.text(QAccessible.Name) == "Кинжал"
    assert iface.text(QAccessible.Description) == "Переходит к сущности"

    _press(row)
    assert requested == [("item", 11)]


# ── task 4.5: mention anchors in the read-only text ─────────────────────────


def _mention_backstory():
    # The anchor sits at the very start so its link rect is addressable
    # offscreen without text-metric guessing.
    return _desc("", "@[Волк](organization:2) — давний враг")


def _backstory_text(widget):
    # The anchor lives in the «Предыстория» section — address its text inside
    # that section's block, not by the shared delegate objectName.
    block = find_item(widget.quick, "previewSection_backstory")
    texts = [i for i in walk_items(block) if i.objectName() == "previewSectionText"]
    assert len(texts) == 1
    return texts[0]


def _click_backstory_link(widget) -> None:
    _click(widget, _backstory_text(widget), pos=QPointF(8, 8))  # first-line anchor


def test_mention_anchor_click_feeds_the_selection_bus(qtbot):
    widget = _preview(qtbot, "character", _entity(description=_mention_backstory()))
    requested = track(widget.entity_requested)

    text = _backstory_text(widget)
    html = str(text.property("text"))
    # The same generator the unit file pins: the scheme anchor inside the
    # RichText the island paints (task 4.5 «те же HTML-ссылки»).
    assert 'href="nri://organization/2"' in html
    # (the RichText format itself needs no separate read — a PlainText label
    # never navigates, so the click below IS the format pin)

    _click_backstory_link(widget)
    assert requested == [("organization", 2)]
    assert widget.vm.panes[0]["nameText"] == "Банн"  # the island only emits


def test_a_dead_anchor_navigates_nothing_and_never_breaks_the_preview(qtbot):
    # The deleted-target half (spec «Если упомянутая сущность удалена,
    # активация SHALL не ломать предпросмотр»): the island cannot know the
    # target is gone — it emits exactly once and, with no answer from the
    # wiring, the shown card stays untouched and intact.
    widget = _preview(qtbot, "character", _entity(description=_mention_backstory()))
    requested = track(widget.entity_requested)

    _click_backstory_link(widget)
    QApplication.processEvents()

    assert requested == [("organization", 2)]
    assert len(widget.vm.panes) == 1
    assert find_item(widget.quick, "previewName").property("text") == "Банн"
    assert find_item(widget.quick, "previewEmptyHint").property("visible") is False


def test_foreign_hrefs_are_a_silent_no_op(qtbot):
    # A marker the generator never produced (a stale fragment, an external
    # URL) arrives at the same slot; the island stays exactly where it was.
    widget = _preview(qtbot, "character", _entity())
    requested = track(widget.entity_requested)
    widget.vm.requestLink("https://example.com/song")
    widget.vm.requestLink("nri://character/abc")
    assert requested == []
    assert widget.vm.panes[0]["nameText"] == "Банн"


def test_rich_text_mentions_are_a_documented_tree_limit(qtbot):
    """Fixed limit ⑥ (AGENTS.md registry, recorded in NRI-0022 task 7.1):
    in Qt 6.10 a link inside a Text.RichText paragraph gets no own
    accessibility node — a probe of the section text answers no interface
    at all (pinned below), so the mention wording «Открывает упомянутую
    сущность» can never be read off the preview's anchors. The navigation
    itself is real (the click pins above; onLinkActivated is the mouse
    path), it is only the tree face that stays silent; the wording
    survives on the MentionField chips, where a mention IS an Item
    (tests/presentation/test_mention_field_qml.py). Should a future Qt
    give RichText links their own nodes, this pin fires and the limit ⑥
    retires in that change."""
    entity = _linked_character()
    entity.description = _mention_backstory()
    widget = _preview(qtbot, "character", entity)

    # The paragraph carrying the anchor: no interface, no per-link child —
    # the very fact the limit records.
    assert QAccessible.queryAccessibleInterface(_backstory_text(widget)) is None

    descriptions = [
        text
        for item in walk_items(widget.quick.rootObject())
        if (iface := QAccessible.queryAccessibleInterface(item)) is not None
        and (text := iface.text(QAccessible.Description))
    ]
    # The walk is non-vacuous: the relation rows DO reach the tree with
    # their map word («Переходит к сущности», task 4.4).
    assert "Переходит к сущности" in descriptions
    # And nowhere does the unreachable mention wording appear.
    assert not [d for d in descriptions if "упомянут" in d.lower()]


# ── NRI-0025 task 4.1: the pane stack — equal shares, fixed bands, scrolls ───


def _slots(
    qtbot,
    pins: list[tuple[str, object]],
    live: tuple[str, object] | None,
    size=(420, 1400),
    now_vm=None,
) -> EntityPreviewWidget:
    """A shown preview island fed one slot frame (the wiring's channel
    since group 5; the pre-split tests above feed their one live card as a
    zero-pins frame — the same single-card column)."""
    widget = EntityPreviewWidget(now_date_vm=now_vm)
    qtbot.addWidget(widget)
    widget.resize(*size)
    widget.show_slots(pins, live)
    widget.show()
    QApplication.processEvents()
    return widget


def _pane_items(widget) -> list:
    return sorted(
        (
            i
            for i in walk_items(widget.quick.rootObject())
            if i.objectName().startswith("previewPane_")
        ),
        key=lambda i: i.mapToScene(QPointF(0, 0)).y(),
    )


@pytest.mark.parametrize("cards", [1, 2, 3, 4])
def test_visible_cards_divide_the_column_in_equal_shares(qtbot, cards):
    # spec preview-pins «Видимые карточки SHALL делить высоту колонки
    # поровну» (checkpoint п.1: panes are separated by space.sm air, the
    # pane floor is 88 px — never selected at this test height).
    pins = [("character", _entity(id=i)) for i in range(1, cards)]
    live = ("character", _entity(id=100))
    widget = _slots(qtbot, pins, live)

    panes = _pane_items(widget)
    assert len(panes) == cards  # pinned cards + the live card, no more
    heights = [p.height() for p in panes]
    assert max(heights) - min(heights) <= 1.0, heights
    assert min(heights) >= 88
    # the checkpoint's air between panes; inside a pane the band-to-canvas
    # step stays space.xs (asserted by the band/scroll geometry below)
    gap = _token_px("space.sm")
    for prev, nxt in zip(panes, panes[1:]):
        y0 = prev.mapToScene(QPointF(0, 0)).y() + prev.height()
        y1 = nxt.mapToScene(QPointF(0, 0)).y()
        assert abs(y1 - y0 - gap) <= 1.0
    # the pane count reads exactly through the objectName contract
    for index in range(cards):
        assert find_item(widget.quick, f"previewPane_{index}") is panes[index]


def test_a_single_pane_fills_the_whole_column(qtbot):
    # Task 4.1 «один pane = вся колонка (внешне как сегодня)»: with zero
    # pins the live card alone owns the column, the empty-live panel is out
    # of the layout and the column-wide band has stepped off (checkpoint п.2).
    widget = _slots(qtbot, [], ("character", _entity()))
    (pane,) = _pane_items(widget)
    root = widget.quick.rootObject()
    margin = _token_px("space.xs")
    assert abs(pane.height() - (root.height() - 2 * margin)) <= 1.0
    assert bool(find_item(widget.quick, "previewHeaderBand").property("visible")) is False
    assert bool(find_item(widget.quick, "previewCanvas").property("visible")) is False


def test_every_pane_scrolls_independently_under_its_fixed_band(qtbot):
    # Task 4.1 «независимая прокрутка каждого pane-а» + checkpoint п.1:
    # the band lies OUTSIDE the flickable, so scrolling structurally cannot
    # reach under it and one pane's offset never moves its siblings.
    long_desc = _desc("К " * 4000, "длинная предыстория")
    pins = [("character", _entity(id=1, description=_desc("П " * 4000, "еще")))]
    widget = _slots(qtbot, pins, ("character", _entity(id=2, description=long_desc)),
                    size=(420, 600))

    scrolls = sorted(
        find_items(widget.quick, "previewScroll"),
        key=lambda s: s.mapToScene(QPointF(0, 0)).y(),
    )
    assert len(scrolls) == 2
    assert scrolls[0].property("contentHeight") > scrolls[0].property("height")

    band = find_item(widget.quick, "previewPaneBand_0")
    pane = _pane_items(widget)[0]
    band_y = band.mapToScene(QPointF(0, 0)).y()
    assert abs(band_y - pane.mapToScene(QPointF(0, 0)).y()) <= 1.0  # top of the pane
    scroll_y = scrolls[0].mapToScene(QPointF(0, 0)).y()
    # band 32 + the pane's space.xs step + the viewport's hairline-1 +
    # space.sm inset inside the canvas (the island's one padding token).
    assert abs(
        scroll_y - band_y - BAND - _token_px("space.xs")
        - 1 - _token_px("space.sm")
    ) <= 1.0

    scrolls[0].setProperty("contentY", 120.0)
    QApplication.processEvents()
    assert scrolls[0].property("contentY") > 0.0
    assert scrolls[1].property("contentY") == 0.0  # the sibling did not move
    assert band.mapToScene(QPointF(0, 0)).y() == band_y  # the band stayed fixed


def test_the_first_pane_band_holds_the_columns_header_axis(qtbot):
    # Checkpoint п.2 / delta «Заголовок предпросмотра»: from the first pane
    # its own band takes the three-column header axis — the same 32 px band
    # at the same space.xs top inset the retired column band used (the
    # axis itself is pinned across the columns in test_panel_header_band.py).
    widget = _slots(qtbot, [("character", _entity(id=1))], ("character", _entity(id=2)))
    band = find_item(widget.quick, "previewPaneBand_0")
    assert abs(band.mapToScene(QPointF(0, 0)).y() - TOP_MARGIN) <= 1.0
    assert band.height() == BAND


def test_a_cramped_pane_caps_the_name_while_a_roomy_one_wraps_free(qtbot):
    # Checkpoint п.6 (the top-slice readability rule): on a pane whose
    # canvas drops under 110 px the name caps at two elided lines, so long
    # names cannot push the rating/dates/age past the top slice; a roomy
    # pane keeps the uncapped wrap (the height test itself rides the scroll
    # viewport, the cap is the delegate's own binding).
    def _by_y(items):
        return sorted(items, key=lambda i: i.mapToScene(QPointF(0, 0)).y())

    tall = _preview(qtbot, "character", _entity())
    scroll = find_item(tall.quick, "previewScroll")
    assert scroll.height() >= 110
    assert int(find_item(tall.quick, "previewName").property("maximumLineCount")) == 0

    # Four panes on a deliberately short column: each canvas falls below the
    # 110 px threshold (the 88 px floor caps the pane, the canvas is 88 minus
    # the band and insets) and every pane's name gets the two-line cap.
    pins = [("character", _entity(id=i)) for i in (1, 2, 3)]
    short = _slots(qtbot, pins, ("character", _entity(id=4)), size=(420, 420))
    names = _by_y(find_items(short.quick, "previewName"))
    scrolls = _by_y(find_items(short.quick, "previewScroll"))
    assert len(names) == 4 and len(scrolls) == 4
    for name, pane_scroll in zip(names, scrolls):
        assert pane_scroll.height() < 110, pane_scroll.height()
        assert int(name.property("maximumLineCount")) == 2


# ── NRI-0025 task 4.2: the band's pin — four names, inactivity, one Press ────

PIN_HINT_TEXT = "Выберите сущность — здесь появится её карточка"

_PIN_FRAMES = {
    # frame: (pins, live, per-slot expectations [(label, enabled), ...])
    "live-only": (
        [],
        ("character", _entity(id=9)),
        [("Закрепить карточку", True)],
    ),
    "pinned": (
        [("character", _entity(id=7))],
        None,
        [("Открепить карточку", True)],
    ),
    "duplicate": (
        [("character", _entity(id=4))],
        ("character", _entity(id=4)),  # same pair — a live second copy
        [("Открепить карточку", True), ("Уже закреплена", False)],
    ),
    "limit": (
        [("character", _entity(id=i)) for i in (1, 2, 3)],
        ("character", _entity(id=9)),  # a fourth, new entity
        [("Открепить карточку", True)] * 3
        + [("Можно закрепить только 3 карточки", False)],
    ),
}


@pytest.mark.parametrize("frame", sorted(_PIN_FRAMES))
def test_the_pin_carries_its_state_as_name_tooltip_role_and_enabled(qtbot, frame):
    # Design Д5 / spec preview-pins «Кнопка-булавка…»: exactly four fixed
    # formulations, the NAME states the button's very state; the tooltip
    # declaration carries the same string (limit ④: it never reaches the
    # tree); NO description is spelled (the name names the action, so
    # DESCRIPTION_VOCABULARY stays closed — the guard pins this half).
    pins, live, expectations = _PIN_FRAMES[frame]
    widget = _slots(qtbot, pins, live)

    for index, (label, enabled) in enumerate(expectations):
        pin = find_item(widget.quick, f"previewPinButton_{index}")
        assert bool(pin.property("enabled")) is enabled, index
        iface = _accessible(pin)
        assert iface.role() == QAccessible.Role.Button, index  # the Button seat
        assert iface.text(QAccessible.Name) == label, index
        assert iface.text(QAccessible.Description) == "", index
        attached = qmlAttachedPropertiesObject(Nri, pin, False)
        assert attached is not None and attached.tooltip == label, index


@pytest.mark.parametrize("frame", sorted(_PIN_FRAMES))
def test_the_pin_wears_its_state_in_the_face(qtbot, frame):
    # User request 2026-10-03 «нет визуального подтверждения что карточка
    # закреплена»: an un-pinned pin LEANS 45° right, a pinned card's pin
    # stands upright (the pre-fix look) and wears the accent colour. The
    # disabled duplicate/limit pins lean too (not pinned) and keep the
    # muted face — the library tint chain mutes disabled glyphs first.
    pins, live, expectations = _PIN_FRAMES[frame]
    widget = _slots(qtbot, pins, live)

    for index, (_label, enabled) in enumerate(expectations):
        pin = find_item(widget.quick, f"previewPinButton_{index}")
        pinned = index < len(pins)  # the frame's own slot law: pins first
        assert float(pin.property("iconRotation")) == (0.0 if pinned else 45.0), index
        assert bool(pin.property("iconAccentTint")) is pinned, index
        tint = pin.property("iconTint")
        if not enabled:
            assert tint == pin.property("mutedColor"), index
        elif pinned:
            assert tint == pin.property("accentColor"), index
        else:
            assert tint == pin.property("fgColor"), index
        # The angle reaches the drawn glyph through the component seat.
        glyph = [
            i
            for i in walk_items(pin)
            if i.objectName() == "themeButtonIcon"
        ]
        assert len(glyph) == 1, index
        assert float(glyph[0].property("glyphRotation")) == (
            0.0 if pinned else 45.0
        ), index


def test_pin_press_is_one_toggle_by_pair(qtbot):
    # The Press rides the component seat (ThemeIconButton ships the штатно
    # Button action — the NRI-0018/0023 contract), so an accessibility
    # activation is one real click: exactly ONE requestPinToggle per Press,
    # by pair with the card's current pinned state (design Д2). The pattern
    # is test_theme_checkbox_accessibility.py's measurement, on the island.
    widget = _slots(
        qtbot, [("location", _entity("location", id=8))], ("character", _entity(id=9))
    )
    toggles = track(widget.pin_toggle_requested)

    live_pin = find_item(widget.quick, "previewPinButton_1")
    _press(live_pin)
    assert toggles == [("character", 9, False)], (
        "one Press on the live pin must emit exactly one unpinned-pair toggle"
    )

    pinned_pin = find_item(widget.quick, "previewPinButton_0")
    _press(pinned_pin)
    assert toggles == [
        ("character", 9, False),
        ("location", 8, True),
    ], "the pinned pane's Press must carry pinned=True by pair"


def test_the_disabled_pin_still_answers_the_hover_with_its_wording(qtbot):
    # Spec «Неактивная булавка … SHALL нести подсказку и имя»: the tooltip
    # is the ghost face's only hover answer (норма Д12), and a disabled
    # button keeps receiving hover (probed offscreen) — so the capacity and
    # duplicate wordings reach the reader through the bridge.
    widget = _slots(
        qtbot, [("character", _entity(id=4))], ("character", _entity(id=4))
    )
    bridge = widget._tooltip_bridge
    pin = find_item(widget.quick, "previewPinButton_1")
    assert bool(pin.property("enabled")) is False

    center = pin.mapToScene(QPointF(pin.width() / 2, pin.height() / 2))
    QTest.mouseMove(widget.quick, QPoint(round(center.x()), round(center.y())))
    qtbot.waitUntil(
        lambda: bridge.last_request is not None
        and bridge.last_request[0] == "Уже закреплена",
        timeout=5000,
    )

    # Leaving releases the tooltip (the shim's empty-text posture).
    QTest.mouseMove(widget.quick, QPoint(2, 2))
    qtbot.waitUntil(
        lambda: bridge.last_request is not None and bridge.last_request[0] == "",
        timeout=5000,
    )


# ── NRI-0025 task 4.3: the empty live area under the pins ────────────────────


@pytest.mark.parametrize("pin_count", [1, 2, 3])
def test_the_empty_live_area_hints_without_a_band_at_any_pane_count(
    qtbot, pin_count
):
    # Delta «Пустая живая область без заголовка» + checkpoint п.3: a
    # CardPanel without a band, the delta sentence wrapped, equal-height
    # citizenship (50/50 on the first pin), and the fully empty column's
    # hint stays silent. The live column with no card still counts within
    # 1–4 panes (pin_count cards + the hint block).
    pins = [("character", _entity(id=i)) for i in range(1, pin_count + 1)]
    widget = _slots(qtbot, pins, None)

    hint = find_item(widget.quick, "previewLiveEmptyHint")
    assert bool(hint.property("visible")) is True
    assert hint.property("text") == PIN_HINT_TEXT
    # The wrap needs its measure (checkpoint п.3): the hint rides the canvas
    # minus the island padding on both sides. The wrapMode itself is an enum
    # unreadable offscreen (the elide/wrapMode limitation known from
    # test_event_types_dialog.py) — the wrap is pinned functionally below.
    canvas = find_item(widget.quick, "previewCanvas")
    assert abs(
        hint.width() - (canvas.width() - 2 * _token_px("space.sm"))
    ) <= 1.0
    assert bool(find_item(widget.quick, "previewEmptyHint").property("visible")) is False
    assert bool(find_item(widget.quick, "previewHeaderBand").property("visible")) is False

    # No band, no pin of its own — those objectNames exist per pinned card
    # only, and the hint panel never gets the index the next pane would.
    assert find_items(widget.quick, f"previewPaneBand_{pin_count}") == []
    assert find_items(widget.quick, f"previewPinButton_{pin_count}") == []
    assert find_items(widget.quick, f"previewPane_{pin_count}") == []

    # Equal-height participation: the first pin split the column 50/50 with
    # the empty live area (spec scenario «Первое закрепление делит колонку»).
    panes = _pane_items(widget)
    assert abs(canvas.height() - panes[0].height()) <= 1.0
    assert canvas.height() >= 88


def test_a_live_card_replaces_the_empty_live_hint(qtbot):
    widget = _slots(
        qtbot, [("character", _entity(id=1))], ("character", _entity(id=2))
    )
    assert bool(find_item(widget.quick, "previewLiveEmptyHint").property("visible")) is False
    assert bool(find_item(widget.quick, "previewCanvas").property("visible")) is False
    assert len(_pane_items(widget)) == 2


def test_the_live_hint_wraps_rather_than_elides_on_a_narrow_column(qtbot):
    # Checkpoint п.3 (the 220 px splitter floor: elide ate half the phrase):
    # the wrapped layout is the observable half of the wrapMode the Python
    # side cannot read — on the column's minimum floor the sentence needs
    # more than one line, which a single-line (NoWrap/elide) Text never
    # grows into.
    widget = _slots(
        qtbot, [("character", _entity(id=1))], None, size=(220, 600)
    )
    hint = find_item(widget.quick, "previewLiveEmptyHint")
    assert bool(hint.property("visible")) is True
    assert hint.width() < 220  # the wrap's measure really is narrow
    line_height = hint.property("font").pixelSize() + 3  # a 13 px line is ~16
    assert hint.height() > 1.8 * line_height, (hint.height(), line_height)


# ── island lifecycle (the facade's teardown contract) ───────────────────────


def test_island_teardown_is_deferred_and_detaches_the_now(qtbot):
    now = _NowStub(date(1203, 1, 1))
    widget = _preview(qtbot, "character", _entity(), now_vm=now)
    assert widget.quick.rootObject() is not None

    widget.close()
    assert widget.quick.rootObject() is not None  # the release is deferred
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.wait(1)
    assert widget.quick.rootObject() is None
    assert widget.quick.source() == QUrl()
    # DEFECT-1 posture: the «now» subscription leaves with the island.
    assert widget.vm._now_vm is None


# ── 2026-10-03 scroll-reset fix: unchanged pins keep their scroll (QA report
# docs/qa/2026-10-03-preview-scroll-reset.md) ─────────────────────────────────
#
# The bug: any new frame recreated every pane delegate, so every pinned
# card's Flickable was a fresh one starting at the top. The fix pairs the
# Python slot identity (reused cards, revs) with the island's scroll memory
# keyed by slotKey; these pins walk the live island through the frames the
# connector pushes and read the offsets back through the object tree.


def _pane_child(widget, slot_index: int, child_name: str):
    """One addressed child of one addressed pane (each pane keeps its scroll
    and name inside itself, so identity is per-slot, never scene-order)."""
    pane = find_item(widget.quick, f"previewPane_{slot_index}")
    found = [i for i in walk_items(pane) if i.objectName() == child_name]
    assert len(found) == 1, (slot_index, child_name)
    return found[0]


def _scroll_of_pane(widget, slot_index: int):
    return _pane_child(widget, slot_index, "previewScroll")


def _name_of_pane(widget, slot_index: int) -> str:
    return str(_pane_child(widget, slot_index, "previewName").property("text"))


def _scroll_pane_to(widget, slot_index: int, offset: float) -> float:
    """Scroll one pane and hand back the position it actually took (the
    same measurement posture as test_long_text_stays_scrollable)."""
    scroll = _scroll_of_pane(widget, slot_index)
    scroll.setProperty("contentY", float(offset))
    QApplication.processEvents()
    return float(scroll.property("contentY"))


def _long_entity(index: int, **overrides):
    """A card whose text scrolls on any pane height the tests use."""
    overrides.setdefault("name", f"Сущ{index}")
    return _entity(
        id=index,
        description=_desc("К " * 4000, f"предыстория {index}"),
        **overrides,
    )


def test_a_new_live_selection_keeps_every_untouched_pins_scroll(qtbot):
    # The reproduction of the report: three pinned cards scrolled to three
    # different readings, then the user clicks a new entity — the connector
    # re-pushes the frame with the same three pins and a different live card.
    pins = [("character", _long_entity(i)) for i in (1, 2, 3)]
    widget = _slots(
        qtbot, pins, ("character", _long_entity(4)), size=(420, 700)
    )
    y0 = _scroll_pane_to(widget, 0, 150.0)
    y1 = _scroll_pane_to(widget, 1, 250.0)
    assert y0 > 0 and y1 > 0  # the scroll range really exists

    widget.show_slots(pins, ("character", _long_entity(5)))
    QApplication.processEvents()

    assert float(_scroll_of_pane(widget, 0).property("contentY")) == pytest.approx(y0, abs=1.0)
    assert float(_scroll_of_pane(widget, 1).property("contentY")) == pytest.approx(y1, abs=1.0)
    # The pin nobody scrolled and the fresh live card open from the top —
    # the QA report's «живая карточка при новом выборе — всегда с начала».
    assert float(_scroll_of_pane(widget, 2).property("contentY")) == 0.0
    assert _name_of_pane(widget, 3) == "Сущ5"
    assert float(_scroll_of_pane(widget, 3).property("contentY")) == 0.0

    # The duplicate scenario (spec «Дубль закреплённой сущности»): selecting
    # an already pinned entity as the live copy is a changed frame too — the
    # pins keep reading and the live copy opens from the top, NOT sharing the
    # pinned twin's remembered offset (the key carries the half).
    widget.show_slots(pins, ("character", _long_entity(1)))
    QApplication.processEvents()
    assert float(_scroll_of_pane(widget, 0).property("contentY")) == pytest.approx(y0, abs=1.0)
    assert float(_scroll_of_pane(widget, 1).property("contentY")) == pytest.approx(y1, abs=1.0)
    assert _name_of_pane(widget, 3) == "Сущ1"
    assert float(_scroll_of_pane(widget, 3).property("contentY")) == 0.0


def test_pinning_the_live_card_keeps_the_other_pins_reading(qtbot):
    # The connector's pin frame (design Д3): the live pair seats as the next
    # pin, the live area empties. The moving card itself may repaint from the
    # top (it is a new construction), the untouched pin must not move.
    a = _long_entity(1)
    live = _long_entity(2)
    widget = _slots(qtbot, [("character", a)], ("character", live), size=(420, 700))
    y0 = _scroll_pane_to(widget, 0, 180.0)
    assert y0 > 0

    widget.show_slots([("character", a), ("character", live)], None)
    QApplication.processEvents()

    assert float(_scroll_of_pane(widget, 0).property("contentY")) == pytest.approx(y0, abs=1.0)
    assert _name_of_pane(widget, 1) == "Сущ2"  # the card that moved up
    assert float(_scroll_of_pane(widget, 1).property("contentY")) == 0.0


def test_unpinning_a_middle_pin_keeps_the_survivors_offsets(qtbot):
    # Identity is the PAIR, not the position: unpinning B reindexes C from
    # slot 2 to slot 1, and C must come back to its own remembered offset —
    # a position-keyed memory would have handed C the offset of the
    # un-scrolled A and dropped its own.
    a = _long_entity(1)
    b = _long_entity(2)
    c = _long_entity(3)
    widget = _slots(
        qtbot,
        [("character", a), ("character", b), ("character", c)],
        None,
        size=(420, 700),
    )
    ya = _scroll_pane_to(widget, 0, 60.0)
    yc = _scroll_pane_to(widget, 2, 140.0)
    assert ya > 0 and yc > 0

    widget.show_slots([("character", a), ("character", c)], None)
    QApplication.processEvents()

    assert _name_of_pane(widget, 1) == "Сущ3"  # C really is slot 1 now
    assert float(_scroll_of_pane(widget, 0).property("contentY")) == pytest.approx(ya, abs=1.0)
    assert float(_scroll_of_pane(widget, 1).property("contentY")) == pytest.approx(yc, abs=1.0)


def test_a_saved_card_repaints_from_the_top_while_neighbours_keep_reading(qtbot):
    # Acceptance «сохранённая карточка … имеет право перерисоваться с нуля —
    # но соседние — нет»: A's row carries new rendered content (the save's
    # fingerprint differs → a new rev), so A's reborn delegate shows the new
    # content at the top, while B — same pair, same rendered fields, same
    # rev — is still scrolled.
    a = _long_entity(1)
    b = _long_entity(2)
    widget = _slots(
        qtbot, [("character", a), ("character", b)], None, size=(420, 700)
    )
    ya = _scroll_pane_to(widget, 0, 200.0)
    yb = _scroll_pane_to(widget, 1, 120.0)
    assert ya > 0 and yb > 0

    a_saved = _long_entity(1, name="Банн обновлённый")
    widget.show_slots([("character", a_saved), ("character", b)], None)
    QApplication.processEvents()

    assert _name_of_pane(widget, 0) == "Банн обновлённый"  # the fresh read
    assert float(_scroll_of_pane(widget, 0).property("contentY")) == 0.0
    assert float(_scroll_of_pane(widget, 1).property("contentY")) == pytest.approx(yb, abs=1.0)


def test_the_now_broadcast_repaints_ages_without_touching_the_offsets(qtbot):
    # The «now» broadcast rebuilds the painting of EVERY card (the age line
    # rides it) — but the cards are recounted in place, their revs survive,
    # so the memory restores every pinned pane exactly where the reader was.
    now = _NowStub(date(1203, 1, 1))
    a = _long_entity(1)
    b = _long_entity(2)
    widget = _slots(
        qtbot,
        [("character", a), ("character", b)],
        None,
        size=(420, 700),
        now_vm=now,
    )
    assert widget.vm.panes[0]["ageText"] == "Возраст: 3 года"
    ya = _scroll_pane_to(widget, 0, 100.0)
    yb = _scroll_pane_to(widget, 1, 50.0)
    assert ya > 0 and yb > 0

    now.coord = date(1210, 1, 1)
    now.nowChanged.emit()
    QApplication.processEvents()

    assert widget.vm.panes[0]["ageText"] == "Возраст: 10 лет"  # really repainted
    assert float(_scroll_of_pane(widget, 0).property("contentY")) == pytest.approx(ya, abs=1.0)
    assert float(_scroll_of_pane(widget, 1).property("contentY")) == pytest.approx(yb, abs=1.0)


# ── 2026-10-03 scroll-DRIFT fix: a remembered offset may arrive before the
# content height has settled (measured on the live island: a delegate's
# contentHeight sweeps 0 → partial → oversized → final while the pane height
# sweeps 0 → negative → settled). A restoration attempt that lands inside a
# transient — where the content cannot hold the offset — must stay armed and
# re-land the moment the height grows; a real user drag retires the wait. ────


def test_a_pending_restoration_waits_for_a_content_height_that_arrives_late(qtbot):
    # The delegate's birth sequence when the content is slower than the
    # first layout pass (RichText sections, images): the offset is already
    # remembered, the contentHeight is still viewport-short. The old
    # implementation cleared the pending offset even when NOTHING had been
    # applied, so the reborn card stayed wherever the transient left it.
    pins = [("character", _long_entity(1))]
    widget = _slots(qtbot, pins, ("character", _long_entity(2)), size=(420, 700))
    scroll = _scroll_of_pane(widget, 0)
    viewport = float(scroll.property("height"))
    assert viewport > 0.0

    scroll.setProperty("pendingRestoredY", 800.0)
    scroll.setProperty("contentHeight", viewport - 50.0)  # content not there yet
    assert float(scroll.property("contentY")) == pytest.approx(0.0, abs=1.0)

    # The content arrives: the remembered position must be taken exactly.
    scroll.setProperty("contentHeight", 3000.0)
    assert float(scroll.property("contentY")) == pytest.approx(800.0, abs=1.0)


def test_a_clamped_restoration_lands_exactly_when_the_content_grows_taller(qtbot):
    # The partial-progress posture stays: while the content is taller than
    # the viewport but shorter than the remembered position, the card reads
    # as far as it can — but the wait is NOT over: the exact position is
    # restored when the height arrives (drift: the old code cleared the
    # pending offset right after this clamp).
    pins = [("character", _long_entity(1))]
    widget = _slots(qtbot, pins, ("character", _long_entity(2)), size=(420, 700))
    scroll = _scroll_of_pane(widget, 0)
    viewport = float(scroll.property("height"))

    scroll.setProperty("pendingRestoredY", 800.0)
    scroll.setProperty("contentHeight", viewport + 300.0)  # taller, but short of 800
    y_clamped = float(scroll.property("contentY"))
    assert 0.0 < y_clamped < 800.0

    scroll.setProperty("contentHeight", 3000.0)
    assert float(scroll.property("contentY")) == pytest.approx(800.0, abs=1.0)


def test_a_user_drag_of_a_pane_drops_the_waiting_restoration(qtbot):
    # The reader's own gesture outranks an unlanded memory: once the pane
    # was really dragged, a later content-height change must not yank the
    # card back to the remembered offset.
    pins = [("character", _long_entity(1))]
    widget = _slots(qtbot, pins, ("character", _long_entity(2)), size=(420, 700))
    scroll = _scroll_of_pane(widget, 0)
    scroll.setProperty("pendingRestoredY", 800.0)

    scene = scroll.mapToScene(QPointF(60, 60))
    QTest.mousePress(
        widget.quick, Qt.MouseButton.LeftButton,
        pos=QPoint(round(scene.x()), round(scene.y())),
    )
    for step in range(1, 6):
        QTest.mouseMove(
            widget.quick, QPoint(round(scene.x()), round(scene.y()) - step * 12)
        )
    QTest.mouseRelease(
        widget.quick, Qt.MouseButton.LeftButton,
        pos=QPoint(round(scene.x()), round(scene.y()) - 60),
    )
    # Wait for the flick momentum to really stop: one equal pair of samples
    # can land inside a frame gap, so demand a short run of them.
    stable_runs = 0
    previous_y = None
    for _ in range(300):
        qtbot.wait(10)
        current_y = float(scroll.property("contentY"))
        stable_runs = stable_runs + 1 if current_y == previous_y else 0
        if stable_runs >= 5:
            break
        previous_y = current_y
    y_user = float(scroll.property("contentY"))
    assert y_user > 0.0  # the drag really moved the content

    scroll.setProperty("contentHeight", 3000.0)
    qtbot.wait(50)
    assert float(scroll.property("contentY")) == pytest.approx(y_user, abs=1.0)
