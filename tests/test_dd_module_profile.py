"""The «profile without the module» switch (add-dnd-module-foundation, task 1.4;
design Д11: acceptance/emergency profile — ``NRI_DISABLE_DD_MODULE=1``).

The switch is read by the composition point before ``app/dd`` is ever touched:
in this profile the package must not reach ``sys.modules`` at all — the proof
is the sys.modules scan after a full ``Application.start`` with every
``app.dd`` entry purged from the module cache beforehand (monkeypatch restores
the cache on teardown). A regular game opens silently; a D&D fixture opens as
ordinary with the one deferred warning, and its flag row stays byte-identical
— the profile hides the module, it never edits the game.

The control test (module present without the switch) runs LAST in file order:
it is what puts ``app.dd`` into the cache, and it proves the silence above is
the switch, not an unavailable import.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys

import pytest
from PySide6.QtWidgets import QDialog

from app.infrastructure.repositories.game_settings_repository import DND_MODULE_KEY
from app.main import (
    DD_MODULE_PROFILE_DISABLE_ENV,
    DD_MODULE_PROFILE_WARNING,
    DD_MODULE_UNAVAILABLE_TITLE,
    Application,
)
from app.presentation.modules.protocol import NoopGameSystemModule
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from tests.test_application_settings_errors import _install_modal_trap


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """Freshly seeded games open the first-entry wizard inside ``start()``;
    offscreen must not block on a real modal loop (local copy of the
    settings-errors convention)."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


@pytest.fixture
def profile_without_module(monkeypatch):
    """The acceptance/emergency profile for this test."""
    monkeypatch.setenv(DD_MODULE_PROFILE_DISABLE_ENV, "1")


@pytest.fixture
def module_cache_purged(monkeypatch):
    """Drop every ``app.dd`` entry from the import cache (restored on
    teardown): a fresh import inside the test therefore reappears in
    ``sys.modules`` only if the composition actually imported the package.

    Since add-dnd-game-face task 8.1 the purge must also retire the tables
    a previous import declared on the kernel ``Base``: design Д6 puts the
    module's tables on the shared metadata, and a module-cache purge alone
    leaves ``dd_character_ext`` behind on the surviving ``Base`` — the
    re-import inside the test would then re-declare a defined table (the
    declarative hard error). Removing the module tables from the metadata
    restores exactly the state the purge promises: for the duration of the
    test it is as if ``app.dd`` had never been imported.

    Teardown restores BOTH halves of the import cache, not just
    ``sys.modules``: a re-import during the test also rebinds the fresh
    module onto its PARENT package's attribute, and the two readers of the
    cache diverge — a production ``from app.dd... import`` resolves through
    ``sys.modules``, while pytest's dotted-name patch targets
    (``monkeypatch.setattr("app.dd...Class.method", …)`` in the lifecycle
    tests) walk the parent attributes via ``_pytest.monkeypatch.resolve``.
    Restoring only ``sys.modules`` left the two copies pointing at
    different module objects, so a later test patched a class nobody
    imports (observed in the combined single-process run as a silently
    UNpatched real ``enable`` answering the write-failure probe). Hence the
    purge also detaches each cached child from its parent with
    ``monkeypatch.delattr`` — and the metadata gets the symmetric care:
    a table the test re-declared stays, one nobody re-imported returns to
    the ``Base`` it was removed from."""
    for name in list(sys.modules):
        if name != "app.dd" and not name.startswith("app.dd."):
            continue
        monkeypatch.delitem(sys.modules, name, raising=False)
        parent_name, _, child = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None:
            monkeypatch.delattr(parent, child, raising=False)
    from app.infrastructure.db.models import Base

    removed = {
        name: table
        for name, table in list(Base.metadata.tables.items())
        if name.startswith("dd_")
    }
    for table in removed.values():
        Base.metadata.remove(table)
    yield
    # Anything the test (re)imported leaves no trace either: an entry that
    # was absent at setup stays absent, so the cache below is exactly what
    # the recorded monkeypatch undos now republish (parent attributes and
    # all). A leftover fresh child under a restored parent would desync
    # ``sys.modules`` from the attribute chain in the OTHER direction —
    # ``_pytest.monkeypatch.resolve`` would then fail with
    # ``module 'app.dd' has no attribute 'module'`` for later dotted
    # patch targets in subsequent files.
    for name in list(sys.modules):
        if name == "app.dd" or name.startswith("app.dd."):
            del sys.modules[name]
    for name, table in removed.items():
        if name not in Base.metadata.tables:
            # The symmetric half of ``MetaData.remove`` (the registry
            # exposes no public re-add); a test that re-imported the
            # module already re-declared its tables and those stay.
            Base.metadata._add_table(name, None, table)


