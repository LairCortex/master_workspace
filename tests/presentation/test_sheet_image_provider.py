"""Sheet island font + ``image://sheet`` provider (change Q3b 1.3, design D7).

The font: registration lives on the island's python side and runs inside
``setup_qml_shell`` before any island loads; the TTF path is unchanged
(``fonts/DejaVuSans.ttf`` next to the sheet views package, same ``.spec``
datas). ``register_sheet_font`` stays once-per-process and reports a missing
file in the log rather than mis-rendering silently.

The provider: ``image://sheet/<imageId>`` resolves through the bound
ImageStore (the current game's), returning real bytes for a real id and an
empty (zero-size) image — never a crash — for anything unknowable: missing
row, missing file, malformed id, no store. The async store coroutine is
bridged from QML's reader thread via run_coroutine_threadsafe; a request on
the loop's own thread is refused instead of deadlocking qasync.
"""
from __future__ import annotations

import asyncio

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtQuick import QQuickImageProvider

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.sheet_font import (
    SHEET_FONT_FAMILY,
    register_sheet_font,
    sheet_font,
)
from app.presentation.qml.sheet_image_provider import (
    SHEET_IMAGE_PROVIDER_ID,
    SheetImageHub,
    SheetImageProvider,
    bind_sheet_image_store,
)
from app.presentation.theme import get_default_theme


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def png_path(tmp_path):
    path = tmp_path / "picture.png"
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(QColor("magenta"))
    assert img.save(str(path), "PNG")
    return path


class FakeStore:
    """Stand-in for ImageStore: async id → path, exactly the real coroutine."""

    def __init__(self, paths: dict[int, object]) -> None:
        self.paths = dict(paths)
        self.calls: list[int] = []

    async def original_file_path(self, image_id: int):
        self.calls.append(image_id)
        return self.paths.get(image_id)


@pytest.fixture(autouse=True)
def _clean_provider_globals():
    yield
    bind_sheet_image_store(None)
    import app.presentation.qml.sheet_image_provider as sip

    sip._pending_store = None


# ── font (moved out of canvas.py without weakening) ──────────────────────────


def test_register_font_registers_the_bundled_family(qapp, monkeypatch):
    import app.presentation.qml.sheet_font as sheet_font_mod

    monkeypatch.setattr(sheet_font_mod, "_font_registered", False)
    register_sheet_font()
    assert sheet_font_mod._font_registered is True
    from PySide6.QtGui import QFontDatabase

    db = QFontDatabase()
    assert SHEET_FONT_FAMILY in db.families()
    # the module-level helper is the same font at the point size asked for
    assert sheet_font(14.5).pointSizeF() == 14.5


def test_shell_setup_registers_font_before_islands_can_load(qapp, monkeypatch):
    import app.presentation.qml.sheet_font as sheet_font_mod
    import app.presentation.qml.engine as engine_mod

    monkeypatch.setattr(sheet_font_mod, "_font_registered", False)
    calls: list[str] = []
    monkeypatch.setattr(
        engine_mod, "register_sheet_font", lambda: calls.append("font")
    )
    monkeypatch.setattr(
        engine_mod,
        "register_sheet_image_provider",
        lambda engine: calls.append("provider"),
    )
    engine = setup_qml_shell(qapp, get_default_theme())
    assert calls == ["font", "provider"]  # font first, provider on the engine
    assert engine is not None


