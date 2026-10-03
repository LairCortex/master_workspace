"""4.1 guard (change nri-0012-qml-accessibility): the accessibility
conventions of ``app/presentation/qml/`` are source-checked on EVERY test run
(design D8's grep guard over D9's forbidden list).

Contract checked by :func:`tests.qml_a11y_scan.find_convention_violations`:

1. no ``Accessible.role: Accessible.NoRole`` anywhere (design F5: NoRole
   leaves a nameless AXStaticText node — exactly the tree noise this change
   forbids);
2. no ``Accessible.ignored`` (it hides nodes the tree contract wants visible);
3. no ``Accessible.value`` (the attached property does not even exist — F3);
4. a stock TEXT control (``ThemeButton``/``ThemeCheckBox``/``ThemeTabButton``)
   with a word text does NOT carry its own ``Accessible.name`` — such a
   control's tree name is its text already (F7), so a usage-site name is a
   forbidden re-annotation.
5. every non-empty literal assigned to ``Accessible.description`` /
   ``accessibleDescription`` (the hidden meaning of an activation) is a word
   of the fixed map DESCRIPTION_VOCABULARY (change nri-0022-entity-preview,
   task 7.1; spec qml-accessibility «Скрытый смысл активации описан в
   дереве») — an invented or retired wording fails here, never in the live
   audit; "" (unset slot) and literal-less bindings stay silent (fixture
   below).
6. no ``ThemeCheckBox`` usage site wires its action on ``onToggled``
   (change nri-0023-event-nesting-and-time, task 13.1, design Д15, live
   audit OBS-2): the accessibility activation of a stock CheckBox writes
   ``checked`` without a user gesture, so the action rides ``onClicked``
   (the tick stays the view model's binding).

Documented boundaries of the statically judgeable rule (kept honest here, the
runtime side is guarded per island in tests/presentation/ and live-audited in
task 5.4):

* glyph-text instances (``text: "+"``/``"↑"``/``""``) are icon buttons — the
  design map explicitly names them at the usage site, so their annotation is
  legal and must not be flagged;
* a *bound* text (``text: modelData.label``) is neither provable word nor
  provably data from source (the map annotates the music-open button whose
  bound text is a URL), so the generic rule stays silent; the named samples of
  task 4.2 pin no-annotation on those controls explicitly;
* the description rule judges only direct literal outcomes (a whole-value
  literal, a ternary's branches); concatenations and property bindings are
  statically unjudgable and stay silent — the runtime face of the map is
  pinned per island; the preview's RichText mention anchors carry no
  description at all (fixed limit ⑥ in AGENTS.md) and live outside the map.

The guard is tamper-proof in both directions tested below: synthetic QML
fixtures carrying each violation are cut (and the legal uses are not), and a
violation injected into a TEMPORARY COPY of the real tree is cut while the
real corpus itself stays clean (no violation ever exists in the repo).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from tests.qml_a11y_scan import (
    DESCRIPTION_VOCABULARY,
    QML_ROOT,
    find_convention_violations,
    rule_head,
)

# Exact expectations on the synthetic fixture below: (file, line, rule head).
# Instance violations report the line of the control's opening brace; the
# ternWord block spans lines 19-21 of the fixture and reports line 19. The
# description-map violations (rule 5, NRI-0022 task 7.1) report the line of
# the description declaration itself.
_EXPECTED_SYNTHETIC = [
    ("bad.qml", 6, "ThemeButton with word text carries its own Accessible.name"),
    ("bad.qml", 7, "ThemeCheckBox with word text carries its own Accessible.name"),
    ("bad.qml", 8, "ThemeTabButton with word text carries its own Accessible.name"),
    ("bad.qml", 9, "forbidden Accessible.NoRole"),
    ("bad.qml", 10, "forbidden Accessible.ignored"),
    ("bad.qml", 11, "forbidden Accessible.value"),
    ("bad.qml", 19, "ThemeButton with word text carries its own Accessible.name"),
    ("bad.qml", 34, "description text outside the fixed map"),
    ("bad.qml", 35, "description text outside the fixed map"),
    ("bad.qml", 44, "ThemeCheckBox wires action on onToggled"),
]

_SYNTHETIC_QML = """\
import QtQuick
import QtQuick.Controls
import nri.components

