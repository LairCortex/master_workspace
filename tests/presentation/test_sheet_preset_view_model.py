"""SheetPresetViewModel unit tests (port-sheet-list-preset-dialogs-qml-q3a, 1.2).

Pure Python port of the «Создать из пресета…» selection rules:
- ``presetList`` rows (roles ``id``/``label``) come from ``PresetCatalog().list()``;
- ``selectPreset(index)`` swaps ``licenseText`` and re-substitutes the preset
  title into ``nameText`` exactly per design D5: only while the field is empty
  or still holds ANOTHER preset's title (``.strip()`` comparison — surrounding
  whitespace does not make a foreign title into a user name, review #9; a
  padded OWN title matches neither branch and survives verbatim, like in the
  widgets dialog);
- initial construction selects the first preset (the widgets dialog did
  ``setCurrentRow(0)``).
The catalog is injected as a stub here; create/conflict flows live in the
facade (group 3), not in this VM.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.presentation.viewmodels.sheet_preset_view_model import (
    SheetPresetViewModel,
)

FATE = SimpleNamespace(id="fate_core", title="Fate Core", license_text="Fate license")
MORK = SimpleNamespace(id="mork_borg", title="Mörk Borg", license_text="Mörk license")


class StubCatalog:
    def __init__(self, presets) -> None:
        self._presets = list(presets)

    def list(self):
        return list(self._presets)


@pytest.fixture
def vm() -> SheetPresetViewModel:
    return SheetPresetViewModel(catalog=StubCatalog([FATE, MORK]))


# --- catalog surface ----------------------------------------------------------


def test_preset_rows_carry_id_and_title_label(vm):
    assert vm.presetList == [
        {"id": "fate_core", "label": "Fate Core"},
        {"id": "mork_borg", "label": "Mörk Borg"},
    ]


def test_construction_selects_the_first_preset(vm):
    # The widgets dialog ended __init__ with setCurrentRow(0): license shown and
    # the title substituted into an empty name field.
    assert vm.selectedIndex == 0
    assert vm.licenseText == "Fate license"
    assert vm.nameText == "Fate Core"


def test_empty_catalog_leaves_no_selection():
    vm = SheetPresetViewModel(catalog=StubCatalog([]))
    assert vm.selectedIndex == -1
    assert vm.licenseText == ""
    assert vm.nameText == ""


def test_default_catalog_is_the_shipped_presets():
    # Same catalog source as the dialog: Fate Core first, Mörk Borg second.
    vm = SheetPresetViewModel()
    assert [row["label"] for row in vm.presetList] == ["Fate Core", "Mörk Borg"]


# --- license swap on selection -------------------------------------------------


def test_selection_change_swaps_license(vm, qtbot):
    with qtbot.waitSignal(vm.licenseChanged, timeout=1000):
        vm.selectPreset(1)
    assert vm.licenseText == "Mörk license"
    with qtbot.waitSignal(vm.licenseChanged, timeout=1000):
        vm.selectPreset(0)
    assert vm.licenseText == "Fate license"
    assert "Mörk" not in vm.licenseText  # no residue of the previous license


def test_selecting_the_same_preset_changes_nothing(vm):
    recorder: list[str] = []
    vm.selectionChanged.connect(lambda: recorder.append("selection"))
    vm.licenseChanged.connect(lambda: recorder.append("license"))
    vm.nameChanged.connect(lambda: recorder.append("name"))
    vm.selectPreset(0)
    assert recorder == []


def test_invalid_index_is_ignored(vm):
    vm.selectPreset(5)
    vm.selectPreset(-1)
    assert vm.selectedIndex == 0
    assert vm.licenseText == "Fate license"


# --- D5 substitution matrix -----------------------------------------------------

# Field content before selectPreset(1) (Fate Core is selected initially), and
# the name content expected after the switch to Mörk Borg.
D5_TO_MORK = [
    ("", "Mörk Borg"),  # empty -> substituted
    ("   ", "Mörk Borg"),  # whitespace-only -> still "empty" (strips to "")
    ("Fate Core", "Mörk Borg"),  # another preset's title -> substituted
    ("  Fate Core  ", "Mörk Borg"),  # padded foreign title: not a user name (#9)
    ("Fate Core\n", "Mörk Borg"),  # trailing newline: .strip() covers it
    ("Mörk Borg", "Mörk Borg"),  # the new preset's own title -> kept
    ("  Mörk Borg  ", "  Mörk Borg  "),  # padded OWN title matches neither
    #                                       rule branch (.strip() is neither ""
    #                                       nor another title) -> survives
    #                                       verbatim, exactly like the widgets
    #                                       dialog
    ("Свой герой", "Свой герой"),  # user typed a name -> untouched
    ("  Мой Fate  ", "  Мой Fate  "),  # padded user name -> untouched
]


@pytest.mark.parametrize("before, expected", D5_TO_MORK)
def test_d5_matrix_switching_to_mork_borg(vm, before, expected):
    vm.setNameText(before)
    vm.selectPreset(1)
    assert vm.nameText == expected


@pytest.mark.parametrize(
    "before, expected",
    [
        ("  Mörk Borg  ", "Fate Core"),  # padded other title -> substituted
        ("", "Fate Core"),
        ("Fate Core", "Fate Core"),  # own (target's) title -> kept
        ("Свой герой", "Свой герой"),
    ],
)
def test_d5_matrix_back_to_fate_core(vm, before, expected):
    vm.selectPreset(1)  # now on Mörk Borg
    vm.setNameText(before)
    vm.selectPreset(0)
    assert vm.nameText == expected


def test_user_name_survives_multiple_switches(vm):
    vm.setNameText("Гром")
    vm.selectPreset(1)
    vm.selectPreset(0)
    vm.selectPreset(1)
    assert vm.nameText == "Гром"
    assert vm.licenseText == "Mörk license"


def test_selection_index_and_id_track_the_preset(vm, qtbot):
    with qtbot.waitSignal(vm.selectionChanged, timeout=1000):
        vm.selectPreset(1)
    assert vm.selectedIndex == 1
    assert vm.selected_preset_id == "mork_borg"
    # The QML-facing mirror of the same fact: the QVariant-wrapped id property
    # (a cleared selection reaches QML as null, not -1/"").
    assert vm.selectedPresetId == "mork_borg"
    vm.selectPreset(0)
    assert vm.selected_preset_id == "fate_core"
    assert vm.selectedPresetId == "fate_core"
    # Python-side license mirror behind the notifying ``licenseText``.
    assert vm.license_text == "Fate license"


# --- name editing from QML -------------------------------------------------------


def test_setting_name_emits_name_changed(vm, qtbot):
    with qtbot.waitSignal(vm.nameChanged, timeout=1000):
        vm.setNameText("Новое имя")
    assert vm.nameText == "Новое имя"


def test_set_name_with_the_same_value_emits_nothing(vm):
    recorder: list[int] = []
    vm.nameChanged.connect(lambda: recorder.append(1))
    vm.setNameText(vm.nameText)
    assert recorder == []
