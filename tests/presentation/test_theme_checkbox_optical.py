"""nri.components ThemeCheckBox — the optical-center geometry pins (change
nri-0018-grid-alignment-and-card, tasks 2.1–2.2; design Д2).

Spec qml-components «Чекбокс ставит индикатор и подпись на один оптический
центр» + ui-layout-grid «Контролы одного ряда стоят на единой полосе высот»:

* the center of the painted 16 px indicator must coincide with the vertical
  center of the caption's ink — measured through the font metrics of the very
  label item, the caption being the single «Х» in the probe (the task's
  pinning wording: ``FontMetrics.boundingRect("Х")``). Tolerance is one raster
  (design Д2 owner resolution 2026-09-25: the correction
  ``min((descent + leading) / 2, 1)`` is capped at 1 px precisely so it can
  never leave the ±1 px pin tolerance), centers compared at device-pixel
  resolution — the suite pins DPR=1 (conftest), so one device pixel is one
  raster;
* the checkbox's strip (``implicitHeight``) must equal the row's button strip:
  ``ThemeButton``'s own implicit height (its text line box + ``space.sm``
  padding, 32 px at the shipped tokens) — the control that already defines the
  row band in every island action row;
* both pins hold in **both themes**; off-skin (design D7) the control collapses
  without contentItem/indicator — the strip contract never reached that
  degraded state — and the pin there is only that today's metrics/padding keep
  the load clean and the toggle alive.

Why the pins are red before the change: Qt 6.10 does not reposition a
user-supplied (non-style) indicator, so the box sat at the control's (0,0)
~8 px above the caption's ink center, and the Basic style's 6 px vertical
padding gave the checkbox a 28 px strip against the buttons' 32.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QFontMetricsF
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.presentation import qml as qml_shell
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.qml_palette import QmlPalette
from tests.presentation.qml_helpers import click_item, find_item
from tests.ui.test_theme_grab import make_runtime

COMPONENTS_DIR = (
    Path(qml_shell.__file__).resolve().parent / "nri" / "components"
)

# The row band the text buttons already carry (ThemeButton: line box + 2×space.sm
# from the shipped tokens) — pinned identically in the NRI-0018 group-1 grabs.
ROW_STRIP = 32

# The pinning caption: ONE glyph so the measured ink is exactly the glyph the
# spec's FontMetrics.boundingRect("Х") wording describes.
PROBE_CAPTION = "Х"

PROBE_SCENE = """
import QtQuick
import nri.components

Item {
    id: probeRoot
    objectName: "checkboxProbe"
    implicitWidth: 240
    implicitHeight: 140

    ThemeCheckBox {
        id: chk
        objectName: "probeCheck"
        text: "%CAPTION%"
        x: 10; y: 10
    }
    ThemeButton {
        objectName: "probeButton"
        text: "btn"
        x: 10; y: 70
    }
}
""".replace("%CAPTION%", PROBE_CAPTION)


def load_probe(qtbot, qapp, runtime, tmp_path, palette=None) -> QQuickWidget:
    """The checkbox probe on the shared shell engine; ``palette=None`` = off-skin."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "checkbox_probe.qml"
    scene.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(240, 140)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    widget.grab()
    return widget


def ink_center_y(label) -> float:
    """Scene-y of the caption ink center per the task wording.

    The center of ``FontMetrics.boundingRect("Х")`` under the label's own font,
    drawn the way the AlignVCenter contentItem draws it: the line box starts at
    the contentItem's vertical alignment inset, the baseline sits ``ascent``
    below its top, and the measured rect is baseline-relative (its top is
    negative for above-baseline ink) — the same contract QML ``FontMetrics``
    documents and the component's offset formula consumes.
    """
    fm = QFontMetricsF(label.property("font"))
    br = fm.boundingRect(PROBE_CAPTION)
    line_top = label.mapToScene(QPointF(0, 0)).y() + (label.height() - label.implicitHeight()) / 2
    baseline = line_top + fm.ascent()
    return baseline + br.top() + br.height() / 2


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_indicator_center_matches_caption_ink_center(qtbot, qapp, tmp_path, theme):
    """Scenario «Подпись не висит под квадратиком» (both themes): the indicator
    center equals the «Х» ink center within one raster (task 2.1's ±1 px)."""
    runtime = make_runtime(tmp_path, theme)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))

    chk = find_item(widget, "probeCheck")
    indicator = chk.property("indicator")
    assert indicator is not None
    label = chk.property("contentItem")
    assert label is not None

    box_center = indicator.mapToScene(QPointF(0, 0)).y() + indicator.height() / 2
    drift = round(box_center) - round(ink_center_y(label))
    assert abs(drift) <= 1, (
        f"индикатор смещён от центра чернил на {drift} px (box={box_center}, "
        f"ink={ink_center_y(label)})"
    )
    assert widget.errors() == []


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_checkbox_strip_equals_the_button_row_strip(qtbot, qapp, tmp_path, theme):
    """Scenario «Ряд не дрожит» (both themes): the checkbox's strip is the row's
    band — implicitHeight equal to the text button's own (both 32 at the shipped
    tokens; design Д2: top/bottom padding space.sm)."""
    runtime = make_runtime(tmp_path, theme)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))

    chk = find_item(widget, "probeCheck")
    button = find_item(widget, "probeButton")
    assert button.implicitHeight() == ROW_STRIP  # the row band itself, re-pinned
    assert chk.implicitHeight() == button.implicitHeight()
    assert widget.errors() == []


def test_offskin_load_stays_clean_with_the_strip_metrics(qtbot, qapp, tmp_path):
    """D7 off-skin regression: the strip padding and the FontMetrics sit on the
    control itself — while collapsed (no contentItem/indicator off-skin, the
    pre-existing D7 behavior) they never reached a themed strip contract before
    and do not now; what today's additions must guarantee is that the control
    still loads clean and toggles (spec «Off-skin без падения»)."""
    widget = load_probe(qtbot, qapp, make_runtime(tmp_path, "dark"), tmp_path)

    chk = find_item(widget, "probeCheck")
    assert chk.property("skinned") is False
    click_item(widget, chk)
    assert chk.property("checked") is True
    assert widget.errors() == []


def test_optical_offset_formula_and_strip_padding_live_in_the_component():
    """Design Д2's «одно знание — одно место» for the correction itself: the
    capped formula ``min((descent + leading) / 2, 1)`` and the space.sm strip
    padding are declared inside the component — no usage site can re-gauge
    them silently (mirrors the group-1 constant pins)."""
    source = (COMPONENTS_DIR / "ThemeCheckBox.qml").read_text(encoding="utf-8")
    assert re.search(
        r"Math\.min\(\(\w+\.descent \+ \w+\.leading\) / 2, 1\)", source
    ), "offset formula min((descent+leading)/2, 1) must live in the component"
    assert re.search(
        r"topPadding: Tokens\.px\(islandTokens, \"space\.sm\", 8\)", source
    )
    assert re.search(
        r"bottomPadding: Tokens\.px\(islandTokens, \"space\.sm\", 8\)", source
    )
