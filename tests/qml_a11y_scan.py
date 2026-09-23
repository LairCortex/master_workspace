"""Static scanner for the QML accessibility conventions (change
nri-0012-qml-accessibility, tasks 4.1/4.2 — design D8's grep guard over the
forbidden list of D9).

The scanner reads QML source text (the real files on disk) and answers the two
guard questions:

* :func:`find_convention_violations` — the 4.1 guard: nowhere under ``root``
  may a QML file mention ``Accessible.NoRole``, ``Accessible.ignored`` or
  ``Accessible.value`` (design F3/F5/D9), and a stock text control instance
  (``ThemeButton`` with word text / ``ThemeCheckBox`` with word text /
  ``ThemeTabButton`` with word text) must not carry its own
  ``Accessible.name``: штатно such a control's name IS its text (design F7),
  so a usage-site annotation is a forbidden re-annotation.

* :func:`object_name_annotation_violation` — the 4.2 sample pin: a NAMED
  instance of a stock control must carry NO ``Accessible.name`` in its
  declaration at all. Unlike the generic rule this also covers controls whose
  text is a dynamic binding — statically unjudgable whether the bound string
  is a caption or data (the design map annotates exactly one such control, the
  music-open button whose text is the URL), so the sampled controls of 4.2 are
  pinned by name explicitly.

Text classification per instance (its depth-1 ``text:`` declaration):

=======  ==================================  ==================================
form     example                             own ``Accessible.name``
=======  ==================================  ==================================
word     ``text: "Сохранить"``               forbidden — the text IS the name
glyph    ``text: "+"`` / ``"↑"`` / ``""``    allowed — icon button, design map
dynamic  ``text: modelData.label``           generic 4.1 rule: allowed (cannot
                                              know the runtime caption); 4.2
                                              pins its named samples anyway
=======  ==================================  ==================================
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.presentation import qml as qml_shell

# The scanned production corpus (islands + nri.components library).
QML_ROOT = Path(qml_shell.__file__).resolve().parent

# Stock controls whose штатно tree name derives from their text (design F7).
STOCK_CONTROL_TYPES = ("ThemeButton", "ThemeCheckBox", "ThemeTabButton")

# Forbidden attachment tokens on comment-stripped source (design F3/F5/D9):
# NoRole leaves a nameless AXStaticText node; ignored hides nodes the contract
# wants visible; the Accessible.value property does not even exist.
FORBIDDEN_TOKENS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Accessible.NoRole", re.compile(r"Accessible\.NoRole\b")),
    ("Accessible.ignored", re.compile(r"Accessible\.ignored\b")),
    ("Accessible.value", re.compile(r"Accessible\.value\b")),
)

_OWN_NAME_RE = re.compile(r"(?<![.\w])Accessible\.name\s*:")
_OWN_TEXT_RE = re.compile(r"(?<![.\w])text\s*:")
_OWN_OBJECT_NAME_RE = re.compile(r"(?<![.\w])objectName\s*:")
_STOCK_OPEN_RE = re.compile(
    r"\b(" + "|".join(STOCK_CONTROL_TYPES) + r")\s*\{"
)

_STRING_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')
_LETTER_RE = re.compile(r"[^\W\d_]")  # Unicode letter ⇒ word text, not a glyph
_WORDISH_RE = re.compile(r"[A-Za-z_$][\w$]*")

# Bare words inside a binding expression that carry no runtime value name.
_JS_KEYWORDS = frozenset(
    {"true", "false", "null", "undefined", "in", "instanceof", "typeof",
     "new", "return", "function", "void", "if", "else", "this"}
)


def _blank_segment(segment: str) -> str:
    return re.sub(r"[^\n]", " ", segment)


def mask_qml(text: str) -> str:
    """Blank comments (line + block), keep string literals and all positions.

    Position preservation keeps every index usable against the raw text (line
    counting, messages quoting the real source).
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            end = n if j == -1 else j + 2
            out.append(_blank_segment(text[i:end]))
            i = end
        else:
            out.append(c)
            i += 1
    return "".join(out)


