"""Static scanner for the QML accessibility conventions (change
nri-0012-qml-accessibility, tasks 4.1/4.2 — design D8's grep guard over the
forbidden list of D9).

The scanner reads QML source text (the real files on disk) and answers the three
guard questions:

* :func:`find_convention_violations` — the 4.1 guard: nowhere under ``root``
  may a QML file mention ``Accessible.NoRole``, ``Accessible.ignored`` or
  ``Accessible.value`` (design F3/F5/D9), a stock text control instance
  (``ThemeButton`` with word text / ``ThemeCheckBox`` with word text /
  ``ThemeTabButton`` with word text) must not carry its own
  ``Accessible.name``: штатно such a control's name IS its text (design F7),
  so a usage-site annotation is a forbidden re-annotation; and (task 13.1)
  no ``ThemeCheckBox`` usage site may wire its action on ``onToggled``.
  Since change
  nri-0022-entity-preview (task 7.1) the same guard also keeps the
  activation-description map: every non-empty string a
  ``Accessible.description`` / ``accessibleDescription`` binding assigns
  must be a word of :data:`DESCRIPTION_VOCABULARY` (spec qml-accessibility
  «Скрытый смысл активации описан в дереве»), so a retired or invented
  wording can never enter silently. The statically judgeable boundaries:
  ``""`` is the unset slot and literal-less bindings (RowItem's pass-through,
  a concatenation) carry nothing to judge — both stay silent; a ternary's
  condition literals are compared, not assigned, so only the branch outcomes
  are judged. The preview island's RichText mention anchors cannot carry a
  description at all (fixed limit ⑥ in AGENTS.md — Qt 6.10 gives a RichText
  link no own QAccessible node): a runtime fact pinned in
  ``tests/presentation/test_entity_preview_island.py``, not a vocabulary
  entry. Since change nri-0023-event-nesting-and-time (task 13.1, design
  Д15, live-audit OBS-2) the guard also keeps the checkbox-action convention:
  a ``ThemeCheckBox`` usage site must not wire its action on ``onToggled`` —
  the accessibility activation of a stock CheckBox writes ``checked``
  without a user gesture (no ``toggled`` emit), so ``onToggled`` silently
  loses the action for AT users; the action rides ``onClicked`` (the tick
  stays a binding of the view model's state).

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

# The fixed activation-description map (change nri-0022-entity-preview, task
# 7.1; spec qml-accessibility «Скрытый смысл активации описан в дереве»).
# A description states the hidden meaning of an activation, so its wording is
# part of the contract the live accessibility-audit diffs against — a literal
# assigned to ``Accessible.description``/``accessibleDescription`` may only be
# a word of this set (or "" — the slot stays unset). The set is the spec's
# fixed list plus the two wordings the shipped map carries (the timeline row,
# the world-snapshot header); a new wording needs a change that extends both
# the spec list and this guard, exactly like «Выбирает сущность» joined the
# map when the detail row left «Открывает карточку» (NRI-0022 task 7.1).
DESCRIPTION_VOCABULARY: frozenset[str] = frozenset({
    "Открывает игру",
    "Открывает карточку",
    "Открывает упомянутую сущность",
    "Выбор цвета типа",
    "Открыть изображение",
    "Переходит к сущности",
    "Выбирает сущность",
    "Открывает событие",
    "Развернуть или свернуть раздел",
})

_DESC_DECL_RE = re.compile(
    r"(?<![.\w])(?:Accessible\.description|accessibleDescription)\s*:"
)

_OWN_NAME_RE = re.compile(r"(?<![.\w])Accessible\.name\s*:")
_OWN_TEXT_RE = re.compile(r"(?<![.\w])text\s*:")
_OWN_OBJECT_NAME_RE = re.compile(r"(?<![.\w])objectName\s*:")
# Task 13.1 (design Д15): the checkbox action handler forbidden at a usage
# site — accessibility activation of a stock CheckBox writes ``checked``
# without emitting ``toggled``, so an onToggled wiring silently loses the
# action for AT users (live audit 2026-09-29 OBS-2).
_OWN_ON_TOGGLED_RE = re.compile(r"(?<![.\w])onToggled\s*:")
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


def _skip_string(v: str, i: int) -> int:
    """Index just past the string literal that starts at ``v[i]`` (an
    unterminated run ends at the newline — literals never span lines)."""
    quote = v[i]
    i += 1
    n = len(v)
    while i < n and v[i] not in (quote, "\n"):
        i += 2 if v[i] == "\\" else 1
    return i + 1 if i < n and v[i] == quote else i


def _find_top_level(v: str, token: str, start: int = 0) -> int | None:
    """First index of ``token`` outside strings and brackets at/after
    ``start``; optional chaining ``?.`` and ``??`` never answer for ``?``."""
    depth = 0
    i = start
    n = len(v)
    while i < n:
        c = v[i]
        if c in "\"'":
            i = _skip_string(v, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and c == token:
            if token != "?" or (i + 1 >= n or v[i + 1] not in "?."):
                return i
        i += 1
    return None


def _description_outcomes(value: str) -> list[str]:
    """The literal texts a description binding can assign; an empty answer
    means the shape is statically unjudgable (property binding, ternary
    branch without a literal, concatenation) and nothing gets judged. A
    ternary is judged per branch; the condition's literals compare, never
    assign, and stay out."""
    v = value.strip().rstrip(";").strip()
    if not v:
        return []
    if _STRING_RE.fullmatch(v):
        return [v[1:-1]]
    q = _find_top_level(v, "?")
    if q is None:
        return []
    c = _find_top_level(v, ":", q + 1)
    if c is None:
        return []
    return _description_outcomes(v[q + 1 : c]) + _description_outcomes(v[c + 1 :])


def _description_value_at(masked: str, struct: str, start: int) -> str:
    """Like :func:`_value_at` but ternary-tolerant: the shipped description
    ternaries wrap after the condition, so a newline whose next non-blank
    token is ``?``/``:`` continues the value; a depth-0 ``}`` (the enclosing
    object closing without a newline) ends it."""
    depth = 0
    end = start
    n = len(struct)
    while end < n:
        c = struct[end]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if c == "}" and depth == 0:
                break
            depth -= 1
        elif depth <= 0 and c in ";\n":
            j = end + 1
            while j < n and struct[j] in " \t":
                j += 1
            if c == "\n" and j < n and struct[j] in "?:":
                end = j
                continue
            break
        end += 1
    return masked[start:end]


@dataclass
class StockInstance:
    """One stock-control declaration with the depth-1 facts the guards read."""

    type_name: str
    line: int
    has_own_name: bool
    text_kind: str | None  # None = no depth-1 text declaration at all
    has_on_toggled: bool = False  # checkbox action wired on the wrong signal


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
        has_toggled = any(
            dep[t.start()] == body_depth
            for t in _OWN_ON_TOGGLED_RE.finditer(struct, open_idx + 1, close_idx)
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
                has_on_toggled=has_toggled,
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
            # The checkbox-action convention (NRI-0023 task 13.1, design Д15):
            # an AT press writes ``checked`` without a user gesture, so the
            # action must ride onClicked (the tick stays the VM's binding).
            if inst.type_name == "ThemeCheckBox" and inst.has_on_toggled:
                violations.append(
                    (rel, inst.line,
                     "ThemeCheckBox wires action on onToggled — the "
                     "accessibility press writes checked without a user "
                     "gesture, so the action must ride onClicked "
                     "(NRI-0023 Д15/OBS-2)")
                )
        # The fixed description map (NRI-0022 task 7.1): every non-empty
        # literal a description binding assigns must be a word of the map;
        # "" is the unset slot, unjudgable shapes stay silent (module
        # docstring, boundary list).
        for d in _DESC_DECL_RE.finditer(struct):
            value = _description_value_at(masked, struct, d.end())
            for outcome in _description_outcomes(value):
                if outcome and outcome not in DESCRIPTION_VOCABULARY:
                    line = _line_of(text, d.start())
                    violations.append(
                        (rel, line,
                         "description text outside the fixed map — "
                         f"{outcome!r} is not a word of "
                         "DESCRIPTION_VOCABULARY (NRI-0022 D8)")
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
