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

QML islands (task 7.1, spec ui-theme «Зачистка QML-исходников», qml-shell
«Мост токенов»): a text pass over ``app/presentation/qml/**.qml`` forbids the
same offenses in the QML dialect — hex color literals (``#rgb``/``#rrggbb``
and alpha forms, ``0xRRGGBB[AA]``), JS-side color construction
(``Qt.rgba``/``Qt.hsla``/``Qt.hsv``/``Qt.tint`` — design D3 keeps the Python
compiler the only color engine), ``SystemPalette`` (the QML analogue of
``palette()``) and any color-valued string literal that is not one of the
named Qt globals the off-skin fallbacks use: themed properties read the
palette bridge only (``LauncherRoot.qml`` header pins its fallback set).

Q2a1 task 4.5 (spec qml-components «Источник оформления — только палитра
токенов»): the same text pass extends over ``app/presentation/qml/**/*.js`` —
the library's shared scripts (``nri/components/tokens.js`` and whatever else
lands there) live in one comment/string grammar with QML, so they scan under
the identical rules: no hex, no OS palette, no JS-side color construction.
Both scans are guarded against silently finding nothing (a typo'd glob must
fail, not pass vacuously), and each dialect has a planted-violation
self-check proving the scanner actually bites.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import app.presentation.qml as qml_pkg
import app.presentation.views as views_pkg
from PySide6.QtGui import QColor

VIEWS_DIR = Path(views_pkg.__file__).resolve().parent
QML_DIR = Path(qml_pkg.__file__).resolve().parent

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
    # W4 acceptance (task 7.2): the updated scale panel — the file with the
    # most new painting code — must stay on this scan list.
    assert "timeline_widget.py" in names
    assert len(scanned) > 15


def test_no_hex_literals_or_palette_calls_in_chrome_views():
    violations: list[str] = []
    for path in sorted(VIEWS_DIR.rglob("*.py")):
        if _is_whitelisted(path):
            continue
        violations.extend(_violations(path))
    assert not violations, "chrome must read colors from tokens:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Task 7.1: the same invariant over the QML island sources.
# ---------------------------------------------------------------------------

# Hex color literals: #rgb/#rgba/#rrggbb/#rrggbbaa strings and 0xRRGGBB[AA]
# integer colors (a legal QML color-slot form, e.g. `color: 0xff8800`).
QML_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
QML_HEX_INT_RE = re.compile(r"\b0[xX][0-9a-fA-F]{6,8}\b")
# JS-side color construction — design D3 keeps the Python theme compiler the
# only color engine; hover/pressed derivatives arrive precomputed in tokens.
QML_JS_COLOR_FN_RE = re.compile(r"\bQt\s*\.\s*(rgba|hsla|hsv|tint)\s*\(")
# OS-palette reads in QML — the analogue of the forbidden widgets palette().
QML_OS_PALETTE_RE = re.compile(r"\bSystemPalette\b")
QML_STRING_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')
QML_NAME_RE = re.compile(r"^[A-Za-z]+$")

# The literal colors an island source may contain at all: exactly the named
# Qt globals the off-skin (empty-palette, design D7) fallbacks degrade to —
# the set LauncherRoot.qml's header pins — plus "transparent" (a named QColor
# with alpha 0 used as "no fill", not a skin color). Every theme-driven value
# comes from the palette bridge instead.
OFF_SKIN_NAMED_GLOBALS = {"white", "black", "gray", "lightgray", "transparent"}


def _blank(text: str) -> str:
    """Comment text with newlines preserved (line numbers stay true)."""
    return "".join(ch if ch == "\n" else " " for ch in text)


