"""Sheet parity of the two creation sheets (change nri-0015, task group 3).

The event dialog and the entity card are siblings of the same family, so the
audit (E2, CR1/E3, CR3, CR4) held them to one contract, pinned here offscreen:

* labels — the shared caption form «<Имя>: *»: the colon on every caption and
  the «*» exactly on the sheet's mandatory fields (3.1); the full set of
  captions of both sheets is listed field→label below;
* the save gate — an empty mandatory name blocks the card the way it blocks
  the event (VM rule + the island button's enabled facet) (3.2);
* every ✨ AI button — its accessible name «Сгенерировать: <поле>» names the
  target of THIS sheet (the card wave names its entity type through the
  registry, never «Событие»), and the button itself sits inside the row of its
  target field, not in a separate row between blocks (3.3).

The AI buttons are never clicked here: a press would fire a real LLM request —
the contract pinned is the name and the position only.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QAccessible

from app.presentation.viewmodels.entity_card_island_view_model import (
    EntityCardIslandViewModel,
)
from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
)
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item, walk_items

# ── 3.1: the full caption map of each sheet, paired field→label ──────────────

EVENT_SHEET_LABELS = [
    ("eventNameField", "Название: *"),
    ("eventStartDateField", "Дата начала: *"),
    ("eventEndDateField", "Дата конца:"),
    ("eventTypeCombo", "Тип:"),
    ("eventCharacteristicsField", "Характеристики: *"),
    ("eventBackstoryField", "Предыстория: *"),
]

CARD_SHEET_LABELS = [
    ("entityNameField", "Название: *"),
    ("entityRatingSpin", "Рейтинг (1-20):"),
    ("entityStartDateField", "Дата начала:"),
    ("entityEndDateField", "Дата конца:"),
    ("entityCharacteristicsField", "Характеристики: *"),
    ("entityBackstoryField", "Предыстория:"),
    ("entityMusicField", "Музыка:"),
    ("entityExtraField_personality", "Личность:"),
    ("entityExtraField_tasks", "Задачи:"),
]

EVENT_MANDATORY_MARKED = {"Название: *", "Дата начала: *", "Характеристики: *",
                          "Предыстория: *"}
CARD_MANDATORY_MARKED = {"Название: *", "Характеристики: *"}

# ── 3.3: the usage-site AI table and the field rows they belong to ───────────

EVENT_AI_NAMES = [
    ("eventNameAiButton", "Сгенерировать: Название"),
    ("eventCharacteristicsAiButton", "Сгенерировать: Характеристики"),
    ("eventBackstoryAiButton", "Сгенерировать: Предыстория"),
    # The wave generates this sheet's entity as a whole — the event.
    ("eventEntityAiButton", "Сгенерировать: Событие"),
]

CARD_AI_NAMES = [
    ("entityNameAiButton", "Сгенерировать: Название"),
    ("entityCharacteristicsAiButton", "Сгенерировать: Характеристики"),
    ("entityBackstoryAiButton", "Сгенерировать: Предыстория"),
    ("entityExtraAiButton_personality", "Сгенерировать: Личность"),
    ("entityExtraAiButton_tasks", "Сгенерировать: Задачи"),
    # C1 (CR1/E3): the card's own target — the entity type, never «Событие».
    ("entityGenerateButton", "Сгенерировать: Персонаж"),
]

EVENT_AI_ROW_PAIRS = [
    ("eventNameField", "eventNameAiButton"),
    ("eventNameField", "eventEntityAiButton"),
    ("eventCharacteristicsField", "eventCharacteristicsAiButton"),
    ("eventBackstoryField", "eventBackstoryAiButton"),
]

CARD_AI_ROW_PAIRS = [
    ("entityNameField", "entityNameAiButton"),
    ("entityNameField", "entityGenerateButton"),
    ("entityCharacteristicsField", "entityCharacteristicsAiButton"),
    ("entityBackstoryField", "entityBackstoryAiButton"),
    ("entityExtraField_personality", "entityExtraAiButton_personality"),
    ("entityExtraField_tasks", "entityExtraAiButton_tasks"),
]


def _scene_rect(item):
    top_left = item.mapToScene(QPointF(0, 0))
    return top_left.x(), top_left.y(), item.width(), item.height()


def _title_texts(widget):
    """Every TitleText caption of the island (roleSize exists on TitleText
    only — the walk stays a plain property read, no interface probing)."""
    return [
        item
        for item in walk_items(widget.rootObject())
        if isinstance(item.property("roleSize"), str)
    ]


def _row_label(widget, field_object_name: str) -> str:
    """The TitleText caption painting the row of ``field_object_name``: a
    caption vertically centered on the field and fully to its left."""
    field = find_item(widget, field_object_name)
    fx, fy, fw, fh = _scene_rect(field)
    candidates = []
    for title in _title_texts(widget):
        tx, ty, tw, th = _scene_rect(title)
        center_y = ty + th / 2
        if fy - 3 <= center_y <= fy + fh + 3 and tx + tw <= fx + 1:
            candidates.append(title)
    assert len(candidates) == 1, (
        f"{field_object_name}: {len(candidates)} row captions "
        f"{[c.property('text') for c in candidates]}"
    )
    return candidates[0].property("text")


def _caption_set(widget):
    """All field captions of the sheet — the island's own header strip
    (sheetTitle) is the one non-field caption and is excluded by name."""
    root = widget.rootObject()
    header = root.property("sheetTitle")
    assert header, "the sheet header title must be threaded in"
    texts = [t.property("text") for t in _title_texts(widget)]
    assert texts.count(header) == 1
    return set(texts) - {header}


def _accessible_name(widget, object_name: str) -> str:
    iface = QAccessible.queryAccessibleInterface(find_item(widget, object_name))
    assert iface is not None, f"no accessibility interface on {object_name!r}"
    return iface.text(QAccessible.Name)


def _assert_button_in_field_row(widget, field_name: str, button_name: str) -> None:
    """The button belongs to the field's row: both share the row (their
    vertical centres coincide — items of one grid/layout row are centred
    together), and the button starts at or right of the field's right edge.
    A button parked in a row of its own between blocks misses the centre."""
    field = find_item(widget, field_name)
    button = find_item(widget, button_name)
    fx, fy, fw, fh = _scene_rect(field)
    bx, by, bw, bh = _scene_rect(button)
    assert bx >= fx + fw - 1, f"{button_name} overlaps its {field_name}"
    dy = abs((by + bh / 2) - (fy + fh / 2))
    assert dy <= 2, (
        f"{button_name} centre {by + bh / 2} not on the {field_name} centre "
        f"{fy + fh / 2} (dy={dy})"
    )


# ── 3.1 ───────────────────────────────────────────────────────────────────────


def test_event_sheet_captions_carry_the_shared_form(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.show()

    assert _caption_set(dialog.quick) == {label for _field, label in EVENT_SHEET_LABELS}
    for field_name, expected in EVENT_SHEET_LABELS:
        assert _row_label(dialog.quick, field_name) == expected
    # E2: every caption ends with the colon; the «*» marks exactly the
    # mandatory fields — no required caption is bare.
    for caption in _caption_set(dialog.quick):
        assert caption.endswith(":") or caption.endswith(": *")
    assert {c for c in _caption_set(dialog.quick) if "*" in c} == EVENT_MANDATORY_MARKED


def test_card_sheet_captions_carry_the_shared_form(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.show()

    assert _caption_set(dialog.quick) == {label for _field, label in CARD_SHEET_LABELS}
    for field_name, expected in CARD_SHEET_LABELS:
        assert _row_label(dialog.quick, field_name) == expected
    for caption in _caption_set(dialog.quick):
        assert caption.endswith(":") or caption.endswith(": *")
    assert {c for c in _caption_set(dialog.quick) if "*" in c} == CARD_MANDATORY_MARKED


# ── 3.2 ───────────────────────────────────────────────────────────────────────


def test_card_save_gate_mirrors_the_empty_name_rule_of_the_event(qtbot):
    vm = EntityCardIslandViewModel("character", [], [])
    emitted: list = []
    vm.saveRequested.connect(lambda: emitted.append(True))

    assert not vm.saveEnabled  # the fresh card: mandatory name empty
    vm.name = "   "
    assert not vm.saveEnabled  # blanks never satisfy the mandatory field
    vm.requestSave()
    assert emitted == []

    vm.name = "Герой"
    assert vm.saveEnabled
    vm.requestSave()
    assert emitted == [True]

    # The other gate facets keep working on top of the name rule.
    vm.set_save_locked(True)
    assert not vm.saveEnabled
    vm.set_save_locked(False)
    assert vm.saveEnabled

    # …and the contract is the event's: the very same field of the event sheet
    # already blocked saving with a full description and no name.
    evm = EventDialogIslandViewModel()
    evm.characteristicsHost.storage = "описание есть"
    assert not evm.valid


def test_card_island_save_button_tracks_the_name_gate(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    button = find_item(dialog.quick, "entitySaveButton")

    assert button.property("enabled") is False
    dialog.name_input.setText("Герой")
    assert button.property("enabled") is True


# ── 3.3 ───────────────────────────────────────────────────────────────────────


def test_event_ai_buttons_are_named_by_their_target_fields(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    for object_name, expected in EVENT_AI_NAMES:
        assert _accessible_name(dialog.quick, object_name) == expected


def test_card_ai_buttons_name_the_card_target_never_the_event(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)

    for object_name, expected in CARD_AI_NAMES:
        name = _accessible_name(dialog.quick, object_name)
        assert name == expected, object_name
    # C1: the whole-entity wave lost the borrowed «Событие» literally.
    whole = find_item(dialog.quick, "entityGenerateButton")
    assert whole.property("fieldLabel") == "Персонаж"


@pytest.mark.parametrize(
    "key,label",
    [
        ("character", "Персонаж"),
        ("organization", "Организация"),
        ("item", "Предмет"),
        ("location", "Локация"),
    ],
)
def test_entity_label_names_the_cards_own_type_from_the_registry(qtbot, key, label):
    vm = EntityCardIslandViewModel(key, [], [])
    assert vm.entityLabel == label


def test_event_ai_buttons_sit_inside_their_field_rows(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.show()

    for field_name, button_name in EVENT_AI_ROW_PAIRS:
        _assert_button_in_field_row(dialog.quick, field_name, button_name)


def test_card_ai_buttons_sit_inside_their_field_rows(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.show()

    for field_name, button_name in CARD_AI_ROW_PAIRS:
        _assert_button_in_field_row(dialog.quick, field_name, button_name)
