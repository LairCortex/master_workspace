"""AST-pin (NRI-0016 5.1, AB5): the log path never resolves to the app root.

The log lives in ``NRI_MANAGER_DIR`` (app/infrastructure/paths.py, the one
config home); the old ``_app_root()`` — frozen-built executable directory / the
repository tree — must not come back in ``main.py`` or ``main_window.py``
either by name or by the «next to the exe» resolution it used to spell.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_FILES = (
    _REPO / "app" / "main.py",
    _REPO / "app" / "presentation" / "views" / "main_window.py",
)


def _names_and_strings(path: Path) -> tuple[set[str], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
    return names, strings


def test_no_app_root_log_path_resolution():
    for path in _FILES:
        names, strings = _names_and_strings(path)
        assert "_app_root" not in names, path
        # The frozen-exe / repo-tree resolution itself must not be re-inlined.
        assert "executable" not in names, path
        assert not any("рядом с exe" in s for s in strings), path
