"""PyInstaller spec guard for the REMOVED import template (C5 group 4).

«Скачать шаблон» generates the workbook under the active game calendar at
save time (change wire-game-calendar-xlsx, design D8), so there is nothing
static left to bundle: the spec's ``datas`` must not mention the template and
``resources/import_template.xlsx`` must be gone from the repository. This
prohibition test replaces tests/test_spec_template_bundle.py, which pinned
the opposite contract.
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


def test_spec_datas_do_not_ship_the_import_template():
    datas = _spec_datas_text()
    assert "import_template" not in datas, (
        "nri_manager.spec datas must not bundle resources/import_template.xlsx "
        "— «Скачать шаблон» regenerates the workbook under the active calendar"
    )


def test_static_template_file_is_gone():
    assert not (REPO_ROOT / "resources" / "import_template.xlsx").exists(), (
        "the static template was removed in C5 — the generator in "
        "app/application/services/xlsx_template.py is its single source"
    )
