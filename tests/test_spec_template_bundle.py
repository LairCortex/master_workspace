"""PyInstaller spec guard for the import template (rework-xlsx-import 5.2).

Closes the risk «PyInstaller не упаковал шаблон»: the spec's ``datas`` must
ship ``resources/import_template.xlsx`` into the bundle ``resources/``
directory — otherwise «Скачать шаблон» fails in the built app (dev resolves
the same layout only in a source checkout). Mirrors
tests/test_spec_presets_bundle.py.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"


def _spec_datas_text() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    if "datas=[" not in text:
        raise AssertionError("nri_manager.spec has no datas list")
    return text.split("datas=[", 1)[1].rsplit("]", 1)[0]


def test_spec_datas_ship_the_import_template():
    datas = _spec_datas_text()
    assert '("resources/import_template.xlsx", "resources")' in datas, (
        "nri_manager.spec datas must ship resources/import_template.xlsx "
        "into resources/ — «Скачать шаблон» reads exactly that bundle path"
    )
    assert (REPO_ROOT / "resources" / "import_template.xlsx").is_file()
