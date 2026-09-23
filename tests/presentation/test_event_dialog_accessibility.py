"""Accessibility contract of the event dialog island (change
nri-0012-qml-accessibility, task 3.5).

Every name is a USAGE-SITE fact from the design map, asserted through
``queryAccessibleInterface``: the fields/dates/type by purpose («Название
события», «Дата начала», «Дата конца», «Тип события»), the mention fields by
their labels (the EditableText role comes from task 1.3), every AI button
«Сгенерировать: <fieldLabel>» — the wave button carries the filled
``fieldLabel: "Событие"`` (QML-side only: the entity button is not among
``get_ai_buttons()``, so the label never enters the prompt) — and the dialog
swatch override «Цвет типа события» over the group-1 palette default. The
text buttons («Сохранить», «Отмена») and the «Бессрочно» checkbox keep the
stock face: offscreen an empty name slot while ``text`` carries the caption.
"""
from __future__ import annotations

from PySide6.QtGui import QAccessible

from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item


def _iface(dialog, object_name: str):
    iface = QAccessible.queryAccessibleInterface(
        find_item(dialog.quick, object_name))
    assert iface is not None, f"no accessibility interface on {object_name!r}"
    return iface


def _name(dialog, object_name: str) -> str:
    return _iface(dialog, object_name).text(QAccessible.Name)


def test_field_date_and_type_zones_carry_map_names(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    name = _iface(dialog, "eventNameField")
    assert name.role() == QAccessible.Role.EditableText
    assert name.text(QAccessible.Name) == "Название события"

    assert _name(dialog, "eventStartDateField") == "Дата начала"
    assert _name(dialog, "eventEndDateField") == "Дата конца"

    combo = _iface(dialog, "eventTypeCombo")
    assert combo.role() == QAccessible.Role.ComboBox
    assert combo.text(QAccessible.Name) == "Тип события"


def test_mention_fields_are_editable_text_named_by_label(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    characteristics = _iface(dialog, "eventCharacteristicsField")
    assert characteristics.role() == QAccessible.Role.EditableText
    assert characteristics.text(QAccessible.Name) == "Характеристики"

    backstory = _iface(dialog, "eventBackstoryField")
    assert backstory.role() == QAccessible.Role.EditableText
    assert backstory.text(QAccessible.Name) == "Предыстория"


def test_ai_buttons_named_by_field_label_with_the_filled_entity_target(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    for object_name, expected in (
        ("eventNameAiButton", "Сгенерировать: Название"),
        ("eventCharacteristicsAiButton", "Сгенерировать: Характеристики"),
        ("eventBackstoryAiButton", "Сгенерировать: Предыстория"),
    ):
        iface = _iface(dialog, object_name)
        assert iface.role() == QAccessible.Role.Button
        assert iface.text(QAccessible.Name) == expected

    # The wave target is named by the fieldLabel task 3.5 fills in.
    whole = _iface(dialog, "eventEntityAiButton")
    assert whole.role() == QAccessible.Role.Button
    assert whole.text(QAccessible.Name) == "Сгенерировать: Событие"
    assert find_item(
        dialog.quick, "eventEntityAiButton").property("fieldLabel") == "Событие"


def test_dialog_swatch_overrides_the_palette_name(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    swatch = _iface(dialog, "eventTypeSwatch")
    assert swatch.role() == QAccessible.Role.RadioButton
    assert swatch.text(QAccessible.Name) == "Цвет типа события"


def test_text_carrying_controls_keep_their_names_untouched(qtbot):
    # «Ровно штатное имя из text» offscreen means: NO usage-site Accessible.name
    # (the unannotated face answers an empty name slot offscreen; its text-
    # derived name is a live-platform fact, design F7 — the same pin group 2
    # used for the entity card and the 4.1 guard will re-check).
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    for object_name, caption in (
        ("eventSaveButton", "Сохранить"),
        ("eventCancelButton", "Отмена"),
    ):
        item = find_item(dialog.quick, object_name)
        iface = QAccessible.queryAccessibleInterface(item)
        assert iface is not None
        assert iface.role() == QAccessible.Role.Button
        assert iface.text(QAccessible.Name) == ""
        # …and the «Сохранить» half of spec «Описание скрытого перехода»:
        # a self-explanatory caption must not be duplicated as description.
        assert iface.text(QAccessible.Description) == ""
        assert item.property("text") == caption

    check_item = find_item(dialog.quick, "eventNoEndCheck")
    check = QAccessible.queryAccessibleInterface(check_item)
    assert check is not None
    assert check.role() == QAccessible.Role.CheckBox
    assert check.text(QAccessible.Name) == ""
    assert check_item.property("text") == "Бессрочно"