def test_shell_setup_installs_provider_and_family_on_a_real_engine(qapp, monkeypatch):
    """No stubs: the real shell registers the real provider and font."""
    import app.presentation.qml.sheet_font as sheet_font_mod

    monkeypatch.setattr(sheet_font_mod, "_font_registered", False)
    engine = setup_qml_shell(qapp, get_default_theme())
    provider = engine.imageProvider(SHEET_IMAGE_PROVIDER_ID)
    assert provider is not None
    assert isinstance(provider, QQuickImageProvider)
    # the hub retry channel is registered together with the provider (D7):
    # the same hub the QML delegates watch under ``sheetImages`` (a context
    # property) must back the engine's provider — without it every cold
    # QQuickWidget request would be refused and never retried.
    from app.presentation.qml.sheet_image_provider import SHEET_IMAGE_HUB_NAME

    hub = engine.rootContext().contextProperty(SHEET_IMAGE_HUB_NAME)
    assert isinstance(hub, SheetImageHub)
    assert provider._hub is hub
    # idempotent registration: a second call must not replace the provider
    from app.presentation.qml.sheet_image_provider import register_sheet_image_provider

    register_sheet_image_provider(engine)
    assert engine.imageProvider(SHEET_IMAGE_PROVIDER_ID) is provider
    assert engine.rootContext().contextProperty(SHEET_IMAGE_HUB_NAME) is hub
    from PySide6.QtGui import QFontDatabase

    assert SHEET_FONT_FAMILY in QFontDatabase().families()


def test_font_still_lives_next_to_the_widgets_canvas():
    """The ``.spec`` datas were *not* touched by Q3b 1.3: the registration has
    a new python home, the bundled TTF stays in the canvas module's ``fonts/``
    directory until the canvas itself is deleted (Q3b 3.4). True for the dev
    tree and for the PyInstaller onedir bundle (``__file__`` resolves inside
    it, so ``_MEIPASS`` adds nothing). If a bundle layout appears elsewhere,
    this fails and the ``_font_path`` resolution must be revisited."""
    from pathlib import Path

    from app.presentation.qml import sheet_font as sheet_font_mod

    path = sheet_font_mod._font_path()
    assert path.is_file()
    assert path == (
        Path(sheet_font_mod.__file__).resolve().parents[1]
        / "views"
        / "character_sheet"
        / "fonts"
        / "DejaVuSans.ttf"
    )


# ── provider: id → bytes / absence → empty, never a crash ────────────────────


def test_provider_resolves_id_to_the_image_bytes(qapp, png_path):
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({3: png_path}))
    image = provider.requestImage("3", QSize(), QSize())
    assert not image.isNull()
    assert image.width() == 8 and image.height() == 8
    assert image.pixelColor(0, 0) == QColor("magenta")


def test_provider_scales_to_the_requested_size(qapp, png_path):
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({7: png_path}))
    image = provider.requestImage("7", QSize(), QSize(4, 4))
    # keep-aspect into 4x4 → exactly 4x4 here (square source)
    assert image.width() <= 4 and image.height() <= 4
    assert image.width() > 0


def test_provider_missing_id_is_empty_not_a_crash(qapp):
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({}))
    image = provider.requestImage("404", QSize(), QSize())
    assert image.isNull()
    assert image.width() == 0 and image.height() == 0


def test_provider_unknown_shapes_are_empty(qapp, tmp_path):
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({"x": None}))
    assert provider.requestImage("not-a-number", QSize(), QSize()).isNull()
    assert provider.requestImage("../etc/passwd", QSize(), QSize()).isNull()
    assert provider.requestImage("5?w=2", QSize(), QSize()).isNull()  # query stripped
    provider.bind_store(FakeStore({5: tmp_path / "gone.png"}))  # row w/o file
    assert provider.requestImage("5", QSize(), QSize()).isNull()
    provider.bind_store(None)  # no store bound (no game)
    assert provider.requestImage("5", QSize(), QSize()).isNull()


def test_provider_rebinding_drops_path_cache(qapp, png_path, tmp_path):
    other = tmp_path / "other.png"
    other.write_bytes(png_path.read_bytes())
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({1: png_path}))
    assert not provider.requestImage("1", QSize(), QSize()).isNull()
    provider.bind_store(FakeStore({}))  # game closed / switched mid-session
    assert provider.requestImage("1", QSize(), QSize()).isNull()


