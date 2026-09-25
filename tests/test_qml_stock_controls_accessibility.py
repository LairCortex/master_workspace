"""4.2 guard (change nri-0012-qml-accessibility): stock Button/CheckBox/
TabButton controls on the live islands keep their штатно accessibility face —
their NAME slot is never overridden by a usage-site annotation.

The task's literal check (``queryAccessibleInterface(...).text(QAccessible.
Name)`` equals the visible text, non-empty) holds only on a live display: on
the offscreen platform the штатно text-derived name does NOT materialize —
every sampled unannotated control answers an EMPTY name slot there. This was
re-verified for this change by a scratch probe (stock Button/CheckBox/
TabButton in a QQuickWidget and in EntityCardDialog: role correct, Name == "";
an added annotation surfaces its string instead), and the same fact is pinned
inside this file (test_offscreen_face_...), so a future Qt that starts
deriving the name offscreen will fail loudly instead of silently.

What IS pinnable offscreen, and is pinned here, is the strongest equivalent —
for sampled production controls (EntityCard island + EventTypes rail buttons
at the source level):

(a) ``queryAccessibleInterface`` is non-null and the role is the component's;
(b) the Name slot never contradicts the visible text (offscreen: the empty
    штатно slot; a non-empty annotation clobber — the only way to get a
    different name — breaks the assertion);
(c) the visible ``text`` itself is present and equals the expected caption;
(d) in the QML source the sampled declaration carries NO ``Accessible.name``
    at all — this is what makes a broken ``Accessible.name: ""`` annotation
    fail the guard: the empty string is indistinguishable from the stock face
    at runtime (probe), but forbidden in the source (the 4.1 rule cannot judge
    bound text — the named-sample pin covers exactly that hole).

Checking that the live name EQUALS the visible text on a real display belongs
to task 5.4 (live ``accessibility-audit``) per the spec scenario «Живой предел
не прикрывается тестом» — the offscreen gate must not imitate it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.views.entity_card_dialog import EntityCardDialog
from tests.presentation.qml_helpers import find_item
from tests.qml_a11y_scan import QML_ROOT, object_name_annotation_violation

# Live sample: production island EntityCardDialog (all three stock control
# families in one real island), pinned against EntityCardRoot.qml.
WIDGET_SAMPLES = [
    ("entitySaveButton", QAccessible.Role.Button, "Сохранить"),
    ("entityNoEndCheck", QAccessible.Role.CheckBox, "Бессрочно"),
    ("entityRelatedTab_organizations", QAccessible.Role.PageTab, "Организации"),
]

# Source sample: every entry is (qml file, declared type, live objectName).
# The related-tab sample has BOUND text (text: modelData.label) — exactly the
# statically unjudgable case the generic 4.1 rule must stay silent about and
# the named-sample pin exists for; the EventTypes buttons add a second island
# to the sampled corpus.
_SOURCE_SAMPLES: list[tuple[str, str, str]] = [
    ("EntityCardRoot.qml", "ThemeButton", "entitySaveButton"),
    ("EntityCardRoot.qml", "ThemeCheckBox", "entityNoEndCheck"),
    ("EntityCardRoot.qml", "ThemeTabButton", "entityRelatedTab_organizations"),
    ("EventTypesRoot.qml", "ThemeButton", "typeAddButton"),
    ("EventTypesRoot.qml", "ThemeButton", "typeRemoveButton"),
]

# Production injection anchors (each replace() call asserts it fired, so a
# moved anchor fails the test instead of silently skipping the proof).
_INJECTIONS = [
    ("EntityCardRoot.qml",
     '                                text: "Бессрочно"\n',
     '                                Accessible.name: ""\n'),
    ("EntityCardRoot.qml",
     '                            text: modelData.label\n',
     '                            Accessible.name: ""\n'),
    ("EventTypesRoot.qml",
     '                        text: "Добавить"\n',
     '                        Accessible.name: ""\n'),
]


@pytest.fixture
def card(qtbot):
    """The real entity-card island (pattern of test_entity_card_accessibility)."""
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.vm.name = "Герой"
    QApplication.processEvents()
    return dialog


def _iface(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def test_sampled_stock_controls_expose_interface_role_and_visible_text(card):
    # (a) + (c): live island controls carry an interface of the component's
    # role and a non-empty visible caption.
    for object_name, role, visible_text in WIDGET_SAMPLES:
        item = find_item(card.quick, object_name)
        assert _iface(item).role() == role
        assert item.property("text") == visible_text != ""


def test_sampled_name_slots_never_contradict_the_visible_text(card):
    # (b): offscreen the штатно face answers the EMPTY name slot (the visible
    # text becomes the name only on a live display — deferred to 5.4). A
    # non-empty slot therefore can only be an annotation, and when Qt starts
    # delivering text-derived names offscreen the slot must equal the caption.
    for object_name, _role, visible_text in WIDGET_SAMPLES:
        name = _iface(find_item(card.quick, object_name)).text(QAccessible.Name)
        assert name in ("", visible_text), (
            f"{object_name}: name slot {name!r} contradicts visible text "
            f"{visible_text!r} — someone annotated a stock control"
        )
        assert name == "", (  # offscreen face pinned deliberately (see docstring)
            f"offscreen name slot for {object_name} became {name!r}: Qt started "
            "deriving text names offscreen — re-check the offscreen/live split"
        )


def test_self_explanatory_sampled_controls_carry_no_description(card):
    # Spec «Скрытый смысл активации описан в дереве»: controls whose caption
    # is self-sufficient must NOT duplicate it as a description. The pin is
    # offscreen-pinnable (unlike the live NAME half): an attached description
    # surfaces here verbatim — the island suites read positive descriptions
    # through the very same slot (F4), so emptiness is a statement, not an
    # absence of mechanism.
    for object_name, _role, _visible_text in WIDGET_SAMPLES:
        assert _iface(find_item(card.quick, object_name)).text(
            QAccessible.Description
        ) == ""


def test_annotation_surface_mechanism_the_runtime_contradiction_guard_relies_on(card):
    # The sanctioned negative control: the music-open wrapper (design map)
    # DOES carry a usage-site name; offscreen it surfaces in the Name slot and
    # differs from the control's (here: empty) visible text. This is precisely
    # the signature a name-clobbering annotation on a sampled stock control
    # would produce — and what the previous test forbids there.
    opener = find_item(card.quick, "entityMusicOpenButton")
    iface = _iface(opener)
    assert iface.text(QAccessible.Name) == "Открыть ссылку на музыку"
    assert iface.text(QAccessible.Name) != opener.property("text")


def test_sampled_declarations_carry_no_accessible_name_in_source():
    # (d): the штатно controls of the sample pin their ENTIRE name slot as
    # unannotated — even the bound-text related-tab, which 4.1 cannot judge.
    for rel, type_name, object_name in _SOURCE_SAMPLES:
        source = (QML_ROOT / rel).read_text(encoding="utf-8")
        assert object_name_annotation_violation(source, type_name, object_name) is None


def test_broken_empty_name_annotation_on_a_sample_would_fail_the_guard(
    tmp_path: Path,
) -> None:
    """The deliberate-violation proof: ``Accessible.name: ""`` is invisible to
    any runtime check offscreen (probe), so the guard that must catch it is
    the source pin — against a temporary copy of the production sources the
    sampled controls fail, while the real tree passes and stays untouched."""
    for rel, anchor, injection in _INJECTIONS:
        source = (QML_ROOT / rel).read_text(encoding="utf-8")
        broken = source.replace(anchor, anchor + injection, 1)
        assert broken != source, f"injection anchor moved in {rel} — fix the probe"
        scratch = tmp_path / rel
        scratch.write_text(broken, encoding="utf-8")
        sample = [
            (t, obj) for r, t, obj in _SOURCE_SAMPLES if r == rel
        ]
        findings = [
            object_name_annotation_violation(broken, t, obj) for t, obj in sample
        ]
        assert any(f is not None for f in findings), (
            f"injected Accessible.name: \"\" in {rel} slipped past the sample pin"
        )

    # Never annotate anything in the repository itself — the real tree passes.
    for rel, type_name, object_name in _SOURCE_SAMPLES:
        source = (QML_ROOT / rel).read_text(encoding="utf-8")
        assert object_name_annotation_violation(source, type_name, object_name) is None


# ── offscreen face pin (the empirical caveat of this task, pinned in-suite) ──

_FACE_QML = """\
import QtQuick
import QtQuick.Controls
import nri.components