def _qml_code(text: str) -> str:
    """QML source with comments blanked out, string literals kept.

    QML has no AST here; comments are narration (may mention hexes, e.g. the
    invariant itself) and must stay invisible to the scan, exactly like
    docstrings in the Python pass above.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch in "\"'":  # string literal: kept verbatim, may contain //
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif ch == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(_blank(text[i:j]))
            i = j
        elif ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(_blank(text[i:j]))
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _qml_violations(path: Path) -> list[str]:
    code = _qml_code(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for lineno, line in enumerate(code.splitlines(), 1):
        for m in QML_HEX_COLOR_RE.finditer(line):
            found.append(f"{path.name}:{lineno}: hex literal {m.group(0)!r}")
        for m in QML_HEX_INT_RE.finditer(line):
            found.append(f"{path.name}:{lineno}: hex color literal {m.group(0)!r}")
        for m in QML_JS_COLOR_FN_RE.finditer(line):
            found.append(f"{path.name}:{lineno}: Qt.{m.group(1)}() color construction")
        for m in QML_OS_PALETTE_RE.finditer(line):
            found.append(f"{path.name}:{lineno}: SystemPalette (OS palette read)")
        for m in QML_STRING_RE.finditer(line):
            value = m.group(0)[1:-1]
            if not QML_NAME_RE.match(value) or not QColor.isValidColorName(value):
                continue  # not a color-valued literal
            if value not in OFF_SKIN_NAMED_GLOBALS:
                found.append(f"{path.name}:{lineno}: color {value!r} outside the palette")
    return found


def test_qml_islands_scan_actual_files():
    # A typo in the glob must not silently scan nothing (same guard as above).
    scanned = sorted(QML_DIR.rglob("*.qml"))
    names = {p.name for p in scanned}
    assert "LauncherRoot.qml" in names
    assert scanned, "no qml sources under app/presentation/qml"


def test_off_skin_named_globals_are_real_qt_color_names():
    # The whitelist earns its name: every entry resolves via Qt's own color
    # database as a named color (not hex, not a palette read).
    for name in OFF_SKIN_NAMED_GLOBALS:
        assert QColor.isValidColorName(name), f"{name!r} is not a Qt color name"
        assert QColor(name).isValid()
        assert QML_NAME_RE.match(name)


def test_qml_scanner_detects_planted_violations(tmp_path):
    # Self-check: the regex pass must catch each offense — and must NOT see
    # the hex narrated inside a comment.
    bad = tmp_path / "Bad.qml"
    bad.write_text(
        'import QtQuick\n'
        'Rectangle {\n'
        '    color: "#ff0000"\n'
        '    border.color: "#abc"\n'
        '    property color c: 0x00ff00\n'
        '    radius: Qt.rgba(1, 0, 0, 1)\n'
        '    color: "tomato"\n'
        '    SystemPalette { id: pal }\n'
        '    // hex "#000000" here is narration, invisible to the scan\n'
        '}\n',
        encoding="utf-8",
    )
    violations = _qml_violations(bad)
    joined = "\n".join(violations)
    assert len(violations) == 6, joined
    assert "#ff0000" in joined and "#abc" in joined and "0x00ff00" in joined
    assert "Qt.rgba" in joined and "tomato" in joined and "SystemPalette" in joined
    assert "#000000" not in joined  # comment narration stayed invisible


def test_qml_islands_carry_no_hex_or_off_palette_colors():
    violations: list[str] = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        violations.extend(_qml_violations(path))
    assert not violations, "qml islands must read colors from the palette:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Task 4.5 (q2a1): the js half of the library — ``nri/components/tokens.js``
# and any further ``.js`` shipped under the qml tree. The QML pass above
# blanks comments and keeps string literals; JS shares that grammar, so the
# identical per-file checker applies. The off-skin fallback set is the same
# (tokens.js takes fallbacks as parameters and embeds no colors of its own).
# ---------------------------------------------------------------------------


def _js_files() -> list[Path]:
    return sorted(QML_DIR.rglob("*.js"))


def test_qml_js_scan_actual_files():
    # The same anti-vacuity guard as the qml pass: the glob must really
    # reach the library's shipped script (a renamed/misspelled scan catches
    # nothing at all — worse than the offenses it is meant to catch).
    scanned = _js_files()
    assert scanned, "no js sources under app/presentation/qml"
    assert "tokens.js" in {p.name for p in scanned}


def test_qml_js_scanner_detects_planted_violations(tmp_path):
    # Planted-violation test for the js branch: every offense kind bites,
    # comment narration stays invisible — asserted through the very checker
    # the production scan runs over the tree above.
    bad = tmp_path / "bad_tokens.js"
    bad.write_text(
        "// hex \"#000000\" narration in a comment is invisible\n"
        ".pragma library\n"
        "var accent = \"#ff0000\";\n"
        "var shorthand = \"#abc\";\n"
        "var asInt = 0x00ff00;\n"
        "function wash() { return Qt.rgba(1, 0, 0, 1); }\n"
        "var namedColor = \"tomato\";\n"
        "var osWash = SystemPalette;\n",
        encoding="utf-8",
    )
    violations = _qml_violations(bad)
    joined = "\n".join(violations)
    assert len(violations) == 6, joined
    assert "#ff0000" in joined and "#abc" in joined and "0x00ff00" in joined
    assert "Qt.rgba" in joined and "tomato" in joined and "SystemPalette" in joined
    assert "#000000" not in joined  # comment narration stayed invisible


def test_qml_js_libraries_carry_no_hex_or_off_palette_colors():
    violations: list[str] = []
    for path in _js_files():
        violations.extend(_qml_violations(path))
    assert not violations, "library js must read colors from the palette:\n" + "\n".join(violations)


# Binding-contract counterpart of the color scan: spec qml-shell «Контракт
# биндингов» (scenario «Sync-вход достаточен») forbids await-constructs in
# qml — QML may only touch synchronous slots/properties of the VM. Comments
# are blanked first (same _qml_code as above), so narration like "never an
# async entry" stays invisible; the Python half of the contract is pinned by
# test_launcher_viewmodel.test_vm_methods_are_all_sync.
QML_ASYNC_RE = re.compile(r"\b(?:async|await)\b")


def test_qml_islands_do_not_use_async_await_syntax():
    violations: list[str] = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        code = _qml_code(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), 1):
            if QML_ASYNC_RE.search(line):
                violations.append(f"{path.name}:{lineno}: async/await in qml")
    assert not violations, "qml may call sync entrances only:\n" + "\n".join(violations)
