"""PyInstaller spec guard for the bundled LSS schemas (add-dnd-module-foundation, task 4.1).

The dataset validator reads its JSON-Schemas from ``app/dd/resources/schemas``
through ``lss_schemas.schema_resource_dir()`` — a design Д5 decision (offline
determinism): the frozen build must ship the fixed bundled set, or validation
dies at the first import attempt with nothing to point at. Like the QML and
preset guards, this test checks the spec text AND that every bundled artifact
actually exists on disk, so an emptied directory can never silently pass.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "nri_manager.spec"
SCHEMA_DIR = REPO_ROOT / "app" / "dd" / "resources" / "schemas"

# The fixed bundled set (mirrors lss_schemas.BUNDLED_SCHEMA_FILES — the import
# of that tuple below keeps the two lists from drifting apart).
SCHEMA_DEST = "app/dd/resources/schemas"


def _spec_datas_text() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    if "datas=[" not in text:
        raise AssertionError("nri_manager.spec has no datas list")
    return text.split("datas=[", 1)[1].rsplit("]", 1)[0]


def test_spec_datas_ship_the_schema_directory():
    datas = _spec_datas_text()
    assert f'("app/dd/resources/schemas", "{SCHEMA_DEST}")' in datas, (
        "nri_manager.spec datas must ship app/dd/resources/schemas — the "
        "frozen validator has no schemas to validate against otherwise"
    )


def test_every_bundled_schema_artifact_exists_on_disk():
    from app.dd.infrastructure.lss_schemas import BUNDLED_SCHEMA_FILES

    assert BUNDLED_SCHEMA_FILES, "the bundled schema set must not be empty"
    for name in BUNDLED_SCHEMA_FILES:
        path = SCHEMA_DIR / name
        assert path.is_file(), f"missing bundled schema artifact: {path}"


def test_character_export_artifact_exists_on_disk():
    # add-dnd-game-face task 9.1: the character export rides the same shipped
    # directory but outside BUNDLED_SCHEMA_FILES (its own version gate) — the
    # emptied-directory guard must not leave it unwatched either.
    from app.dd.infrastructure.lss_schemas import CHARACTER_SCHEMA_FILE

    path = SCHEMA_DIR / CHARACTER_SCHEMA_FILE
    assert path.is_file(), f"missing bundled schema artifact: {path}"