def test_provider_bridges_store_coroutine_off_the_loop_thread(qapp, png_path):
    """The app path: a running qasync loop, a request from the reader thread."""

    async def scenario():
        loop = asyncio.get_running_loop()
        provider = SheetImageProvider()
        provider.bind_store(FakeStore({2: png_path}))  # captures this loop
        assert provider._loop is loop
        return await asyncio.to_thread(
            provider.requestImage, "2", QSize(), QSize()
        )

    image = asyncio.run(scenario())
    assert not image.isNull()
    assert image.width() == 8


def test_provider_refuses_on_the_loop_thread_instead_of_deadlocking(qapp, png_path):
    """Synchronous load *on* the qasync loop thread would hang the app —
    it must come back empty instead (the canvas loads asynchronously)."""

    async def scenario():
        provider = SheetImageProvider()
        provider.bind_store(FakeStore({2: png_path}))
        return provider.requestImage("2", QSize(), QSize())  # same thread

    image = asyncio.run(scenario())
    assert image.isNull()


def test_engine_singleton_provider_gets_bound_store(qapp, png_path):
    engine = setup_qml_shell(qapp, get_default_theme())
    bind_sheet_image_store(FakeStore({9: png_path}))
    provider = engine.imageProvider(SHEET_IMAGE_PROVIDER_ID)
    image = provider.requestImage("9", QSize(), QSize())
    assert not image.isNull()
    # rebinding None (game closed) detaches the engine's provider as well
    bind_sheet_image_store(None)
    assert provider.requestImage("9", QSize(), QSize()).isNull()


# ── full-pipeline guards (change Q3b acceptance 4.3: every resolver rule
#    of the module docstring has a probe, so no branch ships untested) ───────


def test_request_pixmap_is_the_qt6_sync_entry(qapp, png_path):
    """Qt 6 calls requestPixmap directly (no requestImage fallback): the
    override must hand out the pixmap for a real id and a null QPixmap for
    the unknown one (the QML reader's contract)."""
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({3: png_path}))
    pixmap = provider.requestPixmap("3", QSize(), QSize())
    assert not pixmap.isNull()
    assert pixmap.width() == 8
    assert provider.requestPixmap("404", QSize(), QSize()).isNull()


def test_provider_unreadable_file_is_empty_not_a_crash(qapp, tmp_path):
    # Row points at an existing file whose bytes no decoder accepts: the
    # same null-image degradation as a missing file (never an exception
    # inside Qt's image reader).
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"definitely not a PNG")
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({4: broken}))
    assert provider.requestImage("4", QSize(), QSize()).isNull()


def test_provider_cache_entry_goes_stale_when_the_file_dies(qapp, png_path):
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({6: png_path}))
    assert not provider.requestImage("6", QSize(), QSize()).isNull()
    # Second hit: still warm, no store re-call needed.
    calls_before = len(provider._paths)
    assert not provider.requestImage("6", QSize(), QSize()).isNull()
    assert len(provider._paths) == calls_before
    png_path.unlink()  # image GC removed the file behind the cache entry
    assert provider.requestImage("6", QSize(), QSize()).isNull()
    assert 6 not in provider._paths  # the stale entry stopped being trusted


def test_provider_store_raising_synchronously_degrades_to_null(qapp):
    class BoomStore:
        def original_file_path(self, image_id):  # sync DB blow-up
            raise RuntimeError("database is locked")

    provider = SheetImageProvider()
    provider.bind_store(BoomStore())
    assert provider.requestImage("9", QSize(), QSize()).isNull()


def test_hub_prefetch_answers_null_then_resolves_the_delegate(qapp, png_path):
    """The QQuickWidget/hub flow (module docstring, D7): a loop-thread cold
    request answers null AND schedules the lookup; the hub's ``resolved`` is
    the delegate's reload cue; the second request hits the warm cache."""
    hub = SheetImageHub()
    resolved: list[int] = []
    hub.resolved.connect(resolved.append)

    async def scenario():
        provider = SheetImageProvider(hub=hub)
        provider.bind_store(FakeStore({2: png_path}))
        cold = provider.requestImage("2", QSize(), QSize())
        cold_again = provider.requestImage("2", QSize(), QSize())
        # the same cold id pending a task is not re-scheduled twice
        assert len(provider._pending) == 1
        for _ in range(100):
            await asyncio.sleep(0)
            if resolved:
                break
        warm = provider.requestImage("2", QSize(), QSize())
        return cold, cold_again, warm, provider

    cold, cold_again, warm, provider = asyncio.run(scenario())
    assert cold.isNull() and cold_again.isNull()
    assert resolved == [2]
    assert not warm.isNull() and warm.width() == 8
    assert provider._pending == set()  # the task completed, nothing stuck


