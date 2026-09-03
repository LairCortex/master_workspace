"""Launcher QML island (change add-qml-shell-launcher-pilot-q1, tasks 5.1–5.3).

The island (``app/presentation/qml/LauncherRoot.qml``) is loaded into a real
``QQuickWidget`` with the test palette and the view model injected as context
properties — exactly the two names the island binds against (design D6:
``palette`` + ``vm``). Coverage per task:

* 5.1 smoke: ``status == Ready`` and all six objectNames of the interactive
  controls are present; the theme toggle's label shows the *target* theme.
* 5.2 e2e: the row model follows ``vm.games`` without touching qml, a row tap
  lands in ``vm.selected_path``, «Открыть» emits the island's open signal with
  that path — and the whole flow runs on the untouched ``LauncherViewModel``
  (spec qml-shell «VM не знает про QML» proof).
* 5.3 pixel acceptance (convention of tests/test_qml_render_smoke.py): a
  background pixel equals ``color.bg.surface``, an accent-button pixel equals
  ``color.accent`` in both themes; a runtime theme switch repaints the same
  live island (no re-creation, selection kept); an empty palette (off-skin,
  design D7) still loads, keeps the basic Controls look, raises nothing.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QPoint, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest

import app.infrastructure.db.game_manager as game_manager
from app.infrastructure.db.game_manager import GameInfo
from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation import qml as qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.viewmodels.launcher_viewmodel import LauncherViewModel

QML_ROOT_FILE = Path(qml_shell.__file__).resolve().parent / "LauncherRoot.qml"

# The objectName contract of the island (spec game-launcher: each interactive
# control addressable by tests) — spelled out literally to fail on renames.
INTERACTIVE_OBJECT_NAMES = (
    "gameList",
    "newButton",
    "importButton",
    "deleteButton",
    "openButton",
    "themeToggleButton",
)

BASE_TIME = datetime(2026, 1, 1)
LABEL_FORMAT = "%Y-%m-%d %H:%M"


# ── fakes & fixture plumbing ──────────────────────────────────────────────────


class FakeCatalog:
    """In-memory catalog stand-in (same pattern as the VM unit tests)."""

    def __init__(self) -> None:
        self.entries: list[GameInfo] = []
        self._seq = 0

    def _next_modified(self) -> datetime:
        self._seq += 1
        return BASE_TIME + timedelta(minutes=self._seq)

    def list_games(self) -> list[GameInfo]:
        return [dict(e) for e in self.entries]

    def create_game(self, name: str) -> str:
        if any(e["name"] == name for e in self.entries):
            raise FileExistsError(f"Game '{name}' already exists")
        path = f"/games/{name}/game.db"
        self.entries.append(GameInfo(name=name, path=path, modified=self._next_modified()))
        return path

    def delete_game(self, path: str) -> None:
        self.entries = [e for e in self.entries if e["path"] != path]

    def import_game(self, archive_path):  # pragma: no cover - not used here
        raise NotImplementedError

    def read_archive_meta(self, archive_path):  # pragma: no cover - not used here
        raise NotImplementedError


@pytest.fixture
def catalog(monkeypatch):
    fake = FakeCatalog()
    for fn in ("list_games", "create_game", "delete_game", "import_game", "read_archive_meta"):
        monkeypatch.setattr(game_manager, fn, getattr(fake, fn))
    return fake


@pytest.fixture
def vm(catalog):
    return LauncherViewModel()


@pytest.fixture
def tokens_file(tmp_path):
    """Private copy of the shipped tokens — corruptions must not touch it."""
    dst = tmp_path / "tokens.json"
    dst.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture
def runtime(tmp_path, tokens_file):
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file)


@pytest.fixture
def palette(runtime):
    return QmlPalette(runtime)


# ── island plumbing helpers ───────────────────────────────────────────────────


def load_island(qtbot, *, vm, palette, size=(480, 400)) -> QQuickWidget:
    """QQuickWidget with the island's two context properties (D6 contract).

    The widget runs on its own engine (the island unit is engine-agnostic —
    the shared shell engine is covered in test_qml_engine.py); only the
    context contract is identical: the root object reads ``vm`` and
    ``palette`` and nothing else from Python. Since
    add-qml-component-library-q2a1 that contract also includes the
    module-import seam: the island now resolves ``import nri.components``, so
    this loader adds the same import path the production engine installs in
    ``setup_qml_shell`` (``addImportPath(QML_IMPORT_PATH)``) — engine
    plumbing only, no assertion or island-context property changes.
    """
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")

    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.resize(*size)
    # The library-module seam (design D1): import the production import path
    # so the launcher's bare test engine resolves ``import nri.components``
    # exactly like the shared shell engine does.
    widget.engine().addImportPath(qml_shell.QML_IMPORT_PATH)
    # Context properties keep raw pointers without owning them (an object
    # whose Python reference dies becomes ``null`` in QML — a hazard for the
    # production wrapper too, which is why GameLauncherDialog keeps holding
    # its VM). Pin both to the widget's lifetime for the test.
    vm.setParent(widget)
    palette.setParent(widget)
    widget.rootContext().setContextProperty("vm", vm)
    # The island reads the bridge as ``islandPalette`` (bare «palette» is
    # shadowed by Controls in any scope — see LauncherRoot.qml header).
    widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(QML_ROOT_FILE)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def walk_items(root: QQuickItem):
    """All descendant visual items.

    Two lookup facts pinned the hard way on Qt 6.10 software-rendered
    ``QQuickWidget``: ``findChild`` never reaches the scene of a widget whose
    window is unexposed, and delegate rows are not ``QObject`` children of
    their view (the delegate model manages them) — only ``childItems()``
    (the visual tree) sees them.
    """
    stack = [root]
    while stack:
        for child in stack.pop().childItems():
            yield child
            stack.append(child)


def find_items(widget: QQuickWidget, object_name: str) -> list[QQuickItem]:
    return [i for i in walk_items(widget.rootObject()) if i.objectName() == object_name]


def find_item(widget: QQuickWidget, object_name: str) -> QQuickItem:
    items = find_items(widget, object_name)
    assert len(items) == 1, f"expected exactly one {object_name!r}, got {len(items)}"
    return items[0]


def rows(widget: QQuickWidget) -> list[QQuickItem]:
    """Delegate rows top-to-bottom (flickable order, not child-list order).

    ``grab`` first: delegate materialization is driven by the render pass —
    an already-filled model only gets items after a render (or any item
    change), so tests render once before addressing rows.
    """
    widget.grab()
    found = find_items(widget, "gameRow")
    found.sort(key=lambda r: r.mapToScene(QPointF(0, 0)).y())
    return found


def row_texts(widget: QQuickWidget) -> list[str]:
    out = []
    for row in rows(widget):
        texts = [i for i in walk_items(row) if i.objectName() == "gameRowText"]
        assert len(texts) == 1
        out.append(texts[0].property("text"))
    return out


def grab_rgb(widget: QQuickWidget) -> QImage:
    img = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not img.isNull()
    return img


def token_rgb(hex_value: str) -> tuple[int, int, int]:
    color = QColor(hex_value)
    assert color.isValid()
    return (color.red(), color.green(), color.blue())


def pixel_rgb(img: QImage, scene_x: float, scene_y: float, widget: QQuickWidget):
    """Pixel under a *scene* point; grab may be scaled by device pixel ratio."""
    sx = img.width() / widget.width()
    sy = img.height() / widget.height()
    x = min(int(scene_x * sx), img.width() - 1)
    y = min(int(scene_y * sy), img.height() - 1)
    color = img.pixelColor(x, y)
    return (color.red(), color.green(), color.blue())


def surface_pixel(widget: QQuickWidget, img: QImage | None = None):
    """Far top-left corner margin — background only, away from all content."""
    return pixel_rgb(img or grab_rgb(widget), 3, 3, widget)


def button_pixel(widget: QQuickWidget, button: QQuickItem, img: QImage | None = None):
    """A point inside the button's left padding band — button background
    guaranteed, text glyphs centered in the middle are avoided."""
    point = button.mapToScene(QPointF(4, button.height() / 2))
    return pixel_rgb(img or grab_rgb(widget), point.x(), point.y(), widget)


def click_item(widget: QQuickWidget, item: QQuickItem, *, double: bool = False) -> None:
    center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    pos = QPoint(int(center.x()), int(center.y()))
    click = QTest.mouseDClick if double else QTest.mouseClick
    click(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(0)  # let the quick window consume the event


def find_island_vm(widget: QQuickWidget):
    return widget.rootContext().contextProperty("vm")


def track(signal) -> list:
    emits: list = []
    signal.connect(lambda *args: emits.append(args))
    return emits


# ── 5.1: smoke — loads Ready, objectName contract, toggle label ──────────────


def test_island_loads_ready_and_all_six_object_names_exist(qtbot, vm, palette):
    widget = load_island(qtbot, vm=vm, palette=palette)
    assert widget.errors() == []
    for name in INTERACTIVE_OBJECT_NAMES:
        assert find_item(widget, name) is not None, name
    # «Открыть» is the marked default action of the screen (spec
    # game-launcher; Basic Qt 6 Buttons have no «default» property, the
    # island exposes the marker as root.defaultButton).
    assert widget.rootObject().property("defaultButton") is find_item(widget, "openButton")


def test_island_reads_only_palette_and_vm_from_context(qtbot, catalog, palette):
    """The island's context contract (what group 6 must replicate): it must
    load with ONLY ``vm`` + ``palette`` — no service, no theme runtime."""
    # NOTE (contract for the wrapper): context properties keep raw pointers —
    # Python must keep the objects alive (a temporary here would be GC'd).
    island_vm = LauncherViewModel()
    widget = load_island(qtbot, vm=island_vm, palette=palette)
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    catalog.create_game("Проверка")
    vm = find_island_vm(widget)  # the very object handed to the context
    assert vm is island_vm
    vm.refresh()
    # FakeCatalog stamps create_game with BASE_TIME + 1 minute.
    stamp = (BASE_TIME + timedelta(minutes=1)).strftime(LABEL_FORMAT)
    assert row_texts(widget) == [f"Проверка ({stamp})"]


def test_theme_toggle_label_shows_the_target_theme(qtbot, vm, palette):
    widget = load_island(qtbot, vm=vm, palette=palette)
    toggle = find_item(widget, "themeToggleButton")
    # App defaults to dark → the toggle offers the light theme.
    assert widget.rootObject().property("currentTheme") == "dark"
    assert toggle.property("text") == "Светлая тема"

    # The embedding syncs the current theme whenever anything changes it;
    # the island re-labels the toggle with the new *target* theme.
    widget.rootObject().setProperty("currentTheme", "light")
    assert toggle.property("text") == "Тёмная тема"


# ── 5.2: e2e binding, selection, open signal on the real VM ──────────────────


def test_game_rows_follow_vm_without_any_qml_changes(qtbot, catalog, vm, palette):
    widget = load_island(qtbot, vm=vm, palette=palette)
    assert rows(widget) == []  # empty catalog: no rows

    catalog.entries.append(
        GameInfo(name="Погоня", path="/games/Погоня/game.db", modified=BASE_TIME)
    )
    vm.refresh()  # plain VM call — qml untouched
    assert row_texts(widget) == [f"Погоня ({BASE_TIME.strftime(LABEL_FORMAT)})"]

    vm.create("Дар")  # row appears through the VM's gamesChanged notify
    labels = [
        BASE_TIME.strftime(LABEL_FORMAT),
        (BASE_TIME + timedelta(minutes=1)).strftime(LABEL_FORMAT),
    ]
    assert row_texts(widget) == [
        f"Дар ({labels[1]})",      # newest first
        f"Погоня ({labels[0]})",
    ]

    vm.remove("/games/Дар/game.db")  # row disappears again
    assert len(rows(widget)) == 1


def test_row_tap_sets_selected_path_on_vm(qtbot, catalog, vm, palette):
    vm.create("Погоня")
    vm.create("Дар")  # newest first: Дар (0), Погоня (1)
    widget = load_island(qtbot, vm=vm, palette=palette)
    assert vm.selected_path is None

    click_item(widget, rows(widget)[1])
    assert vm.selectedIndex == 1
    assert vm.selected_path == "/games/Погоня/game.db"


def test_open_button_emits_signal_with_selected_path(qtbot, catalog, vm, palette):
    vm.create("Погоня")
    widget = load_island(qtbot, vm=vm, palette=palette)
    opens = track(vm.openRequested)

    click_item(widget, rows(widget)[0])
    click_item(widget, find_item(widget, "openButton"))
    assert opens == [("/games/Погоня/game.db",)]


def test_open_button_without_selection_is_noop(qtbot, catalog, vm, palette):
    vm.create("Погоня")
    widget = load_island(qtbot, vm=vm, palette=palette)
    opens = track(vm.openRequested)

    click_item(widget, find_item(widget, "openButton"))
    assert opens == []


def test_double_click_on_row_opens_that_game(qtbot, catalog, vm, palette):
    vm.create("Погоня")
    vm.create("Дар")
    widget = load_island(qtbot, vm=vm, palette=palette)
    opens = track(vm.openRequested)

    click_item(widget, rows(widget)[1], double=True)
    assert opens == [("/games/Погоня/game.db",)]


def test_control_buttons_emit_vm_request_signals(qtbot, catalog, vm, palette):
    vm.create("Погоня")
    vm.create("Дар")
    widget = load_island(qtbot, vm=vm, palette=palette)
    creates = track(vm.createRequested)
    imports = track(vm.importRequested)
    deletes = track(vm.deleteRequested)

    click_item(widget, find_item(widget, "newButton"))
    click_item(widget, find_item(widget, "importButton"))
    # «Удалить» without a selection: the spec asks for a no-op…
    click_item(widget, find_item(widget, "deleteButton"))
    assert creates == [("",)]
    assert imports == [("",)]
    assert deletes == []

    # …with a selection it carries the VM row index.
    click_item(widget, rows(widget)[1])
    click_item(widget, find_item(widget, "deleteButton"))
    assert deletes == [(1,)]


def test_theme_toggle_click_emits_island_signal(qtbot, vm, palette):
    widget = load_island(qtbot, vm=vm, palette=palette)
    toggles = track(widget.rootObject().themeToggleRequested)
    click_item(widget, find_item(widget, "themeToggleButton"))
    assert toggles == [()]


def test_island_on_real_launcher_viewmodel_unchanged(qtbot, catalog, palette, monkeypatch):
    """Spec qml-shell «VM не знает про QML» proof (task 5.2).

    The island binds to the exact production ``LauncherViewModel`` class —
    no subclass, no patched attribute, no contract edit — and the full
    micro flow (rows → selection → open) works through it.
    """
    real_vm = LauncherViewModel()
    assert type(real_vm) is LauncherViewModel  # no subclass stand-in

    real_vm.create("Погоня")
    real_vm.create("Дар")
    widget = load_island(qtbot, vm=real_vm, palette=palette)
    assert [t.split(" (")[0] for t in row_texts(widget)] == ["Дар", "Погоня"]

    click_item(widget, rows(widget)[1])
    assert real_vm.selected_path == "/games/Погоня/game.db"

    opens = track(real_vm.openRequested)
    click_item(widget, find_item(widget, "openButton"))
    assert opens == [("/games/Погоня/game.db",)]

    # The VM's public mutation API repaints the island without qml changes.
    real_vm.remove("/games/Дар/game.db")
    assert len(rows(widget)) == 1
    assert real_vm.selected_path is None  # list shrank: selection reset


# ── 5.3: pixel acceptance, live retheme, off-skin degradation ────────────────


def test_pixel_acceptance_and_live_retheme_same_island(qtbot, catalog, vm, runtime, palette):
    """Background = color.bg.surface, accent button = color.accent, both
    themes; the theme switch repaints THIS island (no re-creation)."""
    vm.create("Погоня")
    click_probe = None
    widget = load_island(qtbot, vm=vm, palette=palette)
    open_button = find_item(widget, "openButton")
    image = grab_rgb(widget)
    assert widget.grab().width() == widget.width()  # grab is at logical size

    # Dark theme (runtime default) — exact token pixels.
    assert runtime.theme == "dark"
    tokens = palette.tokens
    assert tokens["color.bg.surface"].startswith("#")
    assert surface_pixel(widget, image) == token_rgb(tokens["color.bg.surface"])
    assert button_pixel(widget, open_button, image) == token_rgb(tokens["color.accent"])

    # A selection made before the retheme must survive it (spec Live-retheme).
    click_item(widget, rows(widget)[0])
    click_probe = widget.rootObject()

    assert runtime.toggle() is True  # dark → light, "someone else's" switch
    expected_bg = token_rgb(palette.tokens["color.bg.surface"])
    expected_accent = token_rgb(palette.tokens["color.accent"])

    def repainted() -> bool:
        img = grab_rgb(widget)
        return surface_pixel(widget, img) == expected_bg and (
            button_pixel(widget, open_button, img) == expected_accent
        )

    qtbot.waitUntil(repainted, timeout=5000)

    # Same island object survived the retheme — nothing was re-created.
    assert widget.rootObject() is click_probe
    assert find_item(widget, "openButton") is open_button
    assert vm.selected_path == "/games/Погоня/game.db"  # selection kept

    # …and back to dark (both directions, still no recreation).
    assert runtime.toggle() is True
    expected_bg = token_rgb(palette.tokens["color.bg.surface"])
    expected_accent = token_rgb(palette.tokens["color.accent"])
    qtbot.waitUntil(
        lambda: surface_pixel(widget) == expected_bg
        and button_pixel(widget, open_button) == expected_accent,
        timeout=5000,
    )


def test_offskin_empty_palette_loads_basic_without_errors(qtbot, catalog, vm, tmp_path):
    """Design D7: broken tokens → empty palette → the island still loads,
    controls keep the basic Controls look and stay fully functional."""
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    runtime = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad)
    off_skin_palette = QmlPalette(runtime)
    assert off_skin_palette.tokens == {}

    widget = load_island(qtbot, vm=vm, palette=off_skin_palette)
    assert widget.status() == QQuickWidget.Status.Ready
    assert widget.errors() == []  # no binding exceptions with undefined tokens

    # All interactive controls exist with their plain (Basic) look.
    for name in INTERACTIVE_OBJECT_NAMES:
        item = find_item(widget, name)
        assert item.width() > 0 and item.height() > 0
    assert find_item(widget, "openButton").property("text") == "Открыть"
    assert find_item(widget, "newButton").property("text") == "Новая игра"

    # Functional too: fill the list through the VM, select, open — no errors.
    vm.create("Погоня")
    assert len(rows(widget)) == 1
    opens = track(vm.openRequested)
    click_item(widget, rows(widget)[0])
    click_item(widget, find_item(widget, "openButton"))
    assert opens == [("/games/Погоня/game.db",)]
    assert widget.errors() == []


def test_custom_accent_in_token_file_repaints_island_without_qml_edits(
    qtbot, catalog, vm, tmp_path, tokens_file
):
    """Spec qml-shell «Смена accent без правок qml» (both themes): editing the
    ``color.accent`` value *in the token file* reaches the island pixels
    through the palette bridge — the qml source is loaded from disk verbatim
    and never edited, so an island that hardcoded the token's value (or a hex
    of its own) could not pass."""
    data = json.loads(tokens_file.read_text(encoding="utf-8"))
    # Custom accents distinct from the shipped ones, so the assertion below
    # cannot accidentally pass on the stock tokens.
    assert data["color.accent"]["dark"] != "#0e4a16"
    assert data["color.accent"]["light"] != "#5a0e0e"
    data["color.accent"]["dark"] = "#0e4a16"
    data["color.accent"]["light"] = "#5a0e0e"
    tokens_file.write_text(json.dumps(data), encoding="utf-8")

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file
    )
    palette = QmlPalette(runtime)
    assert palette.tokens["color.accent"] == "#0e4a16"  # dark is the default

    vm.create("Погоня")
    widget = load_island(qtbot, vm=vm, palette=palette)
    open_button = find_item(widget, "openButton")
    assert button_pixel(widget, open_button) == token_rgb("#0e4a16")

    # Second theme with its own custom accent — same island, no reload.
    assert runtime.toggle() is True
    qtbot.waitUntil(
        lambda: button_pixel(widget, open_button) == token_rgb("#5a0e0e"),
        timeout=5000,
    )
    assert widget.errors() == []
