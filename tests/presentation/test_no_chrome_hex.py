"""W2b зачистка (design D6): chrome screens carry no literal hex and no OS palette.

An AST pass over ``app/presentation/views/**`` forbids:

* string constants that look like colors (``#rgb`` / ``#rrggbb``) — the
  catalog/compiler derive every chrome color from tokens instead;
* calls to ``widget.palette()`` — OS-palette reads for chrome purposes are
  migrated to border/accent tokens.

The character-sheet canvas (``character_sheet/canvas*``) is whitelisted: its
QPainter colors are scene content, off-skin by design (D5), as are the paper
and D1 CSS surfaces it renders. Comments are invisible to the AST; docstrings
may mention old hexes (migration history) and are skipped.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import app.presentation.views as views_pkg

VIEWS_DIR = Path(views_pkg.__file__).resolve().parent

HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _is_whitelisted(path: Path) -> bool:
    rel = path.relative_to(VIEWS_DIR).as_posix()
    return rel.startswith("character_sheet/canvas")


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """id() of string-constant nodes that are docstrings (allowed to narrate)."""
    nodes: set[int] = set()
    for holder in (tree, *(n for n in ast.walk(tree)
                           if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef))):
        body = holder.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            value = body[0].value
            if isinstance(value.value, str):
                nodes.add(id(value))
    return nodes


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if HEX_COLOR_RE.search(node.value):
                found.append(f"{path.name}:{node.lineno}: hex literal {node.value!r}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "palette"
            and not node.args
        ):
            found.append(f"{path.name}:{node.lineno}: palette() call")
    return found


def test_chrome_screens_scan_actual_files():
    # A typo in the glob must not silently scan nothing.
    scanned = [p for p in VIEWS_DIR.rglob("*.py") if not _is_whitelisted(p)]
    names = {p.name for p in scanned}
    assert "main_window.py" in names and "llm_setup_dialog.py" in names
    assert len(scanned) > 15


def test_no_hex_literals_or_palette_calls_in_chrome_views():
    violations: list[str] = []
    for path in sorted(VIEWS_DIR.rglob("*.py")):
        if _is_whitelisted(path):
            continue
        violations.extend(_violations(path))
    assert not violations, "chrome must read colors from tokens:\n" + "\n".join(violations)
