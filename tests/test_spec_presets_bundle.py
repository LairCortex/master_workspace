"""PyInstaller spec guard for the bundled presets (add-character-sheet-c).

Closes the design.md risk «PyInstaller не упаковал JSON»: the spec's
``datas`` must ship every layout file the catalog reads
(``fate_core.json``, ``mork_borg.json``) — otherwise
``create_from_preset`` dies with a missing bundle file at runtime. The
actual artifact check runs in the build pipeline (CI builds on every push).
"""
from __future__ import annotations

from pathlib import Path

from app.presentation.views.character_sheet.presets.catalog import PresetCatalog

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"
PRESETS_SRC = "app/presentation/views/character_sheet/presets"


def _spec_datas_text() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    if "datas=[" not in text:
        raise AssertionError("nri_manager.spec has no datas list")
    return text.split("datas=[", 1)[1].rsplit("]", 1)[0]


def test_spec_datas_ship_every_catalog_preset_file():
    datas = _spec_datas_text()
    for preset in PresetCatalog().list():
        relative = f"{PRESETS_SRC}/{preset.json_name}"
        assert relative in datas, (
            f"nri_manager.spec datas must ship {relative} — otherwise the "
            "preset JSON is missing from the bundle"
        )
        assert (REPO_ROOT / relative).is_file()
