"""Minimal LSS formula evaluator (change add-dnd-module-foundation, task 4.2).

LSS formulas appear in `bonus.expr`, `resource.maxExpr`, `uses.countExpr` and
`uses.shortRestRegain` / `resource.shortRestRegain`, and roll formulas live in
`gold-dice.dice`. The grammar accepted here is exactly what those fields use
(per the LSS schema descriptions):

* arithmetic `+ - * /`, parentheses, unary minus;
* dice in d-notation: `2d6`, `2 d 4*10`, `1к8` (Latin ``d`` or Cyrillic ``к``,
  any case, optional spaces);
* variables in square brackets: `[STR] [DEX] [CON] [INT] [WIS] [CHA] [PROF] [LVL]`;
* the functions ``ceil(...)`` and ``max(a, b, ...)`` (``max`` appears in real
  SRD counters, e.g. ``max([CHA],1)`` for bardic inspiration).

"Вычисляется" (computes) for validator purposes means: the text parses under
this grammar, references only known variables, and evaluates to a number with
every known variable bound to a neutral placeholder and dice replaced by
their mathematical expectation (so the check is deterministic — no real
rolling). Anything else — unknown variable, malformed dice, literal division
by zero, trailing junk — is not a computable formula.
"""
from __future__ import annotations

import math
import re
from typing import Mapping

KNOWN_VARIABLES = frozenset(
    {"STR", "DEX", "CON", "INT", "WIS", "CHA", "PROF", "LVL"}
)

# Neutral binding used to decide "formula computes to a number".
_PLACEHOLDER_VALUE = 1.0

_DICE_SEPARATORS = frozenset({"d", "D", "к", "К"})
_CEIL_FUNCTION = "ceil"
_MAX_FUNCTION = "max"

_TOKEN_RE = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<variable>\[[A-Za-zА-Яа-яЁё_]+\])
  | (?P<name>[A-Za-zА-Яа-яЁё_]+)
  | (?P<op>[-+*/(,)])
    """,
    re.VERBOSE,
)


class FormulaSyntaxError(ValueError):
    """Raised when the text is not a well-formed LSS formula."""


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise FormulaSyntaxError(f"неизвестный символ {text[pos]!r}")
        pos = match.end()
        kind = match.lastgroup or ""
        if kind == "space":
            continue
        tokens.append((kind, match.group()))
    return tokens


def _die_expectation(count: float, sides: int) -> float:
    """Deterministic stand-in for `count d sides`: the mathematical mean."""
    return count * (sides + 1) / 2


class _Parser:
    """Recursive-descent evaluator over the token list from ``_tokenize``."""

    def __init__(
        self, tokens: list[tuple[str, str]], variables: Mapping[str, float]
    ) -> None:
        self._tokens = tokens
        self._pos = 0
        self._variables = variables

    def parse(self) -> float:
        if not self._tokens:
            raise FormulaSyntaxError("пустая формула")
        value = self._expression()
        if self._pos != len(self._tokens):
            raise FormulaSyntaxError("лишний текст после конца формулы")
        return value

    # -- grammar levels ---------------------------------------------------
    def _expression(self) -> float:
        value = self._term()
        while self._peek_op() in ("+", "-"):
            op = self._take_op()
            rhs = self._term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def _term(self) -> float:
        value = self._unary()
        while self._peek_op() in ("*", "/"):
            op = self._take_op()
            rhs = self._unary()
            if op == "/":
                if rhs == 0:
                    raise FormulaSyntaxError("деление на ноль")
                value = value / rhs
            else:
                value = value * rhs
        return value

    def _unary(self) -> float:
        if self._peek_op() == "-":
            self._take_op()
            return -self._unary()
        return self._atom()

    def _atom(self) -> float:
        if self._peek_op() == "(":
            self._take_op()
            value = self._expression()
            if self._peek_op() != ")":
                raise FormulaSyntaxError("ожидалась закрывающая скобка")
            self._take_op()
            return value
        kind, raw = self._peek()
        if kind == "number":
            self._advance()
            value = float(raw)
            if self._peek_name_in(_DICE_SEPARATORS):
                self._advance()
                value = _die_expectation(value, self._die_sides())
            return value
        if kind == "variable":
            self._advance()
            return self._variable_value(raw)
        if kind == "name":
            if raw == _CEIL_FUNCTION:
                self._advance()
                inner = self._call_argument()
                return float(math.ceil(inner))
            if raw == _MAX_FUNCTION:
                self._advance()
                return self._call_max()
            raise FormulaSyntaxError(f"неизвестный идентификатор {raw!r}")
        raise FormulaSyntaxError(f"ожидалось число или переменная, получено {raw!r}")

    def _call_argument(self) -> float:
        """One parenthesized argument shared by the functions."""
        if self._peek_op() != "(":
            raise FormulaSyntaxError("у функции ожидалась открывающая скобка")
        self._take_op()
        value = self._expression()
        if self._peek_op() != ")":
            raise FormulaSyntaxError("у функции ожидалась закрывающая скобка")
        self._take_op()
        return value

    def _call_max(self) -> float:
        if self._peek_op() != "(":
            raise FormulaSyntaxError("у max ожидалась открывающая скобка")
        self._take_op()
        best = self._expression()
        while self._peek_op() == ",":
            self._take_op()
            best = max(best, self._expression())
        if self._peek_op() != ")":
            raise FormulaSyntaxError("у max ожидалась закрывающая скобка")
        self._take_op()
        return best

    def _die_sides(self) -> int:
        kind, raw = self._peek()
        if kind != "number":
            raise FormulaSyntaxError("у кубика должно быть число сторон")
        self._advance()
        sides = int(float(raw))
        if sides < 1:
            raise FormulaSyntaxError("у кубика меньше одной стороны")
        return sides

    # -- token helpers ------------------------------------------------------
    def _peek(self) -> tuple[str, str]:
        if self._pos >= len(self._tokens):
            return ("end", "<конец>")
        return self._tokens[self._pos]

    def _peek_op(self) -> str:
        kind, raw = self._peek()
        return raw if kind == "op" else ""

    def _peek_name_in(self, names: frozenset[str]) -> bool:
        kind, raw = self._peek()
        return kind == "name" and raw in names

    def _take_op(self) -> str:
        # Callers always peek the operator first, so the token is known here.
        kind, raw = self._peek()
        assert kind == "op"  # noqa: S101 - internal invariant
        self._advance()
        return raw

    def _advance(self) -> None:
        self._pos += 1

    def _variable_value(self, raw: str) -> float:
        name = raw[1:-1].upper()
        if name not in KNOWN_VARIABLES:
            raise FormulaSyntaxError(f"неизвестная переменная {raw}")
        if name not in self._variables:
            raise FormulaSyntaxError(f"переменная {raw} не связана со значением")
        return self._variables[name]


def evaluate_formula(
    text: str, variables: Mapping[str, float] | None = None
) -> float | None:
    """Evaluate an LSS formula; ``None`` means it does not compute.

    Dice evaluate to their mathematical expectation so the result is
    deterministic. ``variables`` keys are bare names (``"LVL"``); every
    variable used by the formula must be bound, or it does not compute.
    """
    given = {name.upper(): value for name, value in (variables or {}).items()}
    try:
        return _Parser(_tokenize(text), given).parse()
    except FormulaSyntaxError:
        return None


def formula_is_valid(text: str) -> bool:
    """True when the formula computes with every known variable bound to 1."""
    binding = {name: _PLACEHOLDER_VALUE for name in KNOWN_VARIABLES}
    return evaluate_formula(text, binding) is not None
