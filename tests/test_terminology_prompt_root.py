"""NRI-0016 4.3 grep-pin: the UI copy of ``app/`` uses the single dictionary
root «промпт».

The LS3 defect was a root split («Промты полей» next to «промт мира») — a
reader could not tell if these were two settings. The delta spec fixes the
one root (design V5: словарная форма «промпт»); this test is its pin: the
shorter spelling «промт»/«Промт» (without the «п») may not occur anywhere in
the production sources — strings or comments of Python and QML modules. The
substring check is exact: «промт» is not contained in «промпт» (the «п»
breaks the four-letter run), so a correct corpus passes untouched.
"""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_app_sources_spell_prompt_with_the_one_root() -> None:
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*")):
        if path.suffix not in {".py", ".qml"} or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "промт" in text.lower():
            offenders.append(str(path.relative_to(APP_ROOT)))
    assert offenders == [], 'use «промпт», not «промт»: ' + ", ".join(offenders)
