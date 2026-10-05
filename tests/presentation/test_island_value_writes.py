"""PR-016: AX SetValue must reach the model, not just the canvas.

The cocoa value-set path lands in QAccessibleQuickItem, which writes the
item's text/value property silently — no textEdited/valueModified fires, so
fields wired through user-gesture signals ate the write while painting it.
These pins drive the REAL accessibility interfaces (iface.setText /
valueInterface().setCurrentValue) and require the view model to follow, the
vm→widget binding to survive, and the mention field's value slot to read
back (limit ② of the accessibility contract closed — NRI-0013 follow-up).
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item


@pytest.fixture
def card(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.vm.name = "Герой"
    QApplication.processEvents()
    return dialog


def iface_of(widget, object_name: str):
    iface = QAccessible.queryAccessibleInterface(find_item(widget, object_name))
    assert iface is not None, f"no accessibility interface on {object_name!r}"
    return iface


def settle():
    QApplication.processEvents()


def test_name_field_value_write_reaches_vm_and_binding_survives(card):
    field = find_item(card.quick, "entityNameField")
    iface = iface_of(card.quick, "entityNameField")

    iface.setText(QAccessible.Value, "Гильдия пекарей")
    settle()

    assert field.property("text") == "Гильдия пекарей"
    assert card.vm.name == "Гильдия пекарей"

    # The silent property write must not break the vm→text binding.
    card.vm.name = "Василиса"
    settle()
    assert field.property("text") == "Василиса"


def test_rating_spin_value_write_reaches_vm_and_binding_survives(card):
    spin = find_item(card.quick, "entityRatingSpin")
    value_iface = iface_of(card.quick, "entityRatingSpin").valueInterface()
    assert value_iface is not None

    value_iface.setCurrentValue(18)
    settle()

    assert spin.property("value") == 18
    assert card.vm.rating == 18

    card.vm.setRating(5)
    settle()
    assert spin.property("value") == 5


def test_music_field_value_write_reaches_vm(card):
    iface = iface_of(card.quick, "entityMusicField")

    iface.setText(QAccessible.Value, "https://example.org/tango")
    settle()

    assert card.vm.musicUrl == "https://example.org/tango"


def test_mention_value_write_reaches_storage_and_reads_back(card):
    iface = iface_of(card.quick, "entityCharacteristicsField")

    iface.setText(QAccessible.Value, "Сила 16, ловкость 12")
    settle()

    host = card.vm.characteristicsHost
    assert host.storage == "Сила 16, ловкость 12"
    assert iface.text(QAccessible.Value) == "Сила 16, ловкость 12"


def test_mention_value_slot_follows_host_side_change(card):
    iface = iface_of(card.quick, "entityCharacteristicsField")
    host = card.vm.characteristicsHost
    marker = "@[Мастер](character:7) "
    host.updateDisplay(marker, len(marker))
    settle()

    # The value slot mirrors the host-driven display (mention span folded
    # to its label text) without any write-back to storage.
    assert iface.text(QAccessible.Value) == "Мастер "
    assert host.storage == marker


def test_event_dialog_name_value_write_reaches_vm_and_binding_survives(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.vm.name = "Совет гильдий"
    QApplication.processEvents()

    field = find_item(dialog.quick, "eventNameField")
    iface = iface_of(dialog.quick, "eventNameField")

    iface.setText(QAccessible.Value, "Ночной дозор")
    settle()

    assert field.property("text") == "Ночной дозор"
    assert dialog.vm.name == "Ночной дозор"

    dialog.vm.name = "Рассвет"
    settle()
    assert field.property("text") == "Рассвет"
