"""Table tests for the LSS formula mini-evaluator (task 4.2)."""
from __future__ import annotations

import math

import pytest

from app.dd.domain.lss_formula import evaluate_formula, formula_is_valid

ALL_ONES = {name: 1.0 for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA", "PROF", "LVL")}

COMPUTABLE = [
    "1",
    "-3",
    "1 + 2*3",
    "(1+2)*3",
    "10/4",
    "2d6",
    "2 d 4*10",
    "1к8+2",
    "1К6",
    "ceil([LVL]/2)",
    "max([CHA],1)",
    "max(1+[CHA],1)",
    "max(3,2,5)",
    "ceil(max(1,2))",
    "[PROF] + [LVL]",
    "[str] + 1",
    "5*[LVL]",
]

NOT_COMPUTABLE = [
    "",
    "1d",
    "d6",
    "2d0",
    "1+/2",
    "ceil(1",
    "ceil 1",
    "max 1,2",
    "max(1,2",
    "(1+2",
    "1 2",
    "5/0",
    "[XXX]+1",
    "мод",
    "1#2",
    ",1",
]


@pytest.mark.parametrize("text", COMPUTABLE)
def test_computable_formulas(text: str):
    assert formula_is_valid(text)
    value = evaluate_formula(text, ALL_ONES)
    assert value is not None


@pytest.mark.parametrize("text", NOT_COMPUTABLE)
def test_not_computable_formulas(text: str):
    assert not formula_is_valid(text)


def test_semantic_values():
    # dice stand in for their mathematical expectation
    assert evaluate_formula("2d6", {}) == pytest.approx(7.0)
    assert evaluate_formula("2d4*10", {}) == pytest.approx(50.0)
    assert evaluate_formula("ceil([LVL]/2)", {"LVL": 3}) == 2.0
    assert evaluate_formula("max([CHA],1)", {"CHA": 5}) == 5.0
    assert evaluate_formula("max([CHA],1)", {"CHA": 0}) == 1.0
    assert evaluate_formula("[lvl] + [prof]", {"LVL": 4, "PROF": 2}) == 6.0
    assert evaluate_formula("-[LVL]", {"LVL": 2}) == -2.0
    assert math.isclose(evaluate_formula("10/4", {}), 2.5)


def test_unbound_variable_does_not_compute():
    assert evaluate_formula("[LVL]") is None
    assert evaluate_formula("[LVL]+[STR]", {"STR": 3}) is None


def test_unknown_variable_is_rejected_even_when_bound_elsewhere():
    assert evaluate_formula("[HAR]", {"HAR": 4}) is None
