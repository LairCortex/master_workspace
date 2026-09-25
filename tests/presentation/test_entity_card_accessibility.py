"""Accessibility contract of the entity-card island (change
nri-0012-qml-accessibility, task 2.4).

Every name annotation is a USAGE-SITE fact on the production
EntityCardDialog (character type: the fullest composition — image, mention
fields, extras, music, AI row). The roles are штатно component facts pinned
here unchanged (TextField/EditableText face, Button, CheckBox, the MentionField
role from task 1.3); the names come from the design map: «Название», date
fields, «Рейтинг», «Ссылка на музыку» and the «✎» edit button «Изменить ссылку
на музыку» (NRI-0017 FI-4), the mention fields by label, extras by
modelData.label, every AI button «Сгенерировать: <fieldLabel>» (the whole-
entity wave carries the card's own registry label — «Персонаж» for this
fixture since NRI-0015 task 3.3, the borrowed «Событие» is gone). «Сохранить» and
«Открыть чар-лист» keep exactly their text as name (no usage-site override —
map + the 4.1 guard).
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from app.presentation.views.entity_card_dialog import EntityCardDialog
from tests.presentation.qml_helpers import find_item


@pytest.fixture
def card(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.vm.name = "Герой"
    QApplication.processEvents()
    return dialog


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def name_of(widget, object_name: str) -> str:
    return accessible_of(find_item(widget, object_name)).text(QAccessible.Name)


def iface_of(widget, object_name: str):
    return accessible_of(find_item(widget, object_name))


def test_plain_fields_carry_the_map_names_with_their_component_roles(card):
    quick = card.quick

    name_field = iface_of(quick, "entityNameField")
    assert name_field.role() == QAccessible.Role.EditableText
    assert name_field.text(QAccessible.Name) == "Название"

    assert iface_of(quick, "entityStartDateField").text(
        QAccessible.Name) == "Дата начала"
    assert iface_of(quick, "entityEndDateField").text(
        QAccessible.Name) == "Дата конца"

    rating = iface_of(quick, "entityRatingSpin")
    assert rating.role() == QAccessible.Role.SpinBox
    assert rating.text(QAccessible.Name) == "Рейтинг"


def test_mention_fields_are_editable_text_named_by_label(card):
    quick = card.quick

    characteristics = iface_of(quick, "entityCharacteristicsField")
    assert characteristics.role() == QAccessible.Role.EditableText
    assert characteristics.text(QAccessible.Name) == "Характеристики"

    backstory = iface_of(quick, "entityBackstoryField")
    assert backstory.role() == QAccessible.Role.EditableText
    assert backstory.text(QAccessible.Name) == "Предыстория"

    # Extras take the model label (the same string the TitleText paints).
    assert name_of(quick, "entityExtraField_personality") == "Личность"
    assert name_of(quick, "entityExtraField_tasks") == "Задачи"


def test_ai_buttons_naming_rule_with_the_filled_entity_target(card):
    quick = card.quick

    # entity-AI: the wave names THIS card's entity (C1, NRI-0015 task 3.3) —
    # the fieldLabel rides the view model's registry-backed entityLabel, a
    # character card answers «Персонаж» and the event's «Событие» is gone.
    whole = iface_of(quick, "entityGenerateButton")
    assert whole.text(QAccessible.Name) == "Сгенерировать: Персонаж"
    assert quick_root_property(card, "entityGenerateButton", "fieldLabel") == "Персонаж"

    assert name_of(quick, "entityNameAiButton") == "Сгенерировать: Название"
    assert name_of(quick, "entityCharacteristicsAiButton") == (
        "Сгенерировать: Характеристики")
    assert name_of(quick, "entityBackstoryAiButton") == (
        "Сгенерировать: Предыстория")
    # Extra AI buttons follow the model label too.
    assert name_of(quick, "entityExtraAiButton_personality") == (
        "Сгенерировать: Личность")


def quick_root_property(dialog, object_name: str, prop: str):
    return find_item(dialog.quick, object_name).property(prop)


def test_music_input_and_music_open_button_names(card):
    quick = card.quick

    # No url yet: the input is the live visible control.
    music_field = iface_of(quick, "entityMusicField")
    assert music_field.role() == QAccessible.Role.EditableText
    assert music_field.text(QAccessible.Name) == "Ссылка на музыку"

    # A url swaps the pair: the open button (its text is the URL data, the
    # name spells the verb once more) becomes the visible control.
    card.vm.setMusicUrl("https://example.test/song")
    QApplication.processEvents()
    opener = iface_of(quick, "entityMusicOpenButton")
    assert opener.role() == QAccessible.Role.Button
    assert opener.text(QAccessible.Name) == "Открыть ссылку на музыку"

    # NRI-0017 task 4.2 (FI-4=CR2): the music-«✎» icon button — its text is a
    # glyph, so nothing штатно names it; the usage-site spells the action.
    pencil = iface_of(quick, "entityMusicEditButton")
    assert pencil.role() == QAccessible.Role.Button
    assert pencil.text(QAccessible.Name) == "Изменить ссылку на музыку"


def test_text_carrying_controls_keep_their_names_untouched(card):
    # «Ровно штатное имя из text» offscreen means: NO usage-site Accessible.name
    # attached (the unannotated face answers an empty name slot offscreen — its
    # text-derived name is supplied by the live platform tree, design F7), while
    # the text itself carries the caption. An annotation would surface its
    # string here (F4) and break the 4.1 guard.
    from tests.presentation.qml_helpers import find_item

    quick = card.quick

    save_item = find_item(quick, "entitySaveButton")
    save = accessible_of(save_item)
    assert save.role() == QAccessible.Role.Button
    assert save.text(QAccessible.Name) == ""
    # The spec scenario pins BOTH half-facts: no name override AND no
    # description duplicating the self-explanatory caption (the slot reads
    # offscreen — the positive pin lives in the timeline/chip tests).
    assert save.text(QAccessible.Description) == ""
    assert save_item.property("text") == "Сохранить"

    # The char-sheet button needs the availability flag to materialize.
    card.vm.set_character_sheet_available(True)
    QApplication.processEvents()
    sheet_item = find_item(quick, "entityOpenSheetButton")
    sheet = accessible_of(sheet_item)
    assert sheet.role() == QAccessible.Role.Button
    assert sheet.text(QAccessible.Name) == ""
    assert sheet_item.property("text") == "Открыть чар-лист"

    no_end_item = find_item(quick, "entityNoEndCheck")
    no_end = accessible_of(no_end_item)
    assert no_end.role() == QAccessible.Role.CheckBox
    assert no_end.text(QAccessible.Name) == ""
    assert no_end_item.property("text") == "Бессрочно"
