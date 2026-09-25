"""Component contract of nri.components ThemeDateField (change
nri-0017-accessibility-completers, task 1.1, design F1 — the FI-1/M2 fix).

The live audit found «Дата начала» / «Дата конца» / the snapshot's date field
absent from the tree because the usage sites only hung an ``Accessible.name``
on a role-less ``Control`` (FI-1), and the elided caption cut the year off
long forms (M2). The fix moves role, press and the width floor INSIDE the
component (usage sites keep only the name, per the accessibility contract):

* ``Accessible.role: Button`` and ``Accessible.onPressAction`` — the Press
  emits the very ``clicked()`` the TapHandler emits, so the mock host's
  popup-open handler fires through one and the same path (design F1);
* ``worstCaseText`` (host-supplied worst form of the active calendar; the
  component keeps its own fallback worst mask) drives ``implicitWidth`` and
  ``Layout.minimumWidth``, so a Layout can never shrink the caption below
  the worst form and the year survives without reaching the elide.

Offscreen pins follow the NRI-0012 pattern (``queryAccessibleInterface`` +
``actionInterface().doAction("Press")``).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAccessible, QFont, QFontMetricsF
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from tests.presentation.qml_helpers import find_item

# The component's own fallback worst caption is re-stated here on purpose:
# the pin must fail if the built-in mask is dropped or renamed (a host that
# never passes worstCaseText still must not have its year elided).
FALLBACK_MASK = "00 Сентябрь 0000 г. до н.э."
CUSTOM_WORST = "99 Самыйдлинныймесяцдогон 9999 г. до н.э."

PROBE_SCENE = """
import QtQuick
import QtQuick.Layouts
import nri.components

Item {
    id: probeRoot
    objectName: "dateProbe"
    implicitWidth: 320
    implicitHeight: 160

    // clicked() reaches the mock host — the counter pins the emits (QML
    // signals are not exposed on the Python wrapper of a plain Item).
    property int popupOpens: 0

    ThemeDateField {
        objectName: "probeDate"
        x: 10; y: 10
        isoDate: "1200-03-04"
        display: "04 Март 1200"
        // The usage-site name stays the usage site's (contract: role is the
        // component's, name is applied here).
        Accessible.name: "Дата начала"
        onClicked: probeRoot.popupOpens += 1
    }

    ThemeDateField {
        objectName: "fallbackDate"
        x: 10; y: 50
        // No worstCaseText bound → the component's internal worst mask.
        display: "04 Март 1200"
        Accessible.name: "Дата конца"
    }

    ThemeDateField {
        objectName: "hostWorstDate"
        x: 10; y: 90
        // The host/formatter path: the active calendar's worst form arrives.
        worstCaseText: "%s"
        display: "04 Март 1200"
        Accessible.name: "Дата"
    }

    RowLayout {
        objectName: "narrowRow"
        x: 10; y: 125
        width: 200; height: 30
        // The M2 pin: space is scarce, so an item whose minimum the layout
        // ignores would be squeezed until the caption elides.
        ThemeDateField {
            objectName: "clampedDate"
            Layout.fillWidth: true
            worstCaseText: "%s"
            display: "04 Март 1200"
            Accessible.name: "Дата"
        }
        Rectangle {
            Layout.preferredWidth: 400
            Layout.minimumWidth: 40
            height: 30
            color: "transparent"
        }
    }
}
""" % (CUSTOM_WORST, CUSTOM_WORST)


@pytest.fixture
def runtime(tmp_path):
    tokens_copy = tmp_path / "tokens.json"
    tokens_copy.write_text(
        tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8"
    )
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_copy)


def load_date_probe(qtbot, qapp, runtime, tmp_path, palette=None):
    """The probe on the shared shell engine; ``palette=None`` = off-skin."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "themedatefield_probe.qml"
    scene.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(320, 160)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    widget.grab()
    return widget


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def measured_width(text: str) -> float:
    """Independent Python-side measurement of the caption in the field's
    font (font.size.md is 13 px in both themes, the rest of the font stays
    the application default). Only a sanity bound across the two text
    engines (QFontMetricsF vs QML TextMetrics differ by the few points their
    layouting adds/omits), the pin itself is the component's own number."""
    font = QFont()
    font.setPixelSize(13)
    return QFontMetricsF(font).horizontalAdvance(text)


# ── FI-1: the field is a named button in the tree, opened by Press ─────────


def test_date_field_is_a_named_button_in_the_tree(qtbot, qapp, runtime, tmp_path):
    widget = load_date_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))

    iface = accessible_of(find_item(widget, "probeDate"))
    # FI-1 root cause was a role-less Control: the tree refused the node.
    assert iface.role() == QAccessible.Role.Button
    # The name is the usage-site annotation, non-empty.
    name = iface.text(QAccessible.Name)
    assert name == "Дата начала"


def test_press_emits_clicked_the_popup_open_path(qtbot, qapp, runtime, tmp_path):
    widget = load_date_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    field = find_item(widget, "probeDate")
    assert int(widget.rootObject().property("popupOpens")) == 0

    actions = accessible_of(field).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")
    assert int(widget.rootObject().property("popupOpens")) == 1

    # A second activation opens again — the press handler is no one-shot.
    actions.doAction("Press")
    assert int(widget.rootObject().property("popupOpens")) == 2


def test_offskin_contract_is_identical(qtbot, qapp, runtime, tmp_path):
    widget = load_date_probe(qtbot, qapp, runtime, tmp_path)
    field = find_item(widget, "probeDate")

    iface = accessible_of(field)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Дата начала"
    actions = iface.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")
    assert int(widget.rootObject().property("popupOpens")) == 1


# ── M2: the width floor fits the worst form, fallback and host-supplied ────


def test_fallback_worst_mask_sets_the_width_floor(qtbot, qapp, runtime, tmp_path):
    widget = load_date_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    field = find_item(widget, "fallbackDate")

    # Without a host worstCaseText the component measures its own fallback
    # mask; implicitWidth additionally carries the paddings, so it can only
    # exceed the measured text.
    assert str(field.property("worstCaseText")) == ""
    measured = float(field.property("worstCaseWidth"))
    # The mask really is what got measured (cross-engine sanity, see
    # measured_width), and implicitWidth adds the paddings on top.
    assert measured >= measured_width(FALLBACK_MASK) * 0.95
    assert float(field.implicitWidth()) >= measured


def test_host_worst_case_text_drives_implicit_width(qtbot, qapp, runtime, tmp_path):
    widget = load_date_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    field = find_item(widget, "hostWorstDate")

    assert str(field.property("worstCaseText")) == CUSTOM_WORST
    measured = float(field.property("worstCaseWidth"))
    assert measured >= measured_width(CUSTOM_WORST) * 0.95
    assert float(field.implicitWidth()) >= measured
    # The host's longer form really widened the field past the fallback mask.
    fallback = float(find_item(widget, "fallbackDate").property("worstCaseWidth"))
    assert measured > fallback


def test_layout_cannot_shrink_the_caption_below_the_worst_form(
    qtbot, qapp, runtime, tmp_path
):
    """M2: in a cramped RowLayout the field keeps at least its worst-case
    width — the year can no longer be elided away."""
    widget = load_date_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    field = find_item(widget, "clampedDate")

    measured = float(field.property("worstCaseWidth"))
    assert float(field.width()) >= measured > 0.0
    # The squeeze really happened: the row is narrower than both preferred
    # widths summed, so a layout-ignoring item would have got far less.
    assert float(find_item(widget, "narrowRow").width()) < 200 + 400
