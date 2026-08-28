"""Bundled character-sheet presets: catalog + bundled layout files (design D1).

A preset is a fixed layout that ships inside the application bundle — a
``SheetTemplate`` v2 JSON (one portrait A4 page) stored next to this module —
plus its metadata: ``id`` / ``title`` / ``license_text``.
``CharacterSheetService.create_from_preset`` copies the layout into the
current game as a snapshot: after the copy there is no link to the bundle,
app updates never rewrite an already-copied template, and the bundle files
are read-only from the app's point of view.

The bundle carries NO images (no publisher logos, no book art): the
«портрет» of each layout is an image field without a file, and the required
license notice is a plain ``label`` the designer may edit in the copied
layout exactly like any other text on the sheet.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.domain.entities.character_sheet import (
    ORIENTATION_PORTRAIT,
    SCHEMA_VERSION,
    SheetTemplate,
)


def _presets_dir() -> Path:
    """The bundled presets live next to this module.

    The same layout holds in the PyInstaller bundle: the app ships as a
    directory bundle (nri_manager.spec) and the compiled module's
    ``__file__`` resolves inside it right next to the ``datas``-shipped
    layout files (verified in a real bundle:
    ``Path(__file__).resolve().parent == Path(sys._MEIPASS)/<module path>``),
    so no separate ``_MEIPASS`` lookup is needed.
    """
    return Path(__file__).resolve().parent


PRESETS_DIR: Path = _presets_dir()

# License texts are verbatim (spec character-sheet-preset: «Лицензия в
# диалоге и на листе»): the full Fate CC BY paragraph, and for Mörk Borg
# BOTH MÖRK BORG Third Party License paragraphs.
FATE_LICENSE_TEXT: str = (
    "This work is based on Fate Core System and Fate Accelerated Edition "
    "(found at https://www.faterpg.com/), products of Evil Hat Productions, LLC, "
    "developed, authored, and edited by Leonard Balsera, Brian Engard, "
    "Jeremy Keller, Ryan Macklin, Mike Olson, Clark Valentine, Amanda Valentine, "
    "Fred Hicks, and Rob Donoghue, and licensed for our use under the Creative "
    "Commons Attribution 3.0 Unported license "
    "(https://creativecommons.org/licenses/by/3.0/)."
)

MORK_BORG_LICENSE_TEXT: str = (
    "НРИ Сценарий Менеджер is an independent production by НРИ Сценарий "
    "Менеджер and is not affiliated with Ockult Örtmästare Games or Stockholm "
    "Kartell. It is published under the MÖRK BORG Third Party License.\n\n"
    "MÖRK BORG is ©2019 Ockult Örtmästare Games and Stockholm Kartell."
)


@dataclass(frozen=True)
class Preset:
    """Metadata of one bundled preset; the layout itself is ``json_name``."""

    id: str
    title: str
    license_text: str
    json_name: str


FATE_CORE = Preset(
    id="fate_core",
    title="Fate Core",
    license_text=FATE_LICENSE_TEXT,
    json_name="fate_core.json",
)
MORK_BORG = Preset(
    id="mork_borg",
    title="Mörk Borg",
    license_text=MORK_BORG_LICENSE_TEXT,
    json_name="mork_borg.json",
)


class PresetCatalog:
    """Catalog of the bundled presets (design D4): two presets, fixed order.

    ``get`` raises ``KeyError`` for an unknown id — the service layer maps
    that to its own user-facing error.
    """

    def list(self) -> list[Preset]:
        return [FATE_CORE, MORK_BORG]

    def get(self, preset_id: str) -> Preset:
        for preset in self.list():
            if preset.id == preset_id:
                return preset
        raise KeyError(preset_id)

    def load_pages(self, preset_id: str) -> str:
        """The raw ``pages`` JSON of the preset layout (read-only bundle file)."""
        preset = self.get(preset_id)
        return (PRESETS_DIR / preset.json_name).read_text(encoding="utf-8")

    def load_template(self, preset_id: str) -> SheetTemplate:
        """The preset layout as a ``SheetTemplate`` (v2, one portrait page)."""
        preset = self.get(preset_id)
        return SheetTemplate.from_pages_json(
            self.load_pages(preset_id),
            name=preset.title,
            orientation=ORIENTATION_PORTRAIT,
            schema_version=SCHEMA_VERSION,
        )
