"""SheetPresetViewModel — preset-catalog state for the QML preset island.

Design D3 (port-sheet-list-preset-dialogs-qml-q3a): the thin state half of
«Создать из пресета…». Flat row model (roles ``id``/``label``) from
``PresetCatalog().list()``, the selected index, the full ``licenseText`` of the
selection and ``nameText`` (the template-name field).

``selectPreset(index)`` applies the D5 substitution rule verbatim from the
widgets dialog: the preset title is substituted into the name field only while
the user has not typed their own name — the field is empty or ``.strip()``
still matches ANOTHER preset's title (surrounding whitespace does not make a
foreign title into a user name, review #9; a padded OWN title matches neither
branch and survives verbatim). Construction pre-selects the first preset the
way ``setCurrentRow(0)`` did.

The create flow (name validation under ``run_locked``, ``create_from_preset``,
``created(int)``, conflict warnings) is facade/Python-side; QML only switches
the selection.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.domain.character_sheets.preset_catalog import PresetCatalog


class SheetPresetViewModel(QObject):
    """Preset rows + selection + license + the D5 name-substitution rule."""

    rowsChanged = Signal()
    selectionChanged = Signal()
    licenseChanged = Signal()
    nameChanged = Signal()

    def __init__(
        self, catalog: PresetCatalog | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._presets = list((catalog or PresetCatalog()).list())
        self._rows = [
            {"id": preset.id, "label": preset.title} for preset in self._presets
        ]
        self._selected_index = -1
        self._license_text = ""
        self._name_text = ""
        if self._presets:
            # The widgets dialog ended construction with setCurrentRow(0).
            self._apply_selection(0)

    # ---- QML surface (row roles per design D4) ----

    def _get_presets(self) -> list[dict]:
        return self._rows

    presetList = Property("QVariant", _get_presets, notify=rowsChanged)

    def _get_selected_index(self) -> int:
        return self._selected_index

    selectedIndex = Property(int, _get_selected_index, notify=selectionChanged)

    def _get_selected_preset_id(self) -> Any:
        # QVariant: "no selection" reaches QML as null, not "".
        return self.selected_preset_id

    selectedPresetId = Property(
        "QVariant", _get_selected_preset_id, notify=selectionChanged
    )

    def _get_license_text(self) -> str:
        return self._license_text

    licenseText = Property(str, _get_license_text, notify=licenseChanged)

    def _get_name_text(self) -> str:
        return self._name_text

    nameText = Property(str, _get_name_text, notify=nameChanged)

    # ---- QML in-calls (sync slots, spec qml-shell) ----

    @Slot(int)
    def selectPreset(self, index: int) -> None:
        """Switch the selection; a repeat/out-of-range index is a no-op
        (QListWidget's currentRowChanged only fired on actual changes)."""
        if index == self._selected_index:
            return
        if not 0 <= index < len(self._presets):
            return
        self._apply_selection(index)

    @Slot(str)
    def setNameText(self, text: str) -> None:
        """Push the field's current text in from QML (two-way for the name)."""
        if text == self._name_text:
            return
        self._name_text = text
        self.nameChanged.emit()

    # ---- Python (facade / tests) contract ----

    @property
    def selected_index(self) -> int:
        return self._selected_index

    @property
    def selected_preset_id(self) -> str | None:
        if 0 <= self._selected_index < len(self._presets):
            return self._presets[self._selected_index].id
        return None

    @property
    def license_text(self) -> str:
        return self._license_text

    @property
    def name_text(self) -> str:
        return self._name_text

    # ---- internals ----

    def _apply_selection(self, index: int) -> None:
        preset = self._presets[index]
        old_license = self._license_text
        old_name = self._name_text

        self._selected_index = index
        self._license_text = preset.license_text
        # D5: substitute the title only while the field is empty or still
        # holds another preset's title (the user has not typed their own
        # name). Surrounding whitespace does not make it a user name: a padded
        # foreign title like «Mörk Borg » is still that preset's title and
        # gets replaced by the clean one (review #9).
        current = self._name_text.strip()
        other_titles = {p.title for p in self._presets if p.id != preset.id}
        if current == "" or current in other_titles:
            self._name_text = preset.title

        self.selectionChanged.emit()
        if self._license_text != old_license:
            self.licenseChanged.emit()
        if self._name_text != old_name:
            self.nameChanged.emit()
