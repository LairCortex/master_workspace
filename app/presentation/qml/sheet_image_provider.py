"""``image://sheet/<imageId>`` — the sheet canvas reads images from ImageStore.

Part of the character-sheet QML island's python side (change Q3b 1.3, design
D7): the widgets canvas had a manual QPixmap cache pumped by async tasks; the
QML ``Image`` element is asynchronous by itself, so all the island needs is an
id → bytes resolver, registered once per engine as a ``QQuickImageProvider``
under the ``sheet`` identifier.

Resolution rules:

* the store is the *current game's* ``ImageStore`` — bound by whoever builds
  the sheet surface (the facade dialogs receive it via DI) through
  :func:`bind_sheet_image_store`; re-binding drops the path cache, so a game
  switch can never serve the previous game's bytes;
* ``ImageStore.original_file_path`` is a coroutine (the id → sha mapping is a
  DB row). When a request arrives on a pixmap-reader *worker* thread, blocking
  is safe: the coroutine is handed to the captured application loop with
  ``run_coroutine_threadsafe`` and awaited with a bounded timeout. But a
  ``QQuickWidget`` has no render thread, so in practice Qt asks synchronously
  **on the GUI thread — the very thread running the application loop** (Q3b
  fact pinned by the migrated fill-dialog test). Blocking there would hang
  the loop that must run the coroutine, so a cache-miss request on the loop
  thread instead *schedules the lookup as a task on that loop* and answers a
  null image this round; when the task resolves, the hub (:class:`SheetImageHub`,
  context property ``sheetImages``) emits ``resolved(imageId)`` and the canvas
  delegate reloads the same id (warm cache, instant hit) — the QML way of
  loading asynchronously on a surface without a render thread;
* a provider used *without* the hub (a bare unit-test instance) keeps the old
  rule: a request on the loop thread is refused as a null image rather than
  deadlocking the app;
* the id is the single piece of data that reaches the storage layer; anything
  unknown (malformed id, missing row, deleted file) resolves to a null image
  — zero size, logged, never a crash (the same best-effort semantics the
  widgets canvas used).

Lifetime rule (learned the hard way by the Q3b test suite): the engine takes
ownership of a registered provider and deletes it with itself, and the
shiboken wrapper of a non-QObject is not reliably invalidated by that deletion
— so python keeps NO reference to a registered provider. Every registration
installs a fresh instance; the only state kept here is the last bound store,
re-applied to each new provider.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtQuick import QQuickImageProvider

log = logging.getLogger(__name__)

# The provider always registers under this id: the canvas delegates write
# ``image://sheet/<imageId>`` (Q3b D7).
SHEET_IMAGE_PROVIDER_ID: str = "sheet"

# Engine-wide context name the delegates use to observe resolved prefetches
# (the retry channel described in the module docstring).
SHEET_IMAGE_HUB_NAME: str = "sheetImages"

# A live DB round trip is milliseconds; anything past this is a stalled store
# and must not pin the pixmap reader forever.
_RESOLVE_TIMEOUT_S: float = 5.0


class SheetImageHub(QObject):
    """The delegates' retry channel: ``resolved(imageId)`` after a prefetch.

    A ``QQuickWidget`` loads images on the GUI thread — the same thread that
    runs the application loop — so a cold ``image://sheet`` request cannot
    wait for the store coroutine and answers null (the Q3b fact in the module
    docstring). The provider schedules the lookup as a loop task instead and
    a delegate that sees ``resolved`` for its own id re-requests the same
    source; the second request hits the warm cache synchronously. The hub is
    the QObject the island listens to (context property ``sheetImages``), the
    one object python may emit into a QML Connections from.

    Stateless by design: the cache, the loop capture and the pending set all
    live on the engine's provider; the hub only forwards signals.
    """

    resolved = Signal(int)


class SheetImageProvider(QQuickImageProvider):
    """Id → original-bytes provider over the bound ``ImageStore``.

    The instance is engine-owned (see the module docstring's lifetime rule);
    all state here — the cached resolved paths and the loop/thread capture —
    is therefore per-engine and dies with it. ``hub`` (the facade flow)
    enables the schedule-and-retry path for loop-thread requests; the bare
    unit-test provider without a hub keeps refusing them (never blocking the
    app loop).
    """

    def __init__(self, hub: SheetImageHub | None = None) -> None:
        super().__init__(QQuickImageProvider.ImageType.Pixmap)
        self._hub = hub
        self._store = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._paths: dict[int, Path] = {}
        self._pending: set[int] = set()

    # -- binding --------------------------------------------------------------

    def bind_store(self, store) -> None:
        """Point the provider at the current game's ImageStore (or ``None``).

        Called from a context where the application's event loop is the
        process loop (the qasync loop set by ``main()``); the loop and its
        thread are captured now, because resolving *from* QML's worker thread
        later must have no loop to look at. Passing ``None`` detaches (game
        closed); every (re)bind drops the path cache.
        """
        self._paths.clear()
        self._pending.clear()
        self._store = store
        loop: asyncio.AbstractEventLoop | None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop_policy().get_event_loop()
            except RuntimeError:  # non-main thread without a configured loop
                loop = None
        self._loop = loop
        self._loop_thread_id = threading.get_ident()

    # -- QQuickImageProvider contract ------------------------------------------

    def requestPixmap(self, image_id: str, size, requested_size):  # Qt API name
        """Qt 6's entry point for Pixmap-type providers.

        Since Qt 6 the sync path calls ``requestPixmap`` and does *not* fall
        back to ``requestImage`` (the reader warns about the missing override
        and hands QML a null reply). The sheet flow — QQuickWidget, no render
        thread — is that sync path, so this override is where the GUI-thread
        requests actually arrive; it delegates to ``requestImage`` and keeps
        one resolution pipeline.
        """
        image = self.requestImage(image_id, size, requested_size)
        if image.isNull():
            return QPixmap()
        return QPixmap.fromImage(image)

    def requestImage(self, image_id: str, size, requested_size):  # Qt API name
        """Resolve ``<imageId>`` → the original image, or a null QImage.

        ``size`` is filled by Qt with the image's natural size when the id
        resolves; a null image means "no such image" and leaves the QML
        ``Image`` in its error state at zero size — the required degradation
        for missing rows/files.
        """
        path = self._resolve(image_id)
        if path is None:
            return QImage()
        image = QImage(str(path))
        if image.isNull():
            log.debug("sheet image %s unreadable at %s", image_id, path)
            return QImage()
        return self._scaled(image, requested_size)

    # -- resolution -------------------------------------------------------------

    def _resolve(self, image_id: str) -> Path | None:
        store = self._store
        if store is None:
            return None
        number = self._parse_id(image_id)
        if number is None:
            log.debug("sheet image id is not numeric: %r", image_id)
            return None
        cached = self._paths.get(number)
        if cached is not None:
            if cached.is_file():
                return cached
            # GC removed the file since the cache entry (or the row was
            # dropped): treat as missing and stop trusting the entry.
            del self._paths[number]
        if (
            self._hub is not None
            and self._loop is not None
            and self._loop.is_running()
            and threading.get_ident() == self._loop_thread_id
        ):
            # A QQuickWidget request on the loop thread: waiting on the DB
            # would hang the very loop that must run the lookup. Schedule it
            # and answer null this round; the ``resolved`` signal re-asks the
            # delegate with the path warm (module docstring).
            self._schedule_prefetch(number)
            return None
        try:
            value = store.original_file_path(number)
        except Exception:  # a store that throws synchronously must not kill QML
            log.warning("sheet image %s lookup failed", number, exc_info=True)
            return None
        if inspect.isawaitable(value):
            value = self._await(value)
        if value is None:
            return None
        path = Path(str(value))
        if not path.is_file():
            log.debug("sheet image %s has no file at %s", number, path)
            return None
        self._paths[number] = path
        return path

    def _schedule_prefetch(self, number: int) -> None:
        """Run the store lookup as a task on the captured loop (hub flow).

        The request itself answered null this round (module docstring); when
        the task warms ``self._paths`` it emits ``hub.resolved(number)`` and
        the delegate re-requests the same id for a synchronous cache hit.
        A failure just logs — no signal, so the delegate never reload-loops;
        the ``_pending`` set collapses the repeated null-answering requests
        of the same id into one task.
        """
        if number in self._pending:
            return
        self._pending.add(number)
        store = self._store

        async def _lookup() -> None:
            try:
                value = store.original_file_path(number)
                if inspect.isawaitable(value):
                    value = await value
                if value is not None:
                    path = Path(str(value))
                    if path.is_file():
                        self._paths[number] = path
                        self._hub.resolved.emit(number)
            except Exception:
                log.warning(
                    "sheet image prefetch %s failed", number, exc_info=True
                )
            finally:
                self._pending.discard(number)

        asyncio.ensure_future(_lookup(), loop=self._loop)

    def _await(self, awaitable):
        """Bridge ``store.original_file_path`` to this (worker) thread."""
        loop = self._loop
        if loop is not None and loop.is_running():
            if threading.get_ident() == self._loop_thread_id:
                # Blocking here would hang the event loop that must run the
                # very coroutine we wait for (qasync: Qt *is* the loop).
                log.warning(
                    "sheet image request on the loop thread refused; "
                    "image://sheet ids must be loaded asynchronously"
                )
                self._discard(awaitable)
                return None
            future = asyncio.run_coroutine_threadsafe(awaitable, loop)
            try:
                return future.result(_RESOLVE_TIMEOUT_S)
            except asyncio.TimeoutError:
                future.cancel()
                log.warning("sheet image lookup timed out past %.0f s", _RESOLVE_TIMEOUT_S)
                return None
            except Exception:
                log.warning("sheet image lookup failed", exc_info=True)
                return None
        # No live loop was captured (plain unit test / no running app): the
        # awaitable is fake or trivially self-contained — run it right here,
        # on whatever thread QML's reader happens to use. Returns None on any
        # failure (including "already running" oddities), never raising.
        try:
            return asyncio.run(_close_through(awaitable))
        except Exception:
            log.warning("sheet image lookup outside a running loop failed", exc_info=True)
            self._discard(awaitable)
            return None

    @staticmethod
    def _discard(awaitable) -> None:
        """Close a coroutine we ended up not running (no warnings leak)."""
        close = getattr(awaitable, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass

    @staticmethod
    def _parse_id(image_id: str) -> int | None:
        raw = image_id.split("?", 1)[0].split("#", 1)[0].strip("/")
        try:
            return int(raw)
        except ValueError:
            return None

    @staticmethod
    def _scaled(image: QImage, requested_size):
        width = requested_size.width()
        height = requested_size.height()
        if width <= 0 and height <= 0:
            return image
        if 0 < width and 0 < height and image.size() == requested_size:
            return image
        return image.scaled(
            width if width > 0 else -1,
            height if height > 0 else -1,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


async def _close_through(awaitable):
    """``asyncio.run`` target: await the store coroutine (plain awaitable)."""
    return await awaitable


# The last bound store (the current game's ImageStore, or None before a game
# is opened / after it closes). The only provider-related state python keeps:
# registered providers are engine-owned and must not be referenced here —
# see the module docstring's lifetime rule.
_pending_store = None


def sheet_image_provider():
    """The provider registered on the live engine (or ``None``).

    The engine's own registry is the only holder; through it QML and the
    facade dialogs (and tests) can bind a store or trigger a resolution.
    """
    from app.presentation.qml.engine import qml_engine  # late: engine imports us

    engine = qml_engine()
    if engine is None:
        return None
    return engine.imageProvider(SHEET_IMAGE_PROVIDER_ID)


def bind_sheet_image_store(store) -> None:
    """Bind the current game's ImageStore for ``image://sheet`` (or ``None``).

    Applied to the live engine's provider immediately and remembered as the
    store for every provider registered later (the game is opened before any
    sheet surface is built; engine resets happen in tests only).
    """
    global _pending_store
    _pending_store = store
    provider = sheet_image_provider()
    if provider is not None:
        provider.bind_store(store)


def register_sheet_image_provider(engine) -> None:
    """Register ``image://sheet`` on the engine — idempotent per engine.

    A brand-new instance is installed each time (never a previously
    registered one): the engine owns and deletes the provider with itself.
    The last bound store is applied before the hand-off.

    The registration also builds the delegate retry channel of the hub flow
    (module docstring): a fresh ``SheetImageHub`` parented to the engine —
    the QML delegates watch it under the context name ``sheetImages``, the
    provider gets the very same hub, so a loop-thread cold request scheduled
    as a prefetch emits ``resolved`` exactly on the engine whose delegates
    are listening (and both die together with the engine).
    """
    if engine.imageProvider(SHEET_IMAGE_PROVIDER_ID) is not None:
        return
    hub = SheetImageHub(engine)  # dies with the engine, like the provider
    engine.rootContext().setContextProperty(SHEET_IMAGE_HUB_NAME, hub)
    provider = SheetImageProvider(hub)
    provider.bind_store(_pending_store)
    engine.addImageProvider(SHEET_IMAGE_PROVIDER_ID, provider)
