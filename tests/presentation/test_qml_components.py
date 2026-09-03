"""nri.components library (change add-qml-component-library-q2a1,
tasks 1.1–1.2 and the group-2 component acceptance floor).

The qmldir module ships in ``app/presentation/qml/nri/components/`` and the
smoke surface is the module's own ``smoke.qml``; it imports the module but
instantiates none of the qmldir-listed component types (those land with
group 2 — qmldir type entries resolve lazily, which is exactly what keeps
these smokes green today: an unused missing type must not dirty the error
list, and the with-palette smoke pins that expectation).

Coverage per task:

* 1.1 — the smoke loads ``Ready`` with an empty ``errors()`` while carrying
  a real ``import nri.components``; the load runs on the one shared shell
  engine, so module resolution travels through ``setup_qml_shell``'s
  production import path (spec qml-shell «Модуль библиотеки резолвится из
  import-пути» — the same path a PyInstaller bundle will expose).
* 1.2 — ``token()``/``px()`` now live in the stateless ``tokens.js``
  (``.pragma library``). The smoke looks the bridge up with the
  ``typeof islandPalette`` insurance: with a palette in the context the
  probes equal the palette's own entries; with no ``islandPalette`` anywhere
  in the context chain the probes are exactly the fallbacks and the engine
  raised nothing (mirrors design D7's off-skin semantics).

Group 2 (tasks 2.1–2.5) adds the component instantiation floor: a throwaway
probe scene (written to tmp, importing ``nri.components`` through the same
shared-engine import path) instantiates all eight qmldir types and pins, in
three configurations — valid palette, broken tokens (empty palette) and no
``islandPalette`` in the context at all — that the load errors stay empty,
the ``skinned`` flags flip, and click/selection/input keep working off-skin.

Group 4 (tasks 4.1–4.4) is the library's acceptance suite (design D6): the
gallery island ``qml_components_gallery.qml`` (every component under a stable
``objectName``) loads on the shared shell engine with the offscreen software
backend, pixel acceptance compares each themed surface with the hex token in
*both* themes (surfaces via exact pixels at known offsets, text roles via an
exact token pixel inside the text item's bounds — no golden images, spec
«Пиксельная приёмка компонентов библиотеки»), live retheme repaints one
already-loaded gallery through the palette bridge alone (island «Смена токена
перекрашивает»), and the two off-skin runs (empty/broken tokens; no bridge in
the context at all) keep ``errors()`` empty with skin off and interactions
alive (spec «Поведение компонентов вне валидной темы (off-skin)»).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation import qml as qml_shell
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime

QML_DIR = Path(qml_shell.__file__).resolve().parent
MODULE_DIR = QML_DIR / "nri" / "components"
QMLDIR_FILE = MODULE_DIR / "qmldir"
TOKENS_JS = MODULE_DIR / "tokens.js"
SMOKE_FILE = MODULE_DIR / "smoke.qml"

# The fallback literals smoke.qml resolves to when the bridge is absent.
FALLBACK_ACCENT = "skeleton-fallback"
FALLBACK_PX = -1.0


@pytest.fixture
def tokens_file(tmp_path):
    """Private copy of the shipped tokens (pattern of test_launcher_qml.py)."""
    dst = tmp_path / "tokens.json"
    dst.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture
def runtime(tmp_path, tokens_file):
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file)


@pytest.fixture
def palette(runtime):
    return QmlPalette(runtime)


def load_smoke(qtbot, qapp, runtime, palette: QmlPalette | None) -> QQuickWidget:
    """The smoke on the one shared shell engine («общим движком»).

    ``setup_qml_shell`` is what installs the production import path, so
    loading here proves the module resolves exactly like it will in the
    frozen bundle. QQuickWidget hands a non-owning engine reference, and the
    widget's rootContext IS the engine root context — hence one variant per
    test: conftest's autouse ``isolated_qml_shell`` gives every test a fresh
    engine, so the bridge of the with-palette variant can never leak into
    the without-bridge variant.
    """
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(160, 80)
    if palette is not None:
        # Context properties keep raw pointers: pin the bridge to the
        # widget's lifetime (same hazard the production wrapper manages).
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(SMOKE_FILE)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


# ── 1.1: qmldir scaffolding — declared module, lazy future types, clean load ──


def test_smoke_imports_module_on_shared_engine_with_clean_errors(qtbot, qapp, runtime, palette):
    widget = load_smoke(qtbot, qapp, runtime, palette)
    # A qmldir whose future type files do not exist yet must not produce a
    # single error while no such type is used (the group 1/2 seam).
    assert widget.errors() == []
    assert widget.rootObject().property("objectName") == "componentsSmoke"
    # The load ran on the one shared engine: resolving `import
    # nri.components` here proves the shell's single addImportPath call is
    # sufficient for the module (no extra paths, no file copies).
    assert widget.engine() is qml_shell.qml_engine()


def test_qmldir_declares_module_and_future_component_entries():
    lines = [
        stripped
        for stripped in (
            line.split("#", 1)[0].strip()
            for line in QMLDIR_FILE.read_text(encoding="utf-8").splitlines()
        )
        if stripped
    ]
    assert lines[0] == "module nri.components"
    # The contract group 2 implements: one entry per component, file names
    # mirroring the type names (design D4's set, spelled out to fail on
    # silent renames).
    assert lines[1:] == [
        f"{name} {name}.qml"
        for name in (
            "ThemeButton",
            "ThemeField",
            "ThemeCheckBox",
            "ThemeComboBox",
            "TitleText",
            "HintText",
            "CardPanel",
            "RowItem",
        )
    ]
    assert TOKENS_JS.is_file()


# ── 1.2: tokens.js helpers — resolve with the bridge, fall back without it ───


def test_smoke_resolves_tokens_through_the_js_library_when_palette_exists(
    qtbot, qapp, runtime, palette
):
    widget = load_smoke(qtbot, qapp, runtime, palette)
    assert widget.errors() == []
    root = widget.rootObject()
    tokens = palette.tokens  # dark theme is the runtime default
    # The probes are the palette's own values, not the library fallbacks:
    # token() really read the bridge passed across the typeof-insured seam.
    assert root.property("accentProbe") == tokens["color.accent"] != FALLBACK_ACCENT
    # px() read the numeric part of the same CSS-sized token ("16px" -> 16).
    expected_px = float(str(tokens["space.md"]).removesuffix("px"))
    assert float(root.property("spaceProbe")) == expected_px


def test_smoke_without_palette_falls_back_without_exceptions(qtbot, qapp, runtime):
    widget = load_smoke(qtbot, qapp, runtime, palette=None)
    # No islandPalette anywhere in the context chain: the typeof insurance
    # degrades to pure fallbacks and the engine raised nothing.
    assert widget.errors() == []
    root = widget.rootObject()
    assert root.property("accentProbe") == FALLBACK_ACCENT
    assert float(root.property("spaceProbe")) == FALLBACK_PX


def test_smoke_with_an_explicit_null_bridge_falls_back_without_exceptions(
    qtbot, qapp, runtime
):
    """The insurance's second leg: a *null* stand-in for the bridge.

    ``typeof islandPalette`` reports ``"object"`` for a null context
    property, so `resolveTokens` additionally pins ``=== null`` (design D2,
    mirroring the gallery's guard). This test drives that branch directly:
    the property exists and is null, the probes still land on the fallbacks
    and nothing throws.
    """
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(160, 80)
    widget.rootContext().setContextProperty("islandPalette", None)
    widget.setSource(QUrl.fromLocalFile(str(SMOKE_FILE)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    assert widget.errors() == []
    root = widget.rootObject()
    assert root.property("accentProbe") == FALLBACK_ACCENT
    assert float(root.property("spaceProbe")) == FALLBACK_PX


# ── group 2 (tasks 2.1–2.5): component instantiation + off-skin floor ────────
#
# Pixel acceptance (per-control token look in both themes, live-retheme
# gallery, planted-violation js scan) is task 4.x; this is the floor group 2
# owes itself: every qmldir type instantiates through `import
# nri.components` with a clean error list — with a valid palette, with
# broken tokens and with no bridge at all — while interactions keep working
# off-skin (spec «Поведение компонентов вне валидной темы»).

# The probe scene is deliberately NOT a shipped qml file: it lives in tmp,
# resolves `import nri.components` through the shared engine's production
# import path, and exposes plain-value probes Python can read every time.
PROBE_SCENE = """
import QtQuick
import nri.components

Item {
    id: probe
    objectName: "libraryProbe"
    implicitWidth: 420
    implicitHeight: 330

    // interaction counters islands would wire to their view models
    property int buttonClicks: 0
    property int rowTaps: 0
    property int rowActivations: 0

    // combo-delegate probe: the themed delegate Component materializes
    // rows through the combo's own popup, but a windowless offscreen
    // widget can never show that popup here — so the scene clones the
    // delegate template into a local list. Same template, same bindings:
    // instantiation errors (skinned tokens or off-skin fallbacks) surface
    // in errors() either way. Rows are counted Python-side off the view's
    // contentItem after a render pass (the delegate-materialization fact
    // the launcher row tests pin).

    // aggregate + live-retheme probes (component properties, so the notify
    // of the component's own token bindings is what these re-evaluate on)
    property bool allSkinned: btn.skinned && fld.skinned && chk.skinned
        && cbo.skinned && ttl.skinned && hnt.skinned && card.skinned && rw.skinned
    // Off-skin escape detector: off-skin tests must prove NO single component
    // stays skinned (the AND above cannot see one stubborn control).
    property bool anySkinned: btn.skinned || fld.skinned || chk.skinned
        || cbo.skinned || ttl.skinned || hnt.skinned || card.skinned || rw.skinned
    property color btnAccent: btn.accentColor
    property color rowFill: rw.color

    // hover/pressed derivation probes (spec «Источник оформления — только
    // палитра токенов»: the compiler ships color.accent.hover/pressed; design
    // D3: the button consumes exactly those derivations, never its own
    // colors). String probes pin the pass-through: with the bridge the
    // accessors return the compiler's value verbatim, off-skin the caller's
    // base falls through — a drifted token NAME on either side trips these.
    property string hoverProbe: btn.accentHover("base-hover")
    property string pressedProbe: btn.accentPressed("base-pressed")

    ThemeButton {
        id: btn
        objectName: "probeButton"
        text: "Btn"
        accentBackground: true
        x: 10; y: 10
        onClicked: probe.buttonClicks += 1
    }
    ThemeField { id: fld; objectName: "probeField"; x: 10; y: 50; width: 180 }
    ThemeCheckBox { id: chk; objectName: "probeCheck"; text: "Chk"; x: 10; y: 95 }
    ThemeComboBox { id: cbo; objectName: "probeCombo"; model: ["a", "b"]; x: 10; y: 130 }
    TitleText { id: ttl; objectName: "probeTitle"; text: "Title"; x: 10; y: 175 }
    HintText { id: hnt; objectName: "probeHint"; text: "Hint"; x: 10; y: 200 }
    CardPanel { id: card; objectName: "probeCard"; x: 10; y: 225; width: 120; height: 40 }
    RowItem {
        id: rw
        objectName: "probeRow"
        text: "Row"
        textObjectName: "probeRowText"
        x: 10; y: 275
        width: 200
        height: implicitHeight
        onSelectedRequested: probe.rowTaps += 1
        onActivateRequested: probe.rowActivations += 1
    }

    ListView {
        id: delegateProbe
        objectName: "probeDelegate"
        x: 240; y: 10
        width: 160; height: 120
        model: ["a", "b"]
        delegate: cbo.delegate
    }
}
"""

PROBE_OBJECT_NAMES = (
    "probeButton",
    "probeField",
    "probeCheck",
    "probeCombo",
    "probeTitle",
    "probeHint",
    "probeCard",
    "probeRow",
)


def _walk_items(root: QQuickItem):
    stack = [root]
    while stack:
        for child in stack.pop().childItems():
            yield child
            stack.append(child)


def _find_item(widget: QQuickWidget, object_name: str) -> QQuickItem:
    found = [i for i in _walk_items(widget.rootObject()) if i.objectName() == object_name]
    assert len(found) == 1, f"expected exactly one {object_name!r}, got {len(found)}"
    return found[0]


def _delegate_probe_rows(widget: QQuickWidget) -> int:
    """Materialized clones of the combo's delegate template.

    ``grab`` first: delegate materialization is render-pass driven (same
    fact ``test_launcher_qml.rows`` pins for the launcher list).
    """
    widget.grab()
    view = _find_item(widget, "probeDelegate")
    content = view.property("contentItem")
    return len(content.childItems()) if content is not None else 0


def _click(widget: QQuickWidget, item: QQuickItem, *, double: bool = False) -> None:
    center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    pos = QPoint(int(center.x()), int(center.y()))
    click = QTest.mouseDClick if double else QTest.mouseClick
    click(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(0)


def load_probe_scene(
    qtbot, qapp, runtime, palette: "QmlPalette | None", scene_file: Path
) -> QQuickWidget:
    """The all-types probe scene on the one shared shell engine.

    Same plumbing as ``load_smoke`` (production import path, per-test
    isolated engine): the scene resolves ``import nri.components`` exactly
    like an island does.
    """
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")
    scene_file.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(420, 330)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene_file)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def test_all_component_types_instantiate_with_valid_palette(qtbot, qapp, runtime, palette, tmp_path):
    widget = load_probe_scene(qtbot, qapp, runtime, palette, tmp_path / "probe.qml")
    # Every qmldir type instantiates under a valid bridge with no error.
    assert widget.errors() == []
    for name in PROBE_OBJECT_NAMES:
        assert _find_item(widget, name) is not None, name
    # The internal cell text stays addressable through the alias escape
    # hatch (group 3 needs it to keep the launcher's objectName contract).
    assert _find_item(widget, "probeRowText") is not None
    root = widget.rootObject()
    assert root.property("allSkinned") is True
    # hover/pressed reach the button verbatim from the compiler's derivation
    # (design D3's consumption contract — the button adds no color engine).
    tokens = palette.tokens
    assert root.property("hoverProbe") == tokens["color.accent.hover"] != "base-hover"
    assert root.property("pressedProbe") == tokens["color.accent.pressed"] != "base-pressed"
    # The button's token surface carries the palette's own accent…
    assert root.property("btnAccent") == QColor(tokens["color.accent"])
    # Row selection paints the list-role pair (accent fill for the row,
    # accent.fg text — property-level stand-in for the group-4 pixels).
    _find_item(widget, "probeRow").setProperty("selected", True)
    assert root.property("rowFill") == QColor(palette.tokens["color.accent"])
    assert _find_item(widget, "probeRowText").property("color") == QColor(
        palette.tokens["color.accent.fg"]
    )
    # …and a live retheme propagates it through the components' own
    # tokens.js lookup (no island re-creation — spec «Смена токена»).
    assert runtime.toggle() is True
    qtbot.waitUntil(
        lambda: root.property("btnAccent") == QColor(palette.tokens["color.accent"]),
        timeout=5000,
    )
    # …and the hover/pressed probes track the NEW theme through the same
    # bridge (the derivations are per-theme compiler values).
    qtbot.waitUntil(
        lambda: root.property("hoverProbe") == palette.tokens["color.accent.hover"]
        and root.property("pressedProbe") == palette.tokens["color.accent.pressed"],
        timeout=5000,
    )
    # Cloning the combo delegate template into a local list instantiates
    # themed rows (tokens here, fallbacks in the off-skin test below)
    # without engine errors.
    qtbot.waitUntil(lambda: _delegate_probe_rows(widget) >= 2, timeout=5000)
    assert widget.errors() == []


def test_all_component_types_degrade_offskin_with_broken_tokens(
    qtbot, qapp, tmp_path
):
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    runtime = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad)
    off_skin_palette = QmlPalette(runtime)
    assert off_skin_palette.tokens == {}

    widget = load_probe_scene(qtbot, qapp, runtime, off_skin_palette, tmp_path / "probe.qml")
    assert widget.status() == QQuickWidget.Status.Ready
    assert widget.errors() == []
    for name in PROBE_OBJECT_NAMES:
        item = _find_item(widget, name)
        assert item.width() > 0 and item.height() > 0, name
    root = widget.rootObject()
    assert root.property("allSkinned") is False  # design D7: no skin is drawn
    assert root.property("anySkinned") is False  # not even one component stays skinned
    # Off-skin the hover/pressed accessors fall through to the caller's base
    # (no derivation without a bridge — the button stays plain Basic).
    assert root.property("hoverProbe") == "base-hover"
    assert root.property("pressedProbe") == "base-pressed"

    # Interactions stay alive on the plain Basic controls (spec «Off-skin
    # без падения»): click the button, toggle the checkbox, type into the
    # field, tap and activate the row.
    _click(widget, _find_item(widget, "probeButton"))
    assert root.property("buttonClicks") == 1
    checkbox = _find_item(widget, "probeCheck")
    _click(widget, checkbox)
    assert checkbox.property("checked") is True
    field = _find_item(widget, "probeField")
    field.setProperty("text", "off-skin typing")
    assert field.property("text") == "off-skin typing"
    row = _find_item(widget, "probeRow")
    _click(widget, row)
    assert root.property("rowTaps") == 1
    _click(widget, row, double=True)
    assert root.property("rowActivations") == 1
    # The off-skin delegate clone tree instantiates on the named-global
    # fallbacks too — same template, no exceptions.
    qtbot.waitUntil(lambda: _delegate_probe_rows(widget) >= 2, timeout=5000)
    assert widget.errors() == []


def test_all_component_types_load_without_bridge_in_context(qtbot, qapp, runtime, tmp_path):
    # No islandPalette in the context chain at all: the typeof insurance
    # (design D2's documented cost) degrades every component to off-skin —
    # visible items, no skin, no exceptions.
    widget = load_probe_scene(qtbot, qapp, runtime, None, tmp_path / "probe.qml")
    assert widget.status() == QQuickWidget.Status.Ready
    assert widget.errors() == []
    for name in PROBE_OBJECT_NAMES:
        _find_item(widget, name)
    assert widget.rootObject().property("allSkinned") is False
    assert widget.rootObject().property("anySkinned") is False


# ── group 4 (tasks 4.1–4.4): gallery island, pixel acceptance, retheme ────────
#
# The gallery (``qml_components_gallery.qml``, shipped under tests/ — not an
# app file) instantiates every library component under a stable objectName.
# Pixel acceptance follows the convention of test_qml_render_smoke.py /
# test_launcher_qml.py: grab() + exact-token pixels, no golden images. The
# page rectangle paints the *color.danger* token — a token no component
# surface uses — so each themed surface (canvas, surface, border, accent,
# text colours) is distinguishable from its surround in both themes; text
# roles are pinned by an exact token pixel inside the text item's own bounds
# with a fixed glyph set ("WMW"/"WWW"/"MMM").

GALLERY_FILE = Path(__file__).resolve().parent / "qml_components_gallery.qml"

GALLERY_OBJECT_NAMES = (
    "galleryButtonAccent",
    "galleryButtonPlain",
    "galleryField",
    "galleryCheckBox",
    "galleryCombo",
    "galleryTitle",
    "galleryHint",
    "galleryCard",
    "galleryRow",
    "galleryRowText",
    "galleryComboRows",
)

# The off-skin fallbacks the guarded lookups (gallery page included) land on
# — pinned here so the off-skin tests can demand the fallback actually paints.
FALLBACK_PAGE_RGB = (211, 211, 211)  # QColor("lightgray")

_THEME_VALUES = ("dark", "light")


def load_gallery(qtbot, qapp, runtime, palette: "QmlPalette | None") -> QQuickWidget:
    """The gallery on the one shared shell engine (the 4.1 loader contract).

    Same seam as ``load_smoke``/``load_probe_scene``: ``setup_qml_shell``'s
    production import path resolves ``import nri.components``; the
    offscreen software backend (conftest) makes ``grab()`` pixel-meaningful;
    conftest's ``isolated_qml_shell`` gives every test its own engine, so the
    no-bridge variant below really has no ``islandPalette`` anywhere — it
    cannot inherit a bridge planted by another test.
    """
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(420, 330)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(GALLERY_FILE)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def _grab_rgb(widget: QQuickWidget) -> QImage:
    img = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not img.isNull()
    return img


def _token_rgb(hex_value: str) -> tuple[int, int, int]:
    color = QColor(hex_value)
    assert color.isValid(), hex_value
    return (color.red(), color.green(), color.blue())


def _item_pixel(widget, img, item, local_x: float, local_y: float):
    """Pixel under a point given in the item's own coordinate system."""
    point = item.mapToScene(QPointF(local_x, local_y))
    sx = img.width() / widget.width()
    sy = img.height() / widget.height()
    x = min(int(point.x() * sx), img.width() - 1)
    y = min(int(point.y() * sy), img.height() - 1)
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def _exact_pixel_in_bounds(widget, img, item, rgb: tuple[int, int, int]):
    """Scene coordinates of the first exact ``rgb`` pixel inside ``item``.

    The text-role acceptance helper (task 4.2): antialiased glyph cores stay
    exact, so one equal pixel inside the text bounds pins the painted colour
    without any golden image (spec «Пиксельная приёмка компонентов»).
    """
    sx = img.width() / widget.width()
    sy = img.height() / widget.height()
    steps_x = max(1, int(item.width()))
    steps_y = max(1, int(item.height()))
    for iy in range(steps_y):
        for ix in range(steps_x):
            scene = item.mapToScene(QPointF(ix + 0.5, iy + 0.5))
            px = int(scene.x() * sx)
            py = int(scene.y() * sy)
            if px < 0 or py < 0 or px >= img.width() or py >= img.height():
                continue
            c = img.pixelColor(px, py)
            if (c.red(), c.green(), c.blue()) == rgb:
                return (px, py)
    return None


def _gallery_combo_rows(widget) -> list[QQuickItem]:
    """The combo delegate clones materialized by the gallery's probe list.

    Only the ItemDelegate clones count (the flickable keeps unnamed helper
    children in its contentItem); top-to-bottom by scene position.
    """
    view = _find_item(widget, "galleryComboRows")
    content = view.property("contentItem")
    rows = [
        r for r in (content.childItems() if content is not None else [])
        if "ItemDelegate" in r.metaObject().className()
    ]
    rows.sort(key=lambda r: r.mapToScene(QPointF(0, 0)).y())
    return rows


@pytest.fixture(params=_THEME_VALUES)
def themed(request, runtime):
    """The runtime switched to the parametrized theme *before* the load."""
    assert runtime.set_theme(request.param) is True
    return request.param


def test_gallery_loads_ready_with_all_object_names_on_shared_engine(
    qtbot, qapp, runtime, palette
):
    # 4.1: smoke — the gallery island comes up Ready, error-free, carrying an
    # objectName for every library component, on the one shared engine (the
    # module resolved through the production import path exactly as in the
    # frozen bundle).
    widget = load_gallery(qtbot, qapp, runtime, palette)
    assert widget.errors() == []
    assert widget.engine() is qml_shell.qml_engine()
    assert widget.rootObject().property("objectName") == "componentsGallery"
    for name in GALLERY_OBJECT_NAMES:
        assert _find_item(widget, name) is not None, name
    assert widget.rootObject().property("allSkinned") is True


def test_gallery_surfaces_match_tokens_in_both_themes(qtbot, qapp, runtime, themed):
    # 4.2: every themed surface of every themeized component — button accent /
    # plain fills and the plain border, field background/border/focus-border/
    # typed text, checkbox unchecked+checked indicator + label text, combo
    # field + display text + delegate rows, title & hint text, card fill,
    # row selected fill + selected/unselected text — equals the current
    # theme's token value, offscreen, both themes, no goldens.
    palette = QmlPalette(runtime)
    tokens = palette.tokens
    # The page paints color.danger: a surround that equals no component
    # surface, so every token pixel checked below is painted, not seen-through.
    page_rgb = _token_rgb(tokens["color.danger"])
    canvas_rgb = _token_rgb(tokens["color.bg.canvas"])
    surface_rgb = _token_rgb(tokens["color.bg.surface"])
    border_rgb = _token_rgb(tokens["color.border"])
    accent_rgb = _token_rgb(tokens["color.accent"])
    accent_fg_rgb = _token_rgb(tokens["color.accent.fg"])
    fg_rgb = _token_rgb(tokens["color.fg.primary"])
    muted_rgb = _token_rgb(tokens["color.fg.muted"])
    # The surround shares no value with any checked surface — the distinctness
    # that makes every pixel assertion below non-vacuous in this theme.
    assert page_rgb not in (canvas_rgb, surface_rgb, border_rgb, accent_rgb,
                            accent_fg_rgb, fg_rgb, muted_rgb), tokens

    widget = load_gallery(qtbot, qapp, runtime, palette)
    assert widget.errors() == []

    button = _find_item(widget, "galleryButtonAccent")
    plain = _find_item(widget, "galleryButtonPlain")
    field = _find_item(widget, "galleryField")
    checkbox = _find_item(widget, "galleryCheckBox")
    combo = _find_item(widget, "galleryCombo")
    title = _find_item(widget, "galleryTitle")
    hint = _find_item(widget, "galleryHint")
    card = _find_item(widget, "galleryCard")
    row = _find_item(widget, "galleryRow")
    row_text = _find_item(widget, "galleryRowText")

    # ── state-free surfaces (single grab) ──────────────────────────────────
    img = _grab_rgb(widget)
    # The guarded page fill proves the bridge reaches non-control items too.
    assert _item_pixel(widget, img, widget.rootObject(), 2, 320) == page_rgb
    # Buttons: accent fill vs canvas fill; the plain button's 1px edge is the
    # border token, its padding band the canvas token (surround is the danger
    # token, so an unpainted border could not fake the edge pixel).
    assert _item_pixel(widget, img, button, 4, button.height() / 2) == accent_rgb
    assert _item_pixel(widget, img, plain, 4, plain.height() / 2) == canvas_rgb
    assert _item_pixel(widget, img, plain, 0, plain.height() / 2) == border_rgb
    # Field background + idle border.
    assert _item_pixel(widget, img, field, field.width() - 10, field.height() / 2) == canvas_rgb
    assert _item_pixel(widget, img, field, 0, field.height() / 2) == border_rgb
    # Checkbox (unchecked): indicator is the canvas token, label the fg token.
    box = checkbox.property("indicator")
    assert box is not None
    assert _item_pixel(widget, img, box, 3, 3) == canvas_rgb
    label = checkbox.property("contentItem")
    assert label is not None
    assert _exact_pixel_in_bounds(widget, img, label, fg_rgb) is not None
    # Combo field + display text.
    assert _item_pixel(widget, img, combo, 60, combo.height() / 2) == canvas_rgb
    display = combo.property("contentItem")
    assert display is not None
    assert _exact_pixel_in_bounds(widget, img, display, fg_rgb) is not None
    # Text roles: an exact token glyph pixel exists inside the fixed glyphs.
    assert _exact_pixel_in_bounds(widget, img, title, fg_rgb) is not None
    assert _exact_pixel_in_bounds(widget, img, hint, muted_rgb) is not None
    # Card: surface fill and the border-coloured hairline.
    assert _item_pixel(widget, img, card, 20, 20) == surface_rgb
    assert _item_pixel(widget, img, card, 0, card.height() / 2) == border_rgb
    # Row unselected: transparent fill (the danger surround shows through it),
    # fg text.
    assert _item_pixel(widget, img, row, 2, row.height() / 2) == page_rgb
    assert _exact_pixel_in_bounds(widget, img, row_text, fg_rgb) is not None

    # ── state-dependent surfaces (interaction states of the skinned set) ───
    field.setProperty("text", "WWW")
    checkbox.setProperty("checked", True)
    row.setProperty("selected", True)
    qtbot.waitUntil(lambda: len(_gallery_combo_rows(widget)) >= 2, timeout=5000)
    img = _grab_rgb(widget)
    assert _exact_pixel_in_bounds(widget, img, field, fg_rgb) is not None
    # Checked indicator flips to the accent fill (the tick on top is accentFg
    # geometry — sampled beside it, the fill itself).
    assert _item_pixel(widget, img, box, 3, 3) == accent_rgb
    assert _exact_pixel_in_bounds(widget, img, row_text, accent_fg_rgb) is not None
    assert _item_pixel(widget, img, row, 2, row.height() / 2) == accent_rgb
    # The delegate template (popup rows in production) materializes on the
    # same tokens: canvas fill, fg text. The highlighted-row pair is the
    # catalog list-role selection pair — pixel-pinned as RowItem's selected
    # state above; Qt keeps ComboBox.highlightedIndex pinned to -1 while the
    # popup is closed, and QQuickPopup is not exposed to PySide at all, so no
    # headless route to the real popup exists here.
    rows = _gallery_combo_rows(widget)
    for delegate_row in (rows[0], rows[1]):
        assert _item_pixel(widget, img, delegate_row, 2, delegate_row.height() / 2) == canvas_rgb
        assert _exact_pixel_in_bounds(widget, img, delegate_row, fg_rgb) is not None

    # Focus border: activeFocus repaints the field frame with the accent.
    field.forceActiveFocus()
    img = _grab_rgb(widget)
    assert _item_pixel(widget, img, field, 0, field.height() / 2) == accent_rgb
    assert widget.errors() == []


def test_gallery_live_retheme_repaints_without_recreating_the_island(
    qtbot, qapp, runtime, palette
):
    # 4.3: one gallery, one island — a palette-driven theme switch repaints
    # every themed surface to the new theme's hexes with zero re-creation
    # (spec «Смена токена перекрашивает библиотеку», scenario «Пиксель равен
    # токену»'s after-toggle half).
    widget = load_gallery(qtbot, qapp, runtime, palette)
    assert widget.errors() == []
    assert runtime.theme == "dark"
    button = _find_item(widget, "galleryButtonAccent")
    hint = _find_item(widget, "galleryHint")
    card = _find_item(widget, "galleryCard")
    row = _find_item(widget, "galleryRow")
    row.setProperty("selected", True)
    root_before = widget.rootObject()

    accent = _token_rgb(palette.tokens["color.accent"])
    muted = _token_rgb(palette.tokens["color.fg.muted"])
    surface = _token_rgb(palette.tokens["color.bg.surface"])
    img = _grab_rgb(widget)
    assert _item_pixel(widget, img, button, 4, button.height() / 2) == accent
    assert _exact_pixel_in_bounds(widget, img, hint, muted) is not None
    assert _item_pixel(widget, img, card, 20, 20) == surface

    assert runtime.toggle() is True  # dark → light, a bridge-only switch
    new_accent = _token_rgb(palette.tokens["color.accent"])
    new_muted = _token_rgb(palette.tokens["color.fg.muted"])
    new_surface = _token_rgb(palette.tokens["color.bg.surface"])
    assert new_accent != accent  # the parametrized tokens.json really differs

    def repainted() -> bool:
        img = _grab_rgb(widget)
        return (
            _item_pixel(widget, img, button, 4, button.height() / 2) == new_accent
            and _item_pixel(widget, img, card, 20, 20) == new_surface
            and _exact_pixel_in_bounds(widget, img, hint, new_muted) is not None
        )

    qtbot.waitUntil(repainted, timeout=5000)
    # The island is the very same objects — nothing was re-created.
    assert widget.rootObject() is root_before
    assert _find_item(widget, "galleryButtonAccent") is button
    img = _grab_rgb(widget)
    assert _item_pixel(widget, img, row, 2, row.height() / 2) == new_accent
    assert widget.rootObject().property("allSkinned") is True
    assert widget.errors() == []

    # …and back (light → dark), the gallery keeps repainting both ways.
    assert runtime.toggle() is True
    qtbot.waitUntil(
        lambda: _item_pixel(widget, _grab_rgb(widget), button,
                            4, button.height() / 2) == accent,
        timeout=5000,
    )
    assert widget.errors() == []


def _offskin_gallery_interactions(widget, qtbot) -> None:
    """The shared off-skin interaction battery (spec «Off-skin без падения»).

    Click lands (button counter), input works (real key events reach the
    field), focus works (activeFocus + focus-driven repaint stays quiet),
    toggles and row signals fire — and none of it dirties ``errors()``.
    """
    root = widget.rootObject()
    _click(widget, _find_item(widget, "galleryButtonAccent"))
    assert root.property("buttonClicks") == 1

    checkbox = _find_item(widget, "galleryCheckBox")
    _click(widget, checkbox)
    assert checkbox.property("checked") is True

    field = _find_item(widget, "galleryField")
    field.forceActiveFocus()
    assert field.property("activeFocus") is True
    QTest.keyClicks(widget, "abc")
    qtbot.waitUntil(lambda: field.property("text") == "abc", timeout=5000)

    row = _find_item(widget, "galleryRow")
    _click(widget, row)
    assert root.property("rowTaps") == 1
    _click(widget, row, double=True)
    assert root.property("rowActivations") == 1

    qtbot.waitUntil(lambda: len(_gallery_combo_rows(widget)) >= 2, timeout=5000)
    assert widget.errors() == []


def test_gallery_offskin_with_broken_tokens_loads_unskinned_and_stays_alive(
    qtbot, qapp, tmp_path
):
    # 4.4 run A — empty/broken tokens: the palette bridge exists but its
    # dictionary is empty (QmlPalette's off-skin contract); the guarded
    # lookups degrade: no skin (allSkinned false), the guarded page paints
    # its named-global fallback, errors() stays empty, interactions work.
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    runtime = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad)
    off_skin_palette = QmlPalette(runtime)
    assert off_skin_palette.tokens == {}

    widget = load_gallery(qtbot, qapp, runtime, off_skin_palette)
    assert widget.status() == QQuickWidget.Status.Ready
    assert widget.errors() == []
    root = widget.rootObject()
    assert root.property("allSkinned") is False
    assert root.property("anySkinned") is False
    for name in GALLERY_OBJECT_NAMES:
        item = _find_item(widget, name)
        assert item.width() > 0 and item.height() > 0, name
    # The page's guarded read fell back to the named global, not a crash.
    img = _grab_rgb(widget)
    assert _item_pixel(widget, img, root, 2, 320) == FALLBACK_PAGE_RGB
    _offskin_gallery_interactions(widget, qtbot)


def test_gallery_offskin_with_no_bridge_at_all_in_the_context(qtbot, qapp, runtime):
    # 4.4 run B — the stricter variant: no ``islandPalette`` anywhere in the
    # context. conftest's isolated_qml_shell gives this test its own engine
    # and ``load_gallery`` never sets the property, so the context really has
    # no bridge to inherit; the typeof insurance (design D2) then degrades
    # the entire gallery off-skin — same contract as run A, without a
    # single exception.
    widget = load_gallery(qtbot, qapp, runtime, palette=None)
    assert widget.status() == QQuickWidget.Status.Ready
    assert widget.rootContext().contextProperty("islandPalette") is None
    assert widget.errors() == []
    root = widget.rootObject()
    assert root.property("allSkinned") is False
    assert root.property("anySkinned") is False
    img = _grab_rgb(widget)
    assert _item_pixel(widget, img, root, 2, 320) == FALLBACK_PAGE_RGB
    _offskin_gallery_interactions(widget, qtbot)
