# Environment ordering: QT_QUICK_BACKEND must be set here — before any QML
# surface is created (the QSG backend env var is read lazily at first render),
# so this conftest import precedes every Qt Quick usage in the suite.
# Decision (task 1.2, spec qml-shell «Тестирование QML-поверхностей»): the
# software backend renders QQuickWidget under QT_QPA_PLATFORM=offscreen and
# grab() yields the expected pixel locally (macOS, PySide6 6.10.2 — see
# tests/test_qml_render_smoke.py), so pixel acceptance keeps grab()+hex-token
# convention; the spec's fallback (status/property checks without grab()) is
# NOT enabled — if some CI OS fails to render, apply it there only (task 9.1).
import os

os.environ["QT_QUICK_BACKEND"] = "software"
# Grab acceptance must be DPR=1 on Retina hosts and in CI (spec ui-testing
# «Пиксельная приёмка при зафиксированном коэффициенте пикселей»). Qt reads
# these at QApplication start; setdefault so an explicit QT_SCALE_FACTOR=2
# still reaches the guard test. Existing _grab_scaled idioms stay as backup.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_SCREEN_SCALE_FACTORS", "1")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.infrastructure.db.database import create_engine as app_create_engine
from app.infrastructure.db.models import Base


@pytest.fixture(scope="session", autouse=True)
def russian_localization_from_startup(qapp):
    """Every test starts in the same state as the launched app: the Russian
    translator already on (NRI-0014, spec interface-language).

    ``main()`` installs it right after creating the QApplication and before
    the first window; the suite cannot run ``main()`` (pragma: no cover), so
    this session fixture — the first thing touching the session app — applies
    the same single installer. Standard buttons («Отмена», «Да», «Нет», «ОК»)
    and file panels then read Russian in tests exactly like at runtime, and
    texts pinning tests can rely on the post-startup contract.
    """
    from app.infrastructure.localization import install_russian_localization

    return install_russian_localization(qapp)


@pytest.fixture(autouse=True)
def isolated_ui_theme_defaults(tmp_path, monkeypatch):
    """No test may read or write the developer's real ~/.nri_manager/ui.json.

    The process-wide theme runtime is a singleton (Application default, table
    host); resetting it per test also keeps chrome widgets registered by one
    test from being recolored by the next one.
    """
    from app.infrastructure.ui_prefs import config as ui_prefs_config
    from app.presentation import theme as theme_package

    monkeypatch.setattr(ui_prefs_config, "CONFIG_FILE", tmp_path / "ui.json")
    theme_package.reset_default_theme()
    yield
    theme_package.reset_default_theme()


@pytest.fixture(autouse=True)
def isolated_qml_shell():
    """Per-test QML isolation retired in PR-033: the engine lives for the session.

    The engine used to die and be rebuilt after every test. That churn is a
    lifecycle the application NEVER exercises (spec qml-shell: one engine per
    application) and it became the PR-033 crash class: repeatedly destroying
    ``QQmlEngine`` in one process lets the Qt6 type-loader/compiled-data
    caches and the dead engine's QV4 GC detonate inside the NEXT engine's
    widget construction (exit 139 under ``Sbk_QWidget_Init``/
    ``SignalManager::retrieveMetaObject``; the signature vanished for the
    preview family the moment the per-test rebuild stopped — measured 6/6 →
    0/6 for ``test_entity_preview_island.py`` alone). The islands' own
    hygiene — windows closed and deferred work drained per test — is done by
    ``drain_deferred_island_teardown`` below; the engine teardown moves to
    the session end (``qml_shell_lives_for_the_session``).

    The engine-root ``palette`` therefore tracks the first test's theme
    runtime; every island binds its own ``islandPalette`` from the CURRENT
    default theme at construction, which is what the token assertions read
    (pinned green across all of ``tests/presentation`` with this posture).
    """
    yield