def _dd_entries() -> list[str]:
    return [
        name
        for name in sys.modules
        if name == "app.dd" or name.startswith("app.dd.")
    ]


def _make_dd_db(tmp_path, flag_value: str | None):
    db_path = tmp_path / "game" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE game_settings "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
        )
        if flag_value is not None:
            conn.execute(
                "INSERT INTO game_settings (key, value) VALUES (?, ?)",
                (DND_MODULE_KEY, flag_value),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _read_dnd_row(db_path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT value FROM game_settings WHERE key = ?", (DND_MODULE_KEY,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


async def test_profile_regular_game_opens_silently_without_the_package(
    qapp, tmp_path, monkeypatch, profile_without_module, module_cache_purged
):
    """Обычная игра в профиле без модуля: штатный состав, тишина, ``app.dd``
    не импортирован."""
    db_path = _make_dd_db(tmp_path, None)
    boxes = _install_modal_trap(monkeypatch)
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        await asyncio.sleep(0)
        assert boxes == []
        assert application._dd_unavailable_box is None
        assert _dd_entries() == []
    finally:
        window.close()
        await application.shutdown()
    assert _dd_entries() == []


async def test_profile_dnd_game_opens_ordinary_with_warning_data_intact(
    qapp, tmp_path, monkeypatch, profile_without_module, module_cache_purged
):
    """D&D-фикстура в профиле без модуля: игра открыта как обычная с одним
    отложенным предупреждением; признак байт-в-байт не тронут; пакет не
    импортирован."""
    fixture = json.dumps({"enabled": True, "version": 1})
    db_path = _make_dd_db(tmp_path, fixture)
    boxes = _install_modal_trap(monkeypatch)
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        # nothing modal on the startup contour…
        assert boxes == []
        # …the one warning lands deferred, naming the profile, in Russian
        await asyncio.sleep(0)
        assert len(boxes) == 1
        box = boxes[0]
        assert box.parent is window
        assert box.shown_via == "show"
        assert box.title == DD_MODULE_UNAVAILABLE_TITLE
        assert box.text == DD_MODULE_PROFILE_WARNING
        # the game's module data is hidden, never edited
        assert _read_dnd_row(db_path) == fixture
        assert _dd_entries() == []
    finally:
        window.close()
        await application.shutdown()
    assert _read_dnd_row(db_path) == fixture


async def test_control_without_the_switch_the_module_is_composed(
    qapp, tmp_path, monkeypatch, module_cache_purged
):
    """Контроль порядка и зубов предыдущих тестов: без переключателя та же
    фикстура собирает модуль — молчаливость профиля даёт именно он. Сам тест
    ``app.dd`` не импортирует: попадание пакета в кэш — заслуга композиции.
    Переключатель гасится явно (как autouse-обычай композиционного файла):
    тест пинит ветку «без переключателя», значит владеет его значением —
    иначе приёмочный прогон профиля «ядро» (env поднят на весь процесс,
    задача 6.4) читал бы этот контроль красным."""
    monkeypatch.delenv(DD_MODULE_PROFILE_DISABLE_ENV, raising=False)
    db_path = _make_dd_db(tmp_path, json.dumps({"enabled": True, "version": 1}))
    boxes = _install_modal_trap(monkeypatch)
    assert _dd_entries() == []  # purged cache, this test imports nothing of it
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        module = application._game_system_module
        assert type(module).__name__ == "DndModule"
        assert type(module).__module__ == "app.dd.module"
        assert "app.dd.module" in sys.modules  # arrived through the composition
        await asyncio.sleep(0)
        assert boxes == []
    finally:
        window.close()
        await application.shutdown()


# ── add-dnd-game-face (task 2.2): zero external registrations in the kernel
# and in this profile — the byte-for-byte registry ─────────────────────────


async def test_profile_registers_no_external_types(qapp, tmp_path, monkeypatch,
                                                   profile_without_module,
                                                   module_cache_purged):
    """Пин задачи 2.2: в профиле без модуля состав регистрирует НОЛЬ внешних
    типов — реестр отвечает прежнему shape (union поиска = SEARCH_TYPES,
    внешний ключ нерешаем, фолбэк метки = сырой ключ), а раздача пустая;
    после shutdown — тишина в той же форме."""
    from app.domain import entity_registry as reg
    from app.domain.enums.entity_type import EntityType

    db_path = _make_dd_db(tmp_path, json.dumps({"enabled": True, "version": 1}))
    _install_modal_trap(monkeypatch)
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert application._external_sources == ()
        assert reg.external_types() == ()
        assert reg.search_types() == reg.SEARCH_TYPES
        assert reg.resolve("character") is EntityType.CHARACTER
        assert reg.resolve("spell") is None
        assert reg.display_label("spell") == "spell"
        # dd-card-redesign task 3.5 (spec entity-card-tabs «карточки без
        # модуля неотличимы от 0.19.1»): пустые источники — вся карточная
        # история этого профиля. С нулём внешних источников каждый открываемый
        # экран — одноэкранный вид 0.19.1: одна группа «Основное», полоса
        # спит, пришитой полосы связей нет — для всех ядерных типов и события.
        # Половина предпросмотра закрыта парой пинов: здесь — нуль источников
        # (секций неоткуда взять), в test_entity_preview_island — ядровая
        # карточка не печатает внешнюю секцию.
        from app.presentation.views.entity_card_dialog import EntityCardDialog
        from app.presentation.views.event_dialog import EventDialog
        from tests.presentation.qml_helpers import find_item

        screens = []
        for entity_type in sorted(t.value for t in EntityType):
            screens.append(EntityCardDialog(None, entity_type))
        screens.append(EventDialog(None))
        try:
            for dialog in screens:
                assert [e["key"] for e in dialog.vm.groups] == ["overview"]
                assert dialog.vm.moduleGroups == []
                strip_name = (
                    "eventGroupTabs"
                    if isinstance(dialog, EventDialog)
                    else "entityGroupTabs"
                )
                strip = find_item(dialog.quick, strip_name)
                assert strip.property("visible") is False
                if isinstance(dialog, EntityCardDialog):
                    band = find_item(dialog.quick, "entityRelationsBand")
                    assert band.property("active") is False
        finally:
            for dialog in screens:
                dialog.close()
                dialog.deleteLater()
    finally:
        window.close()
        await application.shutdown()
    # the section leaves with the game (composition shutdown resets it)
    assert reg.external_types() == ()
    assert application._external_sources == ()


async def test_kernel_regular_game_registers_no_external_types(
    qapp, tmp_path, monkeypatch
):
    """Тот же ноль-пин для ядра БЕЗ переключателя: обычная игра собирается со
    stub'ом, stub раздаёт пустой кортеж — внешняя секция реестра пуста и
    поверхность реестра байт-в-байт прежнее поведение."""
    monkeypatch.delenv(DD_MODULE_PROFILE_DISABLE_ENV, raising=False)
    from app.domain import entity_registry as reg

    db_path = _make_dd_db(tmp_path, None)
    _install_modal_trap(monkeypatch)
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        assert application._external_sources == ()
        assert reg.external_types() == ()
        assert reg.search_types() == reg.SEARCH_TYPES
    finally:
        window.close()
        await application.shutdown()
