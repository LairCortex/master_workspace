"""Component contract of nri.components ThemeCheckBox — the accessibility
press (live audit 2026-09-30 F2, docs/qa/2026-09-30-lucide-pass-main-window.md).

The live audit caught the launcher's «Светлая тема»: an ``AXPress`` flipped the
tick while ``onClicked`` stayed silent — the stock accessibility activation of
a CheckBox writes ``checked`` without a user gesture, so the action wired on
the click (the theme toggle, the whole NRI-0023 Д15/OBS-2 convention) never
fired and the tick lied about the state (NRI-0016 D2: the state lives ONLY in
the tick). The fix mirrors ThemeTabButton (NRI-0017 F4): the press handler
lives INSIDE the component (``Accessible.onPressAction: control.click()``), so
one accessibility Press runs the very click a mouse runs.

Offscreen pins follow the NRI-0012 pattern (``queryAccessibleInterface`` +
``actionInterface().doAction("Press")``). The single-toggle/single-emit claim
is MEASURED, not assumed: the stock Basic CheckBox also exposes a Press, so
the probe counts ``clicked`` emits and ``checked`` flips across presses — a
double actuation (attached handler + default action) would count 2 emits or a
net-zero flip and fail here. The штатно role stays CheckBox (a role-losing
annotation would break the 4.2 contract and this pin together).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from tests.presentation.qml_helpers import find_item, track
from tests.ui.test_theme_grab import make_runtime

PROBE_SCENE = """
import QtQuick
import nri.components

Item {
    id: probeRoot
    objectName: "checkboxA11yProbe"
    implicitWidth: 240
    implicitHeight: 160

    // The F2 measurement: QML signals are not exposed on the Python wrapper
    // of a plain Item, so the root counts what the Press must produce exactly
    // once per activation (checked itself is read off the control).
    property int clicks: 0

    ThemeCheckBox {
        objectName: "probePress"
        text: "Светлая тема"
        x: 10; y: 10
        onClicked: probeRoot.clicks += 1
    }
}
"""


def load_probe(qtbot, qapp, runtime, tmp_path, palette=None) -> QQuickWidget:
    """The checkbox probe on the shared shell engine; ``palette=None`` = off-skin."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "checkbox_a11y_probe.qml"
    scene.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(240, 160)
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


def press(item) -> None:
    actions = accessible_of(item).actionInterface()
    assert "Press" in actions.actionNames(), (
        f"{item.objectName()!r} exposes accessibility actions "
        f"{list(actions.actionNames())!r} — the checkbox is unreachable to a "
        "single Press (F2)"
    )
    actions.doAction("Press")


def measure_press(widget: QQuickWidget) -> None:
    """One Press = one tick flip + one clicked emit, both directions (F2)."""
    chk = find_item(widget, "probePress")
    root = widget.rootObject()
    assert bool(chk.property("checked")) is False
    assert int(root.property("clicks")) == 0

    press(chk)
    assert bool(chk.property("checked")) is True, "first Press did not flip the tick"
    assert int(root.property("clicks")) == 1, (
        f"first Press emitted clicked {int(root.property('clicks'))} times — "
        "expected exactly 1 (a double actuation or a silent handler)"
    )

    press(chk)
    assert bool(chk.property("checked")) is False, "second Press did not flip back"
    assert int(root.property("clicks")) == 2, (
        f"two Presses emitted clicked {int(root.property('clicks'))} times — "
        "expected exactly 2 (one emit per activation)"
    )
    assert widget.errors() == []


# ── the component contract: role stays штатно, Press = one real click ────────


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_checkbox_keeps_the_stock_checkbox_role(qtbot, qapp, tmp_path, theme):
    """The attached press handler must not touch the штатно tree face (4.2):
    the role reaches the interface as CheckBox in both themes."""
    runtime = make_runtime(tmp_path, theme)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    assert accessible_of(find_item(widget, "probePress")).role() == QAccessible.Role.CheckBox


def test_press_clicks_and_flips_the_tick_exactly_once(qtbot, qapp, tmp_path):
    """F2 pin, skinned: one doAction("Press") toggles ``checked`` once AND
    emits ``clicked`` once — the numbers are counted, so a second (default)
    actuation alongside the component handler cannot hide in the net result."""
    runtime = make_runtime(tmp_path, "dark")
    widget = load_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    measure_press(widget)


def test_offskin_press_contract_is_identical(qtbot, qapp, tmp_path):
    """D7: off-skin (no palette) the control re-materializes as the Basic
    CheckBox but the component press contract holds unchanged."""
    widget = load_probe(qtbot, qapp, make_runtime(tmp_path, "dark"), tmp_path)
    chk = find_item(widget, "probePress")
    assert bool(chk.property("skinned")) is False
    measure_press(widget)


# ── the live F2 pairing: AX-pressing the launcher checkbox switches the theme ─


def test_launcher_checkbox_press_switches_the_theme(qtbot, tmp_path):
    """F2 end-to-end offscreen: GameLauncherDialog + themeToggleButton, Press
    once → the island's themeToggleRequested reaches the dialog exactly once,
    ThemeRuntime.theme flipped dark→light, and the tick rides the runtime
    (never lies ahead of it). The prefs live in tmp_path — the real
    ~/.nri_manager is never written."""
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    assert runtime.theme == "dark"
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    # NRI-0024 4.1: the island moved into the shared launcher content.
    quick = dlg.content.quick

    toggles = track(quick.rootObject().themeToggleRequested)
    chk = find_item(quick, "themeToggleButton")
    assert bool(chk.property("checked")) is False

    press(chk)

    assert toggles == [()], (
        f"one Press emitted themeToggleRequested {len(toggles)} times — "
        "expected exactly 1 (the F2 hole: 0 = tick lies, 2 = double actuation)"
    )
    assert runtime.theme == "light", "the AX press did not reach ThemeRuntime"
    assert bool(chk.property("checked")) is True, "the tick does not ride the runtime"
    assert quick.rootObject().property("currentTheme") == "light"

    # And back — the press is no one-shot (mouse parity both directions).
    press(chk)
    assert len(toggles) == 2
    assert runtime.theme == "dark"
    assert bool(chk.property("checked")) is False