@pytest.fixture(scope="session", autouse=True)
def qml_shell_lives_for_the_session(qapp):
    """Tear the session engine down at the session's end, not at interpreter exit.

    With a session-lived engine still parented to the QApplication when
    CPython finalizes, PySide's atexit destroys it under ``Py_FinalizeEx``
    while the GIL is held, and the engine's destructor joins its
    ``QQuickPixmapReader`` thread — which by then calls back into the Python
    image providers the shell registers; the join never completes (sampled:
    main thread wedged in ``QThread::wait`` under ``destroyQCoreApplication``).
    Resetting HERE — GIL normal, event loop alive — ends the reader normally
    and leaves PySide's atexit nothing to destroy. Requesting ``qapp`` keeps
    this fixture inside the application's lifetime.
    """
    yield
    from app.presentation.qml.engine import reset_qml_shell

    reset_qml_shell()


@pytest.fixture(autouse=True)
def no_stale_windows():
    """Hide any top-level widget a test leaves visible at teardown.

    Offscreen routing detail this guards: a window still on screen from a
    previous test (e.g. a game-switch flow where the app swaps MainWindows
    and teardown closes only the fixture's one) keeps owning the process's
    window-level pointer routing — spontaneous mouse moves then never deliver
    hover to the bare QQuickWidget islands the timeline tests build. Qt does
    not dispose windows Python forgot about; hide every leak here, so the
    next test starts from a clean top-level list.
    """
    yield
    from PySide6.QtWidgets import QApplication

    app_instance = QApplication.instance()
    if app_instance is None:
        return
    for widget in list(app_instance.topLevelWidgets()):
        try:
            if widget.isVisible():
                widget.hide()
        except RuntimeError:
            pass  # C++ side already gone


