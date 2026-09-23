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

Documented boundaries of the statically judgeable rule (kept honest here, the
runtime side is guarded per island in tests/presentation/ and live-audited in
task 5.4):

* glyph-text instances (``text: "+"``/``"↑"``/``""``) are icon buttons — the
  design map explicitly names them at the usage site, so their annotation is
  legal and must not be flagged;
* a *bound* text (``text: modelData.label``) is neither provable word nor
  provably data from source (the map annotates the music-open button whose
  bound text is a URL), so the generic rule stays silent; the named samples of
  task 4.2 pin no-annotation on those controls explicitly.

The guard is tamper-proof in both directions tested below: synthetic QML
fixtures carrying each violation are cut (and the legal uses are not), and a
violation injected into a TEMPORARY COPY of the real tree is cut while the
real corpus itself stays clean (no violation ever exists in the repo).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from tests.qml_a11y_scan import QML_ROOT, find_convention_violations, rule_head

# Exact expectations on the synthetic fixture below: (file, line, rule head).
# Instance violations report the line of the control's opening brace; the
# ternWord block spans lines 19-21 of the fixture and reports line 19.
_EXPECTED_SYNTHETIC = [
    ("bad.qml", 6, "ThemeButton with word text carries its own Accessible.name"),
    ("bad.qml", 7, "ThemeCheckBox with word text carries its own Accessible.name"),
    ("bad.qml", 8, "ThemeTabButton with word text carries its own Accessible.name"),
    ("bad.qml", 9, "forbidden Accessible.NoRole"),
    ("bad.qml", 10, "forbidden Accessible.ignored"),
    ("bad.qml", 11, "forbidden Accessible.value"),
    ("bad.qml", 19, "ThemeButton with word text carries its own Accessible.name"),
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
    for legal in ("okGlyph", "okBound", "okPlain"):
        assert legal not in joined


def test_guard_cuts_a_violation_injected_into_a_copy_of_the_real_tree(
    tmp_path: Path,
) -> None:
    """The deliberate-violation proof for the REAL corpus: the tree is copied
    to a scratch dir, two textbook violations are injected there, and the same
    guard that reads the repository fails on exactly those two — never on an
    unmodified file, and never inside the repository itself."""
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

    row = copy / "TimelineRowDelegate.qml"
    row_text = row.read_text(encoding="utf-8")
    row.write_text(row_text + "\nItem { Accessible.ignored: true }\n", encoding="utf-8")

    violations = find_convention_violations(copy)
    assert sorted(
        ((rel, rule_head(msg)) for rel, _, msg in violations),
        key=lambda entry: (entry[0], entry[1]),
    ) == [
        ("EntityCardRoot.qml",
         "ThemeCheckBox with word text carries its own Accessible.name"),
        ("TimelineRowDelegate.qml", "forbidden Accessible.ignored"),
    ]

    # The repository itself was never touched by the injection exercise.
    assert find_convention_violations(QML_ROOT) == []
