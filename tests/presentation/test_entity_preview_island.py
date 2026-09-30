"""Offscreen pins of the entity-preview island (NRI-0022, tasks 4.1–4.5).

The VM unit file pins the composition rules; this file proves the live island:
the single «Карточка…» band titled by the entity type, the self-explaining
empty state,
the read-only set for every type through the real QML items, the picture slot
with its viewer gesture (the 4096 card posture), the compact relation sections
with their Press contract («Переходит к сущности»), and the RichText mention
anchors whose click feeds the one selection bus without ever touching the
shown entity. The facade is dumb — the tests drive it exactly the way the
group-5 wiring will: show_entity/clear in, entity_requested out.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt, QUrl, Signal
from PySide6.QtGui import QAccessible, QImage, QPixmap
from PySide6.QtQml import QQmlEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.utils import image_utils
from app.presentation.views import entity_preview as preview_module
from app.presentation.views.entity_preview import EntityPreviewWidget
from tests.presentation.qml_helpers import find_item, find_items, track, walk_items


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
        widget.show_entity(entity_type or "character", entity)
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
    # The island is read-only: no tooltip bridge, no extra names — the two
    # context entries above are the whole surface (spec qml-shell).
    assert context.contextProperty("tooltipBridge") is None


def test_empty_state_explains_itself_without_a_type_title(qtbot):
    widget = _preview(qtbot)

    # In the empty state the one band reads the plain word (spec «Заголовок
    # предпросмотра — единственная строка заголовка»).
    band = find_item(widget.quick, "previewBandTitle")
    assert band.property("text") == "Карточка"
    assert band.property("visible") is True

    hint = find_item(widget.quick, "previewEmptyHint")
    assert hint.property("visible") is True
    assert hint.property("text") == (
        "Выберите сущность в среднем столбце — здесь появится её карточка"
    )
    # the themed face: the library's muted italic HintText (the detail
    # panel's empty-hint posture, task 4.1 «тематизированная подсказка»)
    assert hint.metaObject().className().startswith("HintText")

    # The second headline is gone from the island at all (the reader's fix
    # 2026-09-28), and so is the whole content column in this state.
    assert find_items(widget.quick, "previewTitle") == []
    assert _visible(widget, "previewScroll") == [False]
    assert widget.vm.hasEntity is False


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

    # The band IS the headline now — titled by the registry type name, with
    # the entity's own name staying a field inside, no inner duplicate.
    assert find_item(widget.quick, "previewBandTitle").property("text") == (
        f"Карточка: {label}"
    )
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
    assert widget.vm.shown_entity is None


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
    canvas = find_item(widget.quick, "previewCanvas")
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
    band_title = find_item(widget.quick, "previewBandTitle")
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
    calls: list = []

    def __init__(self, original, preview, parent=None, theme=None):
        type(self).calls.append((original, preview, parent, theme))

    def exec(self):
        type(self).calls.append("exec")


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

    _click(widget, find_item(widget.quick, "previewImageMouseArea"))
    assert viewer_recorder[-1] == "exec"
    original, preview, parent, _theme = viewer_recorder[0]
    assert original == "original"
    # The 4096 slot the card's viewer uses (the picture's click rides the
    # same full-size posture, task 4.3).
    assert preview == ("preview", 4096)
    assert parent is widget
    # The picture click never selects or loads anything (the island has no
    # selection; the wiring owns the bus).
    assert widget.vm.shown_entity.name == "Банн"


def test_image_press_action_opens_the_same_viewer(
    qtbot, tmp_path, monkeypatch, viewer_recorder
):
    image_ref = _written_preview(tmp_path, monkeypatch)
    widget = _preview(qtbot, "character", _entity(image_ref=image_ref))
    image = find_item(widget.quick, "previewImage")

    iface = _accessible(image)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Description) == "Открыть изображение"

    _press(image)
    assert viewer_recorder[-1] == "exec"


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
    assert widget.vm.imageSource == ""
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
    widget.vm.requestImage()
    assert viewer_recorder[-1] == "exec"
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
    assert widget.vm.shown_entity.name == "Банн"


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
    assert widget.vm.shown_entity.name == "Банн"  # the island only emits


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
    assert widget.vm.hasEntity is True
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
    assert widget.vm.shown_entity.name == "Банн"


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
