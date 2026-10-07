"""The one entity-type→Lucide-glyph map and its drift guards (Lucide pass).

Pins:
* the map covers the whole entity registry — every ``EntityType`` carries a
  glyph, and every glyph is a real key of the generated ``icons.js``;
* :func:`icon_for` answers by enum and by registry key, and refuses keys
  outside the registry the same strict way the registry itself does;
* no second type→icon dictionary under ``app/``: a Python source file other
  than ``presentation/entity_icons.py`` quoting one of the characteristic
  glyph names fails (the world-snapshot VM's retired third slot is the
  precedent this guard stands on).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.enums.entity_type import EntityType
from app.presentation import entity_icons
from app.presentation.entity_icons import ENTITY_ICONS, icon_for

APP_DIR = Path(entity_icons.__file__).resolve().parents[1]
ICONS_JS = (
    Path(entity_icons.__file__).resolve().parent
    / "qml"
    / "nri"
    / "components"
    / "icons.js"
)
# The distinctive glyphs of the five card types; the rating glyph («list»)
# is deliberately not scanned — the string is a common UI-role literal in
# the theme layer and a scan would false-positive there.
CHARACTERISTIC_GLYPHS = ("calendar-days", "map-pin", "building", "user-round", "sword")
_GLYPH_SCAN = re.compile("|".join(f'"{glyph}"' for glyph in CHARACTERISTIC_GLYPHS))


def _icons_js_keys() -> set[str]:
    source = ICONS_JS.read_text(encoding="utf-8")
    return set(re.findall(r'^\s+"([a-z0-9-]+)": "M', source, re.M))


def test_map_covers_every_registry_type_with_a_vendored_glyph():
    assert set(ENTITY_ICONS) == set(EntityType)
    keys = _icons_js_keys()
    for entity_type, icon_name in ENTITY_ICONS.items():
        assert icon_name, entity_type
        assert icon_name in keys, (entity_type, icon_name)
    # The snapshot-era glyphs the consumers already pinned survive the move.
    assert icon_for(EntityType.EVENT) == "calendar-days"
    assert icon_for("location") == "map-pin"
    assert icon_for("organization") == "building"
    assert icon_for("character") == "user-round"
    assert icon_for("item") == "sword"


def test_icon_for_refuses_types_outside_the_registry():
    with pytest.raises(KeyError):
        icon_for("ghost")


def test_no_second_type_to_icon_dictionary_in_app():
    # Planted-violation self-check (the repo's grep-pin law): the scanner
    # must bite on a hypothetical second dictionary, not pass vacuously.
    assert _GLYPH_SCAN.search('_KINDS = (("location", "map-pin"),)') is not None
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path == Path(entity_icons.__file__):
            continue
        if _GLYPH_SCAN.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(APP_DIR)))
    assert offenders == []
