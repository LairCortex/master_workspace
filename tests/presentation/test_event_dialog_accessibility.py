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


def test_parent_and_time_combos_carry_the_design_map_names(qtbot):
    """NRI-0023 tasks 7.1/7.2 (design Д8): the three dropdowns are штатные
    ThemeComboBoxes — role from the library component, name from the usage
    site («Родительское событие», «Час начала», «Минута начала»). Their popups
    are native windows outside the island (documented limit ③)."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    for object_name, expected in (
        ("eventParentCombo", "Родительское событие"),
        ("eventStartHourCombo", "Час начала"),
        ("eventStartMinuteCombo", "Минута начала"),
    ):
        iface = _iface(dialog, object_name)
        assert iface.role() == QAccessible.Role.ComboBox
        assert iface.text(QAccessible.Name) == expected


def test_no_end_checkbox_activation_reaches_the_view_model(qtbot):
    """NRI-0023 task 13.1 (design Д15, live audit OBS-2): the accessibility
    activation of «Бессрочно» must run the same toggle the mouse runs — on
    the pre-fix ``onToggled`` wiring the offscreen press moved the tick but
    silently never reached the VM, so «Дата конца» never hid. The dialog now
    rides the card's working convention (EntityCardRoot D1: the tick is the
    VM's bound state, every activation is a request read from the source of
    truth); this pin is the offscreen half — the live AXPress re-audit runs
    with the parent's live pass.
    """
    from PySide6.QtWidgets import QApplication

    from tests.presentation.qml_helpers import click_item

    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    check_item = find_item(dialog.quick, "eventNoEndCheck")
    end_field = find_item(dialog.quick, "eventEndDateField")
    actions = _iface(dialog, "eventNoEndCheck").actionInterface()
    # The synthetic mouse half of this pin needs the widget realized on the
    # scene (the entity-card D1 pin shows for the same reason).
    dialog.show()
    QApplication.processEvents()

    assert dialog.vm.noEnd is False
    assert end_field.property("visible") is True

    # The QAccessible press channel (AGENTS pattern: actionInterface().
    # doAction("Press")) — the VM flips and the end-date field hides.
    actions.doAction("Press")
    QApplication.processEvents()
    assert dialog.vm.noEnd is True
    assert end_field.property("visible") is False
    assert check_item.property("checked") is True

    # The mouse click (the ordinary user's path) toggles back through the
    # very same VM call — the convention switch moved nobody off the bus.
    click_item(dialog.quick, check_item)
    QApplication.processEvents()
    assert dialog.vm.noEnd is False
    assert end_field.property("visible") is True
    assert check_item.property("checked") is False