Item {
    implicitWidth: 320
    implicitHeight: 200
    Column {
        ThemeButton { objectName: "plainWord"; text: "Импорт" }
        ThemeButton { objectName: "clobbered"; text: "Отмена"; Accessible.name: "Clobber" }
        TabBar {
            TabButton { objectName: "plainTab"; text: "Листы" }
        }
        CheckBox { objectName: "plainCheck"; text: "Галка" }
    }
}
"""


def _load_scratch_scene(qtbot, qapp, tmp_path: Path) -> QQuickWidget:
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(str(tmp_path / "ui.json")),
        tokens_path=tokens_file_path(),
    )
    engine = setup_qml_shell(qapp, runtime)
    scene = tmp_path / "stock_face_scene.qml"
    scene.write_text(_FACE_QML, encoding="utf-8")
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(320, 200)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def test_offscreen_face_a_stock_button_is_unnamed_while_an_annotation_surfaces(
    qtbot, qapp, tmp_path: Path,
) -> None:
    """Offscreen contract this whole guard rests on: unannotated stock Button
    → role Button with an EMPTY Name (text-derived naming exists on the live
    display only), while an ``Accessible.name`` annotation surfaces verbatim
    and contradicts the text. If a Qt update derives names offscreen the
    first assertion fails and the offscreen/live split gets re-examined."""
    widget = _load_scratch_scene(qtbot, qapp, tmp_path)

    plain = _iface(find_item(widget, "plainWord"))
    assert plain.role() == QAccessible.Role.Button
    assert plain.text(QAccessible.Name) == ""

    clobbered = _iface(find_item(widget, "clobbered"))
    assert clobbered.role() == QAccessible.Role.Button
    assert clobbered.text(QAccessible.Name) == "Clobber"


def test_offscreen_face_a_stock_tab_button_exposes_no_action_at_all(
    qtbot, qapp, tmp_path: Path,
) -> None:
    """NRI-0017 (B1, design F4) rationale pinned offscreen: the Qt 6.10
    accessibility bridge gives an unannotated stock TabButton an EMPTY action
    list — a tree consumer cannot actuate a tab at all (live B1 was the same
    hole) — while a plain CheckBox does expose its actions. This is why the
    single-activation press lives INSIDE ThemeTabButton
    (``Accessible.onPressAction: control.click()``; the switch itself is
    pinned on the real island by test_sheet_list_accessibility.py). If a Qt
    update starts exposing tab actions on the stock face, this pin fails and
    the component handler gets re-examined — the quirk must never go
    undocumented a second time."""
    widget = _load_scratch_scene(qtbot, qapp, tmp_path)

    tab = _iface(find_item(widget, "plainTab"))
    assert tab.role() == QAccessible.Role.PageTab
    actions = tab.actionInterface()
    assert actions is not None
    assert list(actions.actionNames()) == [], (
        f"un-annotated stock TabButton now exposes {list(actions.actionNames())!r} "
        "— re-check ThemeTabButton's component-owned onPressAction (NRI-0017 F4)"
    )

    # Contrast (the reason only tabs needed the component-side handler): the
    # other stock families the islands use DO expose Press unannotated.
    check_actions = _iface(find_item(widget, "plainCheck")).actionInterface()
    assert "Press" in check_actions.actionNames()
