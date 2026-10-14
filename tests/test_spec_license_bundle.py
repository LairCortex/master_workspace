"""Release must ship the licence texts (docs/licensing.md §6, §4.1).

The code is Apache-2.0 (`LICENSE`), the content and our translations are
CC-BY-4.0 (`LICENSE.DATA.md`), third-party notices live in `NOTICE.md`, and
PySide6 is distributed under the LGPL-3.0 option — whose licence text has to
travel with the shipped binaries. A release built without these files breaks
the licence we ourselves chose, and nothing but this file-first guard notices
it until the artefact is already published.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"
DEST = "licenses"

#: Every notice the release ships: (source, destination directory).
LICENSE_DATAS = (
    ("LICENSE", DEST),
    ("LICENSE.DATA.md", DEST),
    ("NOTICE.md", DEST),
    ("LICENSES", f"{DEST}/LICENSES"),
)


def _spec_datas_text() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    if "datas=[" not in text:
        raise AssertionError("nri_manager.spec has no datas list")
    return text.split("datas=[", 1)[1].rsplit("]", 1)[0]


def test_spec_datas_ship_every_licence_notice():
    datas = _spec_datas_text()
    for src, dest in LICENSE_DATAS:
        assert f'("{src}", "{dest}")' in datas, (
            f"nri_manager.spec datas must ship {src!r} under {dest!r} — the "
            "release would lose a licence text it itself relies on"
        )


def test_every_licence_notice_exists_on_disk():
    for src, _dest in LICENSE_DATAS:
        assert (REPO_ROOT / src).exists(), f"missing licence notice: {src}"


def test_lgpl_text_is_the_real_licence():
    body = (REPO_ROOT / "LICENSES" / "lgpl-3.0.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in body
    assert "Version 3" in body


def test_pyproject_declares_the_code_licence():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "Apache-2.0"
    declared = project["license-files"]
    for src, _dest in LICENSE_DATAS:
        # pyproject lists the directory as a glob (LICENSES/*), the spec ships
        # the directory itself — both must name the same notice.
        assert any(entry == src or entry.startswith(f"{src}/") for entry in declared), (
            f"pyproject.toml license-files must declare {src!r}, got {declared}"
        )
    for entry in declared:
        assert "*" in entry or (REPO_ROOT / entry).exists(), f"dangling license-file: {entry}"


def test_data_licence_is_the_one_the_validator_accepts():
    """`license` inside a dataset is matched case-sensitively by the app."""
    from app.dd.domain.lss_checks import LICENSE_RE

    text = (REPO_ROOT / "LICENSE.DATA.md").read_text(encoding="utf-8")
    assert "CC-BY-4.0" in text and LICENSE_RE.match("CC-BY-4.0")
    assert "cc-by-4.0" not in text, (
        "the lowercase Hugging Face tag is not what a dataset file must carry"
    )