def blank_string_contents(masked: str) -> str:
    """Blank string-literal contents (quotes kept) — the brace-safe view."""
    out: list[str] = []
    i, n = 0, len(masked)
    while i < n:
        c = masked[i]
        if c in ('"', "'"):
            quote = c
            out.append(c)
            i += 1
            while i < n and masked[i] not in (quote, "\n"):
                if masked[i] == "\\":
                    out.append("  ")
                    i += 2
                    continue
                out.append(" ")
                i += 1
            if i < n and masked[i] == quote:  # properly closed literal
                out.append(quote)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def depths(struct: str) -> list[int]:
    """``depths[i]`` = brace nesting depth BEFORE index ``i`` (struct view)."""
    depth = 0
    arr: list[int] = []
    for c in struct:
        if c == "}":
            depth -= 1
        arr.append(max(depth, 0))
        if c == "{":
            depth += 1
    return arr


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _block_end(struct: str, open_idx: int) -> int:
    """Index of the '}' matching the '{' at ``open_idx`` (struct view)."""
    depth = 1
    for k in range(open_idx + 1, len(struct)):
        c = struct[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return k
    raise ValueError("unbalanced QML block")


def _value_at(masked: str, struct: str, start: int) -> str:
    """Binding value from after the colon: the text slice is read from the
    string-intact view, but termination is decided on the brace/string-blanked
    struct view — the value ends at the first ``;`` or newline whose
    parenthesis/bracket depth is zero (a value wrapped in brackets may span
    lines). Every shipped text/objectName binding fits this rule."""
    depth = 0
    end = start
    n = len(struct)
    while end < n:
        c = struct[end]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth <= 0 and c in ";\n":
            break
        end += 1
    return masked[start:end]


def classify_text_value(value: str) -> str:
    """word | glyph | dynamic | blank for one depth-1 text binding value."""
    literals = _STRING_RE.findall(value)
    if literals:
        if any(_LETTER_RE.search(lit) for lit in literals):
            return "word"  # any literal caption ⇒ text-carrying (also "a" + x)
        rest_words = [
            w for w in _WORDISH_RE.findall(_STRING_RE.sub(" ", value))
            if w not in _JS_KEYWORDS
        ]
        return "dynamic" if rest_words else "glyph"
    rest_words = [
        w for w in _WORDISH_RE.findall(value) if w not in _JS_KEYWORDS
    ]
    return "dynamic" if rest_words else "blank"


@dataclass
class StockInstance:
    """One stock-control declaration with the depth-1 facts the guards read."""

    type_name: str
    line: int
    has_own_name: bool
    text_kind: str | None  # None = no depth-1 text declaration at all


def _scan_instances(masked: str):
    """Yield (StockInstance, open_idx, close_idx) for every stock control.

    Searches run on the struct view (string contents blanked), so a
    ``ThemeButton {`` mentioned inside a string literal never materializes a
    phantom instance; values are sliced from the string-intact masked view.
    """
    struct = blank_string_contents(masked)
    dep = depths(struct)
    for m in _STOCK_OPEN_RE.finditer(struct):
        open_idx = m.end() - 1  # the '{' is part of the match in struct view
        try:
            close_idx = _block_end(struct, open_idx)
        except ValueError:
            continue
        body_depth = dep[open_idx] + 1
        has_name = any(
            dep[n.start()] == body_depth
            for n in _OWN_NAME_RE.finditer(struct, open_idx + 1, close_idx)
        )
        text_kind = None
        for t in _OWN_TEXT_RE.finditer(struct, open_idx + 1, close_idx):
            if dep[t.start()] == body_depth:
                text_kind = classify_text_value(_value_at(masked, struct, t.end()))
                break
        yield (
            StockInstance(
                type_name=m.group(1),
                line=_line_of(masked, open_idx),
                has_own_name=has_name,
                text_kind=text_kind,
            ),
            open_idx,
            close_idx,
        )


def stock_instances(text: str) -> list[StockInstance]:
    return [inst for inst, _, _ in _scan_instances(mask_qml(text))]


def find_convention_violations(root: Path) -> list[tuple[str, int, str]]:
    """All 4.1 violations under ``root`` as (relpath, line, message)."""
    violations: list[tuple[str, int, str]] = []
    for qml_file in sorted(root.rglob("*.qml")):
        rel = str(qml_file.relative_to(root))
        text = qml_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        masked = mask_qml(text)
        struct = blank_string_contents(masked)
        for token, rx in FORBIDDEN_TOKENS:
            for m in rx.finditer(struct):
                line = _line_of(text, m.start())
                snippet = lines[line - 1].strip() if line - 1 < len(lines) else ""
                violations.append(
                    (rel, line, f"forbidden {token} (design D9): {snippet}")
                )
        for inst, _, _ in _scan_instances(masked):
            if inst.has_own_name and inst.text_kind == "word":
                violations.append(
                    (rel, inst.line,
                     f"{inst.type_name} with word text carries its own "
                     "Accessible.name — the text IS the штатно name (F7/D9)")
                )
    return violations


def rule_head(message: str) -> str:
    """The stable rule identifier prefix of a violation message (tests assert
    on it without pinning the human-readable snippet tail)."""
    if message.startswith("forbidden "):
        return message.split(" (design D9)")[0]
    return message.split(" —")[0]


def _object_name_matches(value: str, object_name: str) -> bool:
    """Depth-1 objectName declaration vs the live instance name. Two shipped
    forms: an exact literal, or a Repeater concatenation whose quoted prefix
    each live instance starts with (``"tab_" + modelData.attr``)."""
    for lit in _STRING_RE.findall(value):
        inner = lit[1:-1]
        if inner == object_name:
            return True
        if inner.endswith("_") and object_name.startswith(inner):
            return True
    return False


def object_name_annotation_violation(
    text: str, type_name: str, object_name: str
) -> str | None:
    """4.2 sample pin: a message if the NAMED stock-control instance declares
    ANY depth-1 ``Accessible.name`` (even ``""`` — a name slot pinned by the
    stock control must not be attached at all, whatever its text binding is);
    ``None`` when clean. Raises LookupError if no instance with that name
    exists (a stale sample list must fail loudly, not silently pass)."""
    masked = mask_qml(text)
    struct = blank_string_contents(masked)
    dep = depths(struct)
    pattern = re.compile(rf"\b{re.escape(type_name)}\s*\{{")
    matched = False
    for m in pattern.finditer(struct):
        open_idx = m.end() - 1
        try:
            close_idx = _block_end(struct, open_idx)
        except ValueError:
            continue
        body_depth = dep[open_idx] + 1
        declared = [
            _value_at(masked, struct, om.end())
            for om in _OWN_OBJECT_NAME_RE.finditer(struct, open_idx + 1, close_idx)
            if dep[om.start()] == body_depth
        ]
        if not any(_object_name_matches(v, object_name) for v in declared):
            continue
        matched = True
        for nm in _OWN_NAME_RE.finditer(struct, open_idx + 1, close_idx):
            if dep[nm.start()] == body_depth:
                return (
                    f"line {_line_of(text, nm.start())}: {type_name} "
                    f"{object_name!r} attaches Accessible.name — its штатно "
                    "text-derived name must stay un-overridden"
                )
    if not matched:
        raise LookupError(
            f"no {type_name} instance with objectName {object_name!r} in source"
        )
    return None