@pytest.fixture(autouse=True)
def drain_deferred_island_teardown():
    """Run every island's deferred release inside the test that scheduled it.

    NRI-0021 flake fix (task 7.2). The island lifecycle defers its scene
    release by one loop turn (``QTimer.singleShot(0, …)`` in
    ``IslandDialogMixin``), and ``pytest-qt`` closes registered widgets only
    AFTER the function fixtures have finalized (its ``pytest_runtest_teardown``
    hookwrapper runs after every finalizer) — so without this drain the
    release timer and the ``deleteLater``/``DeferredDelete`` events of a
    window closed at test end survive into the NEXT test's event pump
    (``pytestqt`` ``pytest_runtest_setup`` → ``_process_events``), where they
    fire against islands whose engine ``reset_qml_shell`` has already dropped.
    That is where the SEGFAULTs of the NRI-0021 test runs died: faulthandler
    stacks in ``_process_events`` during setup, malloc reports of
    ``QObjectPrivate::deleteChildren`` freeing stale pointers during a
    deferred ``QDialog`` delete (the crash class already registered as a
    live-audit follow-up in NRI-0019, `Python-2026-09-26-121657.ips`).

    Closing the still-visible windows here and pumping the queue runs each
    window's own production exit path (close → one-shot release → palette
    detach → ``setSource(QUrl())``) while its engine is still alive, so
    nothing deferred can outlive the test that scheduled it. This fixture is
    defined last among the autouse ones so it finalizes first — before
    ``no_stale_windows`` turns visible windows into hidden ones; the later
    ``hide``/``close`` calls on now-closed windows are no-ops. (PR-033: the
    queue pytest-qt posts afterwards — ``close`` + ``deleteLater`` in its own
    teardown wrapper — is drained by the outer ``pytest_runtest_teardown``
    hook at the end of this file.)
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app_instance = QApplication.instance()
    if app_instance is None:
        return
    for widget in list(app_instance.topLevelWidgets()):
        try:
            if widget.isVisible():
                widget.close()
        except RuntimeError:
            pass  # C++ side already gone
    # Fire the one-shot island releases, then the deferred deletes they post.
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest_asyncio.fixture
async def async_engine():
    # App's create_engine registers a unicode-aware SQLite lower() —
    # fixtures must match runtime behavior for case-insensitive search.
    engine = app_create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine):
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def uow(async_session):
    """GameSessionUoW over the test session (wave 5, design D4).

    Built with a fresh ``asyncio.Lock`` — tests exercising real serialization
    supply their own; this one just satisfies the unit's signature.
    """
    from app.infrastructure.db.uow import GameSessionUoW

    return GameSessionUoW(async_session, asyncio.Lock())


@pytest.fixture(autouse=True)
def unbind_sheet_image_store_at_boundary():
    """The session engine's image provider never outlives a test holding a store.

    The provider caches the bound ``ImageStore`` plus the asyncio loop and
    thread captured at bind time — correct for production (one qasync loop,
    one store per game), a dangling pair for tests, which swap both every
    test. With the session engine (PR-033) the provider outlives the test, so
    a late prefetch (pixmap retry through the hub, a leftover visible island)
    could schedule a coroutine of a disposed store onto a closed loop. The
    public bind helper detaches the store, drops the path cache and forgets
    the remembered store for later registrations; dialog facades re-bind at
    their own construction.
    """
    from app.presentation.qml.sheet_image_provider import bind_sheet_image_store

    bind_sheet_image_store(None)
    yield
    bind_sheet_image_store(None)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item):
    """Finish every window death pytest-qt schedules, inside this test (PR-033).

    ``QtBot._close_widgets`` runs after every fixture (its teardown wrapper
    is ``trylast``) and only ``deleteLater``-s its widgets; without this
    outer drain the queue survives into the NEXT test and the island
    destructions land mid-construction — one detonation site of the PR-033
    crashes. A plain new-style wrapper sits outside pytest-qt's hook, so the
    code after the ``yield`` runs once pytest-qt has scheduled its deletes:
    the pump executes them at a quiet moment with the session engine alive,
    before any later island can meet the churn mid-construction.
    """
    result = yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is not None:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        # the destructions release their islands one loop turn later
        # (``IslandDialogMixin`` schedules it) — let the one-shots fire too.
        QCoreApplication.processEvents()
    # NOTE (PR-033): the jail is deliberately NOT released here — see the
    # fixture docstring; the wrappers outlive every C++ churn of the test.
    if getattr(item, "_pr033_shell_reset_pending", False):
        # a fixture swapped the session engine onto its own runtime; drop it
        # only now — after QtBot closed its windows (closing island windows
        # against an already-dead engine raised through QtBot's teardown).
        from app.presentation.qml.engine import reset_qml_shell

        reset_qml_shell()
    return result


@pytest.fixture(autouse=True)
def no_nested_qeventloop(qtbot):
    """``qtbot.wait``/``waitUntil`` must not spin a nested QEventLoop (PR-033).

    Timers, deferred deletes and QML pulses fired by a nested loop re-enter
    half-torn-down Python scenes; under pytest-asyncio the nesting sits in a
    greenlet over an asyncio loop the test already stopped. One contributing
    layer of the PR-033 posture (measured: not sufficient alone — the
    wrapper-lifetime boundary hygiene below carries the rest). The calls in
    this suite never wait on signals, only pump frames, which is exactly what
    ``QTest.qWait`` does without recursion; timeout and ``TimeoutError``
    semantics stay identical.
    """
    from PySide6.QtTest import QTest

    def _wait(ms: int = 1000, **_kwargs) -> None:
        QTest.qWait(ms)

    def _wait_until(predicate, timeout: int = 1000, wait_for: int = 50, **_kwargs):
        elapsed = 0
        while not predicate():
            if elapsed >= timeout:
                raise qtbot.TimeoutError(f"qWait patch: timed out after {timeout} ms")
            QTest.qWait(wait_for)
            elapsed += wait_for

    original_wait, original_wait_until = qtbot.wait, qtbot.waitUntil
    qtbot.wait, qtbot.waitUntil = _wait, _wait_until
    yield
    qtbot.wait, qtbot.waitUntil = original_wait, original_wait_until


_qt_wrapper_jail: list = []


@pytest.fixture(autouse=True)
def boundary_qml_garbage_and_wrapper_jail():
    """One boundary hygiene bundle for the Qt wrapper lifetime (PR-033).

    Two halves, one mechanism — the session engine outlives the Python side
    of the objects its scenes bind:

    * ``collectGarbage`` after every test detaches QV4 wrappers while the
      test's Python objects are still alive; left to itself the QV4 GC runs
      at the next allocation burst — mid the NEXT island's construction, the
      measured crash site (``QV4::QObjectWrapper::getProperty`` reading a
      freed ``PyObject`` — EXC_BAD_ACCESS caught attaching a debugger to a
      live run).
    * the jail keeps each island facade's Python wrapper — and through it
      its VM/palette attributes — alive from ``setup_island`` for the rest
      of the process. Production holds every window's Python reference as
      long as anything can still reach it; tests used to drop it at fixture
      end while ``deleteLater``/one-shot releases and QML lookups were still
      in flight. A wrapper that outlives its deleted C++ object is safe (an
      invalidated wrapper raises, never crashes); the reverse is the crash.
      The list grows by one entry per island — megabytes per module, and
      under the per-file runner one process is one module anyway.
    """
    from app.presentation.qml import island as island_module
    from app.presentation.qml.engine import qml_engine

    original_setup = island_module.IslandDialogMixin.setup_island

    def _jailed_setup(self) -> None:
        original_setup(self)
        _qt_wrapper_jail.append(self)

    island_module.IslandDialogMixin.setup_island = _jailed_setup
    yield
    island_module.IslandDialogMixin.setup_island = original_setup
    engine = qml_engine()
    if engine is not None:
        engine.collectGarbage()


@pytest.fixture(autouse=True)
def jail_qtbot_widget_wrappers(qtbot):
    """Hold every ``qtbot.addWidget`` wrapper past QtBot's own teardown (PR-033).

    QtBot closes and releases its widget list in its finalizer — the Python
    wrappers of already ``deleteLater``-pending C++ objects die at that
    moment, and PySide's wrapper-deallocation over a deleted C++ object is
    itself one of the PR-033 corruption paths (the island-panel widget
    families crash exactly like the QML islands: the calendar-grid detonation
    in ``test_r4_panel_lifecycle`` ran after such panels were closed and
    released mid-test). Requesting ``qtbot`` makes this fixture tear down
    BEFORE QtBot's own finalizer, so each registered wrapper lands in the
    jail while still valid; the process-end release is then harmless (the
    objects stay referenced until exit, where Qt's own shutdown owns them).
    """
    yield
    _qt_wrapper_jail.extend(getattr(qtbot, "_widgets", []))


@pytest.fixture(scope="session", autouse=True)
def forgiving_qtbot_widget_close():
    """Let QtBot's widget sweep skip what the test (or the jail) outlived (PR-033).

    QtBot's teardown closes every registered widget before any fixture
    finalizes. Tests that deliberately run a window's production exit inside
    the body (``sendPostedEvents(..., DeferredDelete)`` — the deferred-release
    contract of the island dialogs) leave a Python wrapper over a deleted
    C++ object; QtBot then raises ``RuntimeError ... already deleted`` from
    its sweep. Pre-jail, the wrapper happened to be garbage-collected by then
    and QtBot's weakref silently skipped the entry — the jail (which keeps
    wrappers alive to prevent the PR-033 wrapper-death corruption) turned
    that silent skip into an error. The patched sweep keeps QtBot's behavior
    — close + deleteLater + event processing — but skips invalid objects.
    """
    import contextlib

    import pytestqt.plugin as qt_plugin
    import shiboken6

    def _close_widgets(item) -> None:
        widgets = getattr(item, "qt_widgets", None)
        if not widgets:
            return
        for w, before_close_func in widgets:
            w = w()
            if w is None or not shiboken6.isValid(w):
                continue
            with contextlib.suppress(RuntimeError):
                if before_close_func is not None:
                    before_close_func(w)
                w.close()
                w.deleteLater()

    original = qt_plugin._close_widgets
    qt_plugin._close_widgets = _close_widgets
    yield
    qt_plugin._close_widgets = original
