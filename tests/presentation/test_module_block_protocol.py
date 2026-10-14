"""Task 4.1 (dd-card-redesign, design Д2/Д5): the module-block protocol.

Three halves, none needing a window:

* the AST guard — the finite vocabularies (block kinds, cell kinds, anchors)
  are read out of ``protocol.py``'s SOURCE as literals and compared against
  the frozen lists here: widening the channel in the protocol without a
  kernel renderer, a QML pin and this test is cut on every run (design Д2
  «виды дескрипторов ограничены перечнем», risk «канал разрастается в второй
  UI-движок»);
* the construction gates — an unknown kind/anchor/cell kind is refused with
  the Russian sentence where it is built, the six legal kinds and two legal
  anchors build, and every descriptor serializes to JSON-safe plain data (the
  channel crosses to QML through QVariant, no Python object may ride);
* the empty channel — the default frame is honestly empty (the kernel paints
  the unchanged 0.19.1 screen), and the two new protocol doors answer the
  protocol's standing silence when called bare (the same contract
  tests/test_dd_module_isolation.py pins for the older doors).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.presentation.modules.protocol import (
    BLOCK_ANCHOR_REFUSAL,
    BLOCK_KIND_REFUSAL,
    CELL_KIND_REFUSAL,
    MODULE_BLOCK_ANCHORS,
    MODULE_BLOCK_KINDS,
    MODULE_CELL_KINDS,
    ModuleBlock,
    ModuleBlockCell,
    ModuleBlockFrame,
    ModuleBlockOption,
    ModuleBlockRow,
    ModuleSection,
)

PROTOCOL_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "presentation"
    / "modules"
    / "protocol.py"
)

# The frozen vocabularies as the design names them. Any drift — in either
# direction — fails first here, before the QML renderer could meet a kind it
# cannot paint. ``textline`` joined with the LSS sheet id of «Основное»
# (dd-card-redesign tasks 4.3/5.5) — the sanctioned growth path: protocol,
# kernel renderer, QML pin and this list in one change.
EXPECTED_KINDS = {"combo", "number", "textline", "switch", "text", "buttons", "table"}
EXPECTED_CELL_KINDS = {"text", "number", "switch"}
EXPECTED_ANCHORS = {"after_short_fields", "after_music"}


def _module_literal(name: str) -> set[str]:
    """Evaluate the ``frozenset({...})`` literal assigned to ``name`` at the
    module level of protocol.py — the source of truth, not the runtime value
    (a runtime equality would agree with a widened constant; this one will
    not)."""
    tree = ast.parse(PROTOCOL_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        target = None
        if isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if isinstance(target, ast.Name) and target.id == name:
            assert isinstance(node.value, ast.Call), name
            assert isinstance(node.value.func, ast.Name), name
            assert node.value.func.id in {"frozenset", "set"}, name
            value = ast.literal_eval(node.value.args[0])
            assert isinstance(value, (set, frozenset)), name
            return set(value)
    raise AssertionError(f"{name} is no longer a module-level literal")


def test_block_kind_vocabulary_is_the_frozen_seven() -> None:
    assert _module_literal("MODULE_BLOCK_KINDS") == EXPECTED_KINDS
    assert set(MODULE_BLOCK_KINDS) == EXPECTED_KINDS


def test_cell_kind_and_anchor_vocabularies_are_frozen() -> None:
    assert _module_literal("MODULE_CELL_KINDS") == EXPECTED_CELL_KINDS
    assert _module_literal("MODULE_BLOCK_ANCHORS") == EXPECTED_ANCHORS
    assert set(MODULE_CELL_KINDS) == EXPECTED_CELL_KINDS
    assert set(MODULE_BLOCK_ANCHORS) == EXPECTED_ANCHORS


def test_every_legal_kind_builds_at_every_legal_anchor() -> None:
    for kind in sorted(EXPECTED_KINDS):
        for anchor in sorted(EXPECTED_ANCHORS):
            block = ModuleBlock(kind=kind, id=f"b_{kind}", label="Блок", anchor=anchor)
            assert block.to_dict()["kind"] == kind
            assert block.to_dict()["anchor"] == anchor


def test_unknown_kind_anchor_and_cell_kind_are_refused() -> None:
    with pytest.raises(ValueError) as kind_error:
        ModuleBlock(kind="slider", id="x", label="X", anchor="after_music")
    assert str(kind_error.value) == BLOCK_KIND_REFUSAL
    with pytest.raises(ValueError) as anchor_error:
        ModuleBlock(kind="text", id="x", label="X", anchor="after_header")
    assert str(anchor_error.value) == BLOCK_ANCHOR_REFUSAL
    with pytest.raises(ValueError) as cell_error:
        ModuleBlockCell(field="c", kind="buttons")
    assert str(cell_error.value) == CELL_KIND_REFUSAL


def test_serialization_is_json_safe_plain_data() -> None:
    frame_blocks = (
        ModuleBlock(
            kind="combo",
            id="race",
            label="Вид",
            anchor="after_short_fields",
            options=(ModuleBlockOption("d1|e1", "Дwarf · SRD"),),
            value="d1|e1",
        ),
        ModuleBlock(
            kind="number",
            id="speed",
            label="Скорость",
            anchor="after_short_fields",
            value="30",
            min_value=0,
            max_value=500,
        ),
        ModuleBlock(
            kind="switch",
            id="flag",
            label="Флаг",
            anchor="after_short_fields",
            checked=True,
        ),
        ModuleBlock(
            kind="textline",
            id="sheet",
            label="Лист LSS",
            anchor="after_music",
            value="12345",
            placeholder="id цифрового листа Long Story Short",
        ),
        ModuleBlock(
            kind="text",
            id="jump",
            label="Прыжки",
            anchor="after_short_fields",
            value="вес 240 фн",
        ),
        ModuleBlock(
            kind="buttons",
            id="doors",
            label="Лист LSS",
            anchor="after_music",
            actions=(
                ModuleBlockOption("open", "Открыть в браузере"),
                ModuleBlockOption("top_up", "Дозаполнить ИИ", enabled=False),
            ),
        ),
        ModuleBlock(
            kind="table",
            id="abilities",
            label="Характеристики",
            anchor="after_short_fields",
            columns=("Навык", "Значение", "Владение"),
            rows=(
                ModuleBlockRow(
                    id="strength",
                    cells=(
                        ModuleBlockCell("label", "text", "Сила"),
                        ModuleBlockCell(
                            "value", "number", "", "16", min_value=1, max_value=30
                        ),
                        ModuleBlockCell("prof", "switch", "", checked=True),
                    ),
                ),
            ),
        ),
    )
    payload = [block.to_dict() for block in frame_blocks]
    round_tripped = json.loads(json.dumps(payload, ensure_ascii=False))
    assert round_tripped[0]["options"][0]["label"] == "Дwarf · SRD"
    assert round_tripped[1]["minValue"] == 0
    assert round_tripped[2]["checked"] is True
    assert round_tripped[3]["value"] == "12345"
    assert round_tripped[3]["placeholder"] == "id цифрового листа Long Story Short"
    assert round_tripped[4]["value"] == "вес 240 фн"
    assert round_tripped[5]["actions"][1]["enabled"] is False
    assert round_tripped[6]["rows"][0]["cells"][1]["field"] == "value"
    # The preview mirror's read value serializes the same way.
    section = ModuleSection("Характеристики", ("Сила 16: проверка +3",))
    assert json.loads(json.dumps(section.to_dict())) == {
        "title": "Характеристики",
        "lines": ["Сила 16: проверка +3"],
    }


def test_empty_frame_is_the_honest_absence() -> None:
    frame = ModuleBlockFrame()
    assert frame.blocks == ()
    assert frame.hidden_fields == ()
    assert frame.handler_factory is None


def test_protocol_doors_answer_the_standing_silence() -> None:
    """The bare bodies of the two new doors stay silent (``...``), the same
    contract tests/test_dd_module_isolation.py pins for the older doors — a
    protocol method called bare answers None, it never guesses a frame."""
    from app.presentation.modules.protocol import ExternalEntitySource

    assert ExternalEntitySource.module_blocks(None, None) is None
    assert ExternalEntitySource.module_sections(None, "character", "1") is None


def test_frame_factory_field_is_plain_object() -> None:
    """The handler factory rides as a plain ``object`` (the protocol stays a
    runtime leaf — no Callable typing import, the CardTabSpec.factory
    precedent): the frame with a factory keeps the dataclasses frozen and
    hashable-free (object carries no __eq__ promises beyond identity)."""
    sentinel = object()
    frame = ModuleBlockFrame(handler_factory=sentinel)
    assert frame.handler_factory is sentinel