def test_await_reports_a_timeout_instead_of_pinning_the_reader(qapp, monkeypatch):
    class SlowStore:
        async def original_file_path(self, image_id):
            await asyncio.sleep(1.0)
            return None

    async def scenario():
        import app.presentation.qml.sheet_image_provider as sip

        monkeypatch.setattr(sip, "_RESOLVE_TIMEOUT_S", 0.05)
        provider = SheetImageProvider()
        provider.bind_store(SlowStore())
        return await asyncio.to_thread(provider.requestImage, "7", QSize(), QSize())

    image = asyncio.run(scenario())
    assert image.isNull()  # worker gave up past the bound, never hung


def test_await_reports_store_failures_from_the_worker(qapp):
    class BoomAsyncStore:
        async def original_file_path(self, image_id):
            raise ValueError("row gone")

    async def scenario():
        provider = SheetImageProvider()
        provider.bind_store(BoomAsyncStore())
        return await asyncio.to_thread(provider.requestImage, "7", QSize(), QSize())

    image = asyncio.run(scenario())
    assert image.isNull()


def test_resolution_without_any_loop_runs_in_place_anyway(qapp, png_path):
    # bind from a bare thread: nothing to capture, so the awaitable is run
    # right there — and a coroutine that still fails must come back null,
    # not raise into Qt's reader.
    import threading

    outcomes: dict[str, object] = {}

    class BadStore:
        async def original_file_path(self, image_id):
            raise RuntimeError("no loop and no row")

    def work():
        provider = SheetImageProvider()
        provider.bind_store(FakeStore({8: png_path}))
        outcomes["good"] = provider.requestImage("8", QSize(), QSize())
        provider.bind_store(BadStore())
        outcomes["bad"] = provider.requestImage("8", QSize(), QSize())

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert not outcomes["good"].isNull()
    assert outcomes["bad"].isNull()


def test_discard_swallows_close_failures_of_unrun_coroutines(qapp):
    class BadAwaitable:
        def close(self):
            raise RuntimeError("cannot close")

    SheetImageProvider._discard(BadAwaitable())  # must not raise
    SheetImageProvider._discard(None)            # non-awaitable: silently kept


def test_scaled_returns_the_source_when_sizes_already_match(qapp, png_path):
    provider = SheetImageProvider()
    provider.bind_store(FakeStore({3: png_path}))
    image = provider.requestImage("3", QSize(), QSize(8, 8))  # natural size
    assert not image.isNull()
    assert image.width() == 8 and image.height() == 8


def test_hub_prefetch_failures_and_misses_stay_quiet(qapp):
    # A prefetch that blows up or finds no row must not emit (no delegate
    # reload-loop on a dead id) and must not pin the pending set.
    hub = SheetImageHub()
    resolved: list[int] = []
    hub.resolved.connect(resolved.append)

    class BoomAsyncStore:
        async def original_file_path(self, image_id):
            raise ValueError("row gone")

    async def scenario():
        empty = SheetImageProvider(hub=hub)
        empty.bind_store(FakeStore({}))
        miss = empty.requestImage("5", QSize(), QSize())
        boom = SheetImageProvider(hub=hub)
        boom.bind_store(BoomAsyncStore())
        bad = boom.requestImage("6", QSize(), QSize())
        for _ in range(100):
            await asyncio.sleep(0)
        return miss, bad, empty, boom

    miss, bad, empty, boom = asyncio.run(scenario())
    assert miss.isNull() and bad.isNull()
    assert resolved == []
    assert empty._pending == set() and boom._pending == set()