Item {
    ThemeButton { objectName: "badWord"; text: "Отмена"; Accessible.name: "X" }
    ThemeCheckBox { objectName: "badChk"; text: "Флаг"; Accessible.name: "" }
    ThemeTabButton { objectName: "badTab"; text: "Вкладки"; Accessible.name: "Tab" }
    Item { objectName: "noRole"; Accessible.role: Accessible.NoRole }
    Item { objectName: "ignored"; Accessible.ignored: true }
    Item { objectName: "value"; Accessible.value: 3 }

    // The legal uses (design map) must NOT be flagged: glyph buttons named
    // by the action, bound-text wrappers naming the action, plain text
    // controls left alone; comments/strings mentioning the tokens stay quiet.
    ThemeButton { objectName: "okGlyph"; text: "+"; Accessible.name: "+" }
    ThemeButton { objectName: "okBound"; text: rootData.url; Accessible.name: "Открыть" }
    ThemeButton { objectName: "okPlain"; text: "Импорт; и ещё" }
    ThemeButton { objectName: "ternWord";
        text: cond ? "раз"
                   : "два"
        Accessible.name: "TernClobber" }
    // Accessible.NoRole, Accessible.ignored, Accessible.value in comments no
    Item { property var s: "ThemeButton { text: \\"fake\\"; Accessible.name: \\"fake\\" }" }

    // The description map (rule 5, NRI-0022 task 7.1): map words and the
    // unset "" are legal, a property binding is unjudgable, a ternary's
    // condition literal compares (not assigns) and stays out; an invented
    // outcome — direct or in a branch — is cut on the declaration line.
    Item { objectName: "okDesc"; Accessible.description: "Выбирает сущность" }
    Item { objectName: "okEmpty"; accessibleDescription: "" }
    Item { objectName: "okTern"; Accessible.description: rowKind === "hdr"
        ? "Развернуть или свернуть раздел" : "Переходит к сущности" }
    Item { objectName: "badDesc"; Accessible.description: "Открывает детали" }
    Item { objectName: "badTern"; Accessible.description: model.type === "image"
        ? "Открыть изображение" : "Закрывает всё" }

    // The checkbox-action convention (rule 6, NRI-0023 task 13.1, design
    // Д15): the accessibility press writes ``checked`` without a user
    // gesture — an onToggled wiring silently loses the action, so the usage
    // site must ride onClicked. The tick-toggle below is cut on its opening
    // brace; the onClicked one and a mention of the token in a comment stay
    // silent.
    ThemeCheckBox { objectName: "badToggle"; text: "Галка"
        onToggled: vm.setFlag(checked) }
    ThemeCheckBox { objectName: "okClick"; text: "Галка"
        onClicked: vm.setFlag(!vm.flag) }  // onToggled here is only prose
}
"""


def test_real_qml_corpus_breaks_no_accessibility_convention() -> None:
    assert find_convention_violations(QML_ROOT) == []


def test_guard_cuts_each_synthetic_violation_and_keeps_legal_uses(
    tmp_path: Path,
) -> None:
    (tmp_path / "bad.qml").write_text(_SYNTHETIC_QML, encoding="utf-8")

    found = find_convention_violations(tmp_path)
    found_triples = sorted(
        ((rel, line, rule_head(msg)) for rel, line, msg in found),
        key=lambda entry: (entry[0], entry[1]),
    )
    assert found_triples == _EXPECTED_SYNTHETIC
    # The ok* instances never appear in any message.
    joined = "\n".join(msg for _, _, msg in found)
    for legal in ("okGlyph", "okBound", "okPlain", "okDesc", "okEmpty",
                  "okTern", "okClick"):
        assert legal not in joined


def test_guard_cuts_a_violation_injected_into_a_copy_of_the_real_tree(
    tmp_path: Path,
) -> None:
    """The deliberate-violation proof for the REAL corpus: the tree is copied
    to a scratch dir, four textbook violations are injected there (one per
    guard family, the third rewriting the detail row's mapped description
    out of the fixed map, the fourth rewinding the card's «Бессрочно» to the
    retired onToggled wiring), and the same guard that reads the repository
    fails on exactly those four — never on an unmodified file, and never
    inside the repository itself."""
    copy = tmp_path / "qml-copy"
    shutil.copytree(QML_ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    assert find_convention_violations(copy) == []  # untouched copy is clean

    card = copy / "EntityCardRoot.qml"
    card_text = card.read_text(encoding="utf-8")
    broken_checkbox = card_text.replace(
        '                                objectName: "entityNoEndCheck"\n'
        '                                text: "Бессрочно"\n',
        '                                objectName: "entityNoEndCheck"\n'
        '                                text: "Бессрочно"\n'
        '                                Accessible.name: ""\n',
        1,
    )
    assert broken_checkbox != card_text, "injection anchor moved — fix the probe"
    card.write_text(broken_checkbox, encoding="utf-8")

    # The checkbox-action convention (rule 6, NRI-0023 task 13.1): the card's
    # working onClicked wiring is rewound to the OBS-2 onToggled shape — the
    # exact regression Д15 forbids.
    rewound = broken_checkbox.replace(
        '                                onClicked: entityCardVm.setNoEnd(!entityCardVm.noEnd)\n',
        '                                onToggled: entityCardVm.setNoEnd(checked)\n',
        1,
    )
    assert rewound != broken_checkbox, "injection anchor moved — fix the probe"
    card.write_text(rewound, encoding="utf-8")

    # The description map (rule 5): the row's mapped «Выбирает сущность» is
    # rewritten to an invented wording — the exact drift NRI-0022 T7.1 pins.
    detail = copy / "DetailPanelRoot.qml"
    detail_text = detail.read_text(encoding="utf-8")
    broken_row = detail_text.replace(
        'Accessible.description: "Выбирает сущность"',
        'Accessible.description: "Открывает детали"',
        1,
    )
    assert broken_row != detail_text, "injection anchor moved — fix the probe"
    detail.write_text(broken_row, encoding="utf-8")

    row = copy / "TimelineRowDelegate.qml"
    row_text = row.read_text(encoding="utf-8")
    row.write_text(row_text + "\nItem { Accessible.ignored: true }\n", encoding="utf-8")

    violations = find_convention_violations(copy)
    assert sorted(
        ((rel, rule_head(msg)) for rel, _, msg in violations),
        key=lambda entry: (entry[0], entry[1]),
    ) == [
        ("DetailPanelRoot.qml", "description text outside the fixed map"),
        ("EntityCardRoot.qml", "ThemeCheckBox wires action on onToggled"),
        ("EntityCardRoot.qml",
         "ThemeCheckBox with word text carries its own Accessible.name"),
        ("TimelineRowDelegate.qml", "forbidden Accessible.ignored"),
    ]

    # The repository itself was never touched by the injection exercise.
    assert find_convention_violations(QML_ROOT) == []


# ── NRI-0025 task 4.2: the preview pin's quartet of fixed wordings ───────────

# The four formulations are design Д5's contract — the NAME states the
# button's very state and doubles as the tooltip; they reach the live audit
# register, so they are pinned here verbatim, in source. The island maps the
# column VM's pinState word to this quartet; counting the cap stays in the
# VM (checkpoint п.5: one owner of the number three).
PREVIEW_PIN_QUARTET: tuple[str, ...] = (
    "Закрепить карточку",
    "Открепить карточку",
    "Уже закреплена",
    "Можно закрепить только 3 карточки",
)


def test_the_preview_pin_names_are_the_pinned_quartet() -> None:
    text = (QML_ROOT / "EntityPreviewRoot.qml").read_text(encoding="utf-8")
    # Each wording exists exactly once in the source: the pinLabel ternary is
    # the single author — the tree name, the Nri.tooltip declaration and the
    # hover report all read that one property, so a fifth string (or a drift
    # of one into the tooltip) fails here. The runtime face of the same
    # quartet is pinned per state in test_entity_preview_island.py.
    for wording in PREVIEW_PIN_QUARTET:
        assert text.count(f'"{wording}"') == 1, wording
    assert "Accessible.name: pinLabel" in text
    assert "Nri.tooltip: pinLabel" in text
    # The pin spells no description (the name already names the action) —
    # the hidden-meaning slot of the Button seat stays untouched.
    assert "Accessible.description" not in text.split("id: pinButton")[1].split(
        "onClicked"
    )[0]


def test_description_vocabulary_stays_the_frozen_map() -> None:
    # NRI-0025 design Д5: the quartet lives in the NAME slot, so the fixed
    # description map does NOT grow — equality on the whole map, not just
    # the absence of pin wordings (a retired wording leaving silently fails
    # here too, mirroring rule 5's two-sided guard).
    assert DESCRIPTION_VOCABULARY == frozenset({
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
