"""Живые потоки жизненного цикла модуля (add-dnd-module-foundation, tasks
2.2/2.3/2.4/2.5; spec dnd-module-lifecycle «Включение модуля на открытой
игре», «Выключение модуля с сохранением данных», «Версия модуля и
совместимость версий приложения», «Профиль сборки без модуля» + main-window
«Метка системы и меню модуля»).

Оффскрин-контур через ``Application.start`` на опорах композиционного файла
``tests/test_dnd_module_composition.py``. Ловушка PR-010 ставится ДВАЖДЫ: на
``app.main.QMessageBox`` (подтверждение включения, error-box ядра) и на
``app.dd.module.QMessageBox`` (подтверждение выключения). Сравнение ответа
каждый поток ведёт со ``StandardButton`` СВОЕГО класса QMessageBox, а
ловушка — тот же класс для своего потока, поэтому тест эмитит «ответ»
константой той же ловушки (``_answer``).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from PySide6.QtWidgets import QDialog, QLabel, QMenu

from app.infrastructure.repositories.game_settings_repository import (
    DND_MODULE_DATA_VERSION,
    DND_MODULE_KEY,
    DndModuleFlag,
)
from app.main import (
    DD_MODULE_ENABLE_BODY,
    DD_MODULE_OFF_WARNING,
    DD_MODULE_PROFILE_DISABLE_ENV,
    DD_MODULE_PROFILE_WARNING,
    DD_MODULE_UNAVAILABLE_TITLE,
    DD_MODULE_VERSION_WARNING,
    Application,
    _compose_game_system_module,
)
from app.presentation.modules.protocol import NoopGameSystemModule
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from tests.test_application_settings_errors import _install_modal_trap


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """Как в композиционном файле: первый запуск поднимает визард календаря,
    оффскрину нужен мгновенный отказ вместо модального цикла."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


@pytest.fixture(autouse=True)
def default_profile(monkeypatch):
    monkeypatch.delenv(DD_MODULE_PROFILE_DISABLE_ENV, raising=False)


def _make_game_db(tmp_path, flag_value: str | None):
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


def _answer(box, button_name: str) -> None:
    """Эмит «ответа» сигналом finished — как настоящая кнопка своей ловушки."""
    for handler in box.finished.handlers:
        handler(getattr(box.StandardButton, button_name))


def _badge(window) -> QLabel | None:
    return window.findChild(QLabel, "ddSystemBadge")


def _module_menu(window) -> QMenu | None:
    menus = window.findChildren(QMenu, "ddModuleMenu")
    for menu in menus:
        # remove() вынимает действие из строки сразу, а сам объект QMenu
        # уничтожается только через deleteLater — строка меню пуста без него.
        # После повторного включения в дереве живут оба меню: выбираем то,
        # что сейчас висит в строке.
        if any(act.menu() is menu for act in window.menuBar().actions()):
            return menu
    return None


def _disable_action(window):
    menu = _module_menu(window)
    assert menu is not None
    # С group 5 в группе два пункта — поиск по objectName, а не по позиции.
    return next(a for a in menu.actions() if a.objectName() == "ddDisableAction")


def _datasets_action(window):
    menu = _module_menu(window)
    assert menu is not None
    return next(a for a in menu.actions() if a.objectName() == "ddDatasetsAction")


def _table_snapshot(db_path) -> dict[str, list]:
    """Снимок всех доменных таблиц игры (кроме game_settings — единственный,
    кому разрешено меняться, и dd_* — таблиц самого модуля, которые включение
    аддитивно создаёт по Д6, а не меняет): включение модуля не трогает данные
    игры. Их отдельный снимок — _dd_tables_snapshot."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name <> 'game_settings' AND substr(name, 1, 3) <> 'dd_' "
                "ORDER BY name"
            )
        ]
        return {
            name: conn.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
            for name in tables
        }
    finally:
        conn.close()


def _dd_tables_snapshot(db_path) -> tuple[list[str], dict[str, int]]:
    """Имена dd_* таблиц и число строк в каждой: включение создаёт их пустыми
    (заполнение — обязанность карточки, тесты 8.1/8.2)."""
    conn = sqlite3.connect(str(db_path))
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND substr(name, 1, 3) = 'dd_' ORDER BY name"
            )
        ]
        rows = {n: conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}
        return names, rows
    finally:
        conn.close()


# ── единицы: профиль без модуля и выключенный признак ───────────────────────


def test_profile_without_module_stays_silent_for_off_flag(monkeypatch):
    # Д11: предупреждение про скрытые данные обещает пункт «Включить…»,
    # которого в этом профиле нет; а предупреждать о недоступности игры,
    # которая ни о чём не просила, — ложь. Молчание.
    monkeypatch.setenv(DD_MODULE_PROFILE_DISABLE_ENV, "1")
    module, warning = _compose_game_system_module(
        DndModuleFlag(enabled=False, version=1)
    )
    assert type(module) is NoopGameSystemModule
    assert warning is None


def test_profile_warning_unchanged_for_enabled_flag(monkeypatch):
    monkeypatch.setenv(DD_MODULE_PROFILE_DISABLE_ENV, "1")
    module, warning = _compose_game_system_module(
        DndModuleFlag(enabled=True, version=1)
    )
    assert type(module) is NoopGameSystemModule
    assert warning == DD_MODULE_PROFILE_WARNING


# ── guards «безоконного» момента: потоки без окна/юзита безвредны ───────────


async def test_live_enable_guards_are_inert_without_a_window(qapp):
    """Между закрытием старого окна и сборкой нового (момент переключения)
    ни подтверждение, ни ответ, ни сама запись не имеют куда лечь — каждый
    вход молча выходит, ничего не создавая (прецедент: безоконный момент
    e2e-переключения)."""
    from PySide6.QtWidgets import QMessageBox

    application = Application(qapp)  # start не вызывался: окна нет
    application._on_enable_dd_module_requested()
    assert application._dd_confirm_box is None
    # даже «Да» без коннектора — без задачи
    application._on_enable_dd_module_answered(QMessageBox.StandardButton.Yes)
    assert application._dd_flow is None
    await application._enable_dd_module()  # окно/uow/wiring неты — тихо
    assert type(application._game_system_module) is NoopGameSystemModule
    application._show_dd_error("нет окна")
    assert application._dd_error_box is None
    application._dd_error_finished(0)
    assert application._dd_error_box is None


async def test_detached_module_answer_channels_are_inert():
    """façade без attach: триггер выключения не рисует окно вопросов,
    «ответ Да» без коннектора/сервиса не порождает задачу, а сам поток
    без сервиса выходит до любого обращения."""
    from PySide6.QtWidgets import QMessageBox

    from app.dd.module import DndModule

    module = DndModule()
    module._on_disable_requested()
    assert module._confirm_box is None
    module._on_disable_answered(QMessageBox.StandardButton.Yes)
    assert module._disable_task is None
    await module._disable_async()  # settings None — бездействие
    assert module.enabled is False
    # Экран датасетов без attach equally инертен: ни листа, ни ссылки.
    module._on_datasets_requested()
    assert module._datasets_sheet is None


# ── включение на открытой обычной игре (task 2.2) ────────────────────────────


async def test_enable_on_ordinary_game_writes_flag_and_attaches(
    qapp, tmp_path, monkeypatch
):
    from app.dd.module import DndModule

    db_path = _make_game_db(tmp_path, None)  # обычная игра
    main_boxes = _install_modal_trap(monkeypatch)  # app.main.QMessageBox
    _install_modal_trap(monkeypatch, "app.dd.module.QMessageBox")

    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        # снимок всех доменных таблиц до включения (task 2.2): включение НЕ
        # SHALL изменять существующие таблицы и строки игры
        before = _table_snapshot(db_path)
        assert before  # the schema really exists — the snapshot is not empty
        # ядро предложило включение: группа «Игра» с пунктом видна
        assert window.enable_dd_module_action.isVisible()
        assert _badge(window) is None

        window.enable_dd_module_action.trigger()
        assert len(main_boxes) == 1
        box = main_boxes[0]
        # «с подтверждением, объясняющим аддитивность»: состав Да|Нет,
        # кнопка по умолчанию — «Нет»
        assert box.title == DD_MODULE_UNAVAILABLE_TITLE
        assert box.text == DD_MODULE_ENABLE_BODY
        assert repr(box.buttons) == "<TrapButton Yes|No>"
        assert box.default_button is box.StandardButton.No

        # отвод (Нет): бездействие — ни задачи, ни записи, ни состава
        _answer(box, "No")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert type(application._game_system_module) is NoopGameSystemModule
        assert _read_dnd_row(db_path) is None
        assert window.enable_dd_module_action.isVisible()

        # Да: признак записан, модуль пристёгнут к живому окну
        window.enable_dd_module_action.trigger()
        _answer(main_boxes[-1], "Yes")
        await application._dd_flow
        assert json.loads(_read_dnd_row(db_path)) == {
            "enabled": True,
            "version": DND_MODULE_DATA_VERSION,
        }
        module = application._game_system_module
        assert isinstance(module, DndModule) and module.enabled
        # add-dnd-game-face (tasks 2.2 → 3.2): live attach пере-раздаёт
        # источники на месте — с группой 3 источник справочника настоящий, и
        # все три долгоживущих соавтора состава + реестр получают его в том
        # же живом сеансе, без перезапуска
        from app.domain import entity_registry as reg

        # add-dnd-game-face (task 8.2 → 11.1): живой attach пере-раздаёт уже
        # ЧЕТЫРЕ источника — справочник, табы персонажа, бестиарий и встречу
        # (табы ничего не объявляют; бестиарий объявляет dd_monster —
        # собственную сущность игры, вне рубильника; встреча — таб ядра и
        # пометки лестницы, собственных типов не объявляет)
        from app.dd.presentation.character_tab_source import DndCharacterTabSource
        from app.dd.presentation.dd_encounter_source import DndEncounterSource
        from app.dd.presentation.monster_source import DndMonsterSource
        from app.dd.presentation.reference_source import DndReferenceSource

        assert len(application._external_sources) == 4
        (
            reference_source,
            tab_source,
            monster_source,
            encounter_source,
        ) = application._external_sources
        assert isinstance(reference_source, DndReferenceSource)
        assert isinstance(tab_source, DndCharacterTabSource)
        assert isinstance(monster_source, DndMonsterSource)
        assert isinstance(encounter_source, DndEncounterSource)
        assert application._external_sources == tuple(module.external_sources)
        assert reg.external_types() == (
            reference_source.type_descriptors + monster_source.type_descriptors
        )
        assert application._search_service.external_sources == application._external_sources
        assert application._wiring.external_sources == application._external_sources
        assert window.entity_preview.vm.external_sources == application._external_sources
        # task 11.2: the ladder is the fourth long-lived reader — enable must
        # hand it the list too, or its rows would stay mark-free forever.
        assert application._wiring.timeline_vm.external_sources == (
            application._external_sources
        )
        # данные игры не тронуты: СВОИ таблицы и строки — слово в слово те же
        # (снимок теперь сознательно не видит dd_* — аддитивную половину
        # включения их создаёт сам enable, task 8.1/Д6; их состав ниже)
        assert _table_snapshot(db_path) == before
        # таблицы модуля появились включением и пустые (Д6: одна аддитивная
        # волна с флагом; наполнение — тесты 8.1)
        dd_tables, dd_rows = _dd_tables_snapshot(db_path)
        assert dd_tables == [
            "dd_character_ext",
            # dd-card-redesign (task 2.2, design Д6): the feat-link table
            # joins the same additive wave as the module's other tables.
            "dd_character_feat_link",
            "dd_character_spell_link",
            # task 11.1: the encounter overlay joins the same additive wave
            "dd_encounter",
            "dd_monster",
        ]
        assert set(dd_rows) == set(dd_tables)
        assert all(count == 0 for count in dd_rows.values())
        # add-dnd-game-face (task 10.2, spec dnd-bestiary «переключатель
        # справочных записей … монстров не касается»): живой рубильник ВНИЗ
        # гасит только справочный источник — видимость бестиария решает
        # один attach; настоящий поиск (тот же проход, тот же реестр) и
        # кандидаты упоминаний находят монстра при выключенном рубильнике.
        await module.reference_visibility.set_visible(False)
        assert reference_source.visible is False
        assert monster_source.visible is True
        from app.dd.application.monster_service import DdMonsterService

        await DdMonsterService(application._uow).save_monster(
            monster_id=None, name="Гоблин", rating=1, blocks={}
        )
        found = await application._search_service.search_all("гоб")
        assert [hit.name for hit in found["dd_monster"]] == ["Гоблин"]
        mention_rows = await application._search_service.search_names("гоб")
        assert any(
            row["type"] == "dd_monster" and row["name"] == "Гоблин"
            for row in mention_rows
        )
        await module.reference_visibility.set_visible(True)
        assert reference_source.visible is True
        # табы загораются живым attach (spec «Таб модуля живёт с модулем»)
        assert tab_source.visible is True
        # метка и группа модуля появились, kernel-пункт уступил место
        assert _badge(window) is not None and _badge(window).text() == "D&D"
        assert _module_menu(window) is not None
        # Меню-семейство съедает одиночный '&' как мнемонику (live-аудит
        # 2026-10-10: группа и пункты печатались «DD»); канонические подписи
        # доходят до экрана через '&'-удвоение — пин сверяет снятое удвоение.
        menu = _module_menu(window)
        from app.dd.presentation.section import (
            DD_DATASETS_ACTION_TEXT,
            DD_DISABLE_ACTION_TEXT,
            DD_MENU_TITLE,
        )

        assert menu.menuAction().text().replace("&&", "&") == DD_MENU_TITLE
        for action, caption in (
            (_datasets_action(window), DD_DATASETS_ACTION_TEXT),
            (_disable_action(window), DD_DISABLE_ACTION_TEXT),
        ):
            assert action.text().replace("&&", "&") == caption
        assert not window.enable_dd_module_action.isVisible()
    finally:
        window.close()
        await application.shutdown()


async def test_enable_write_failure_keeps_stub_and_tells_the_user(
    qapp, tmp_path, monkeypatch
):
    # Персистентная ошибка не глотается (принцип 3): modeless error-box,
    # состав остаётся stub, строка признака не появляется.
    db_path = _make_game_db(tmp_path, None)
    main_boxes = _install_modal_trap(monkeypatch)
    _install_modal_trap(monkeypatch, "app.dd.module.QMessageBox")

    async def _boom(*args, **kwargs):
        raise RuntimeError("диск отказал")

    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        monkeypatch.setattr(
            "app.dd.application.module_settings_service."
            "ModuleSettingsService.enable",
            _boom,
        )
        window.enable_dd_module_requested.emit()
        _answer(main_boxes[-1], "Yes")
        await application._dd_flow
        assert type(application._game_system_module) is NoopGameSystemModule
        assert _read_dnd_row(db_path) is None
        assert window.enable_dd_module_action.isVisible()
        # отдельный error-box, modeless, с причиной
        errors = [b for b in main_boxes if b.icon == b.Icon.Critical]
        assert len(errors) == 1
        assert "диск отказал" in errors[0].text
        assert application._dd_error_box is errors[0]
        # закрытие сбрасывает live-ref (постулата PR-010 для всех box'ов)
        _answer(errors[0], "Ok")
        assert application._dd_error_box is None
    finally:
        window.close()
        await application.shutdown()


# ── выключение с сохранением данных и повторное включение (task 2.3) ────────


async def test_disable_hides_the_module_and_reenable_returns_it(
    qapp, tmp_path, monkeypatch
):
    from app.dd.module import DndModule

    flag_value = json.dumps(
        {"enabled": True, "version": DND_MODULE_DATA_VERSION}
    )
    db_path = _make_game_db(tmp_path, flag_value)
    main_boxes = _install_modal_trap(monkeypatch)
    dd_boxes = _install_modal_trap(monkeypatch, "app.dd.module.QMessageBox")

    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        module = application._game_system_module
        assert isinstance(module, DndModule) and module.enabled
        assert _badge(window) is not None
        assert not window.enable_dd_module_action.isVisible()

        # «Выключить D&D-модуль…» — сначала подтверждение
        _disable_action(window).trigger()
        assert len(dd_boxes) == 1
        confirm = dd_boxes[0]
        from app.dd.module import DD_DISABLE_CONFIRM_BODY

        assert confirm.text == DD_DISABLE_CONFIRM_BODY

        # отвод (Нет) — модуль стоит, строка не тронута
        _answer(confirm, "No")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert module.enabled
        assert _read_dnd_row(db_path) == flag_value

        # Да: признак снят с сохранением версии, UI снят, пункт ядра вернулся
        # (task 11.2: вместе с detach лестница получает одну перезагрузку
        # через публичную дверь коннектора — пометки встреч гаснут сразу,
        # сам модификатор к viewmodel лестницы не тянется)
        reloads: list[int] = []
        real_reload = application._wiring.reload_timeline

        async def spy_reload():
            reloads.append(1)
            await real_reload()

        monkeypatch.setattr(application._wiring, "reload_timeline", spy_reload)
        _disable_action(window).trigger()
        _answer(dd_boxes[-1], "Yes")
        await module._disable_task
        assert reloads == [1]
        # видимость жизни модуля гаснет у источников с дверью set_attached
        # (встреча — одна из них: её пометки и гасит перезагрузка выше);
        # справочный источник живёт своим рубильником (двери не имеет)
        assert [source.visible for source in application._external_sources[1:]] == [
            False, False, False,
        ]
        assert json.loads(_read_dnd_row(db_path)) == {
            "enabled": False,
            "version": DND_MODULE_DATA_VERSION,
        }
        assert not module.enabled
        # remove() снимает бейдж с угла и вынимает действие меню из строки
        # сразу; физическое уничтожение виджетов — deleteLater, до него
        # доводится очередь событий (постулат DeferredDelete elsewhere).
        from PySide6.QtCore import QCoreApplication, QEvent

        assert window.menuBar().cornerWidget() is None
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert _badge(window) is None
        assert _module_menu(window) is None
        assert window.enable_dd_module_action.isVisible()

        # «Выключили и снова включили» — в той же сессии, без рестарта
        window.enable_dd_module_requested.emit()
        _answer(main_boxes[-1], "Yes")
        await application._dd_flow
        assert json.loads(_read_dnd_row(db_path)) == {
            "enabled": True,
            "version": DND_MODULE_DATA_VERSION,
        }
        module2 = application._game_system_module
        assert isinstance(module2, DndModule) and module2.enabled
        assert _badge(window) is not None
        assert not window.enable_dd_module_action.isVisible()
    finally:
        window.close()
        await application.shutdown()


async def test_opening_a_disabled_module_game_warns_about_hidden_data(
    qapp, tmp_path, monkeypatch
):
    # Spec «Выключение модуля с сохранением данных»: пока строка признака
    # хранит «выключено», следующее открытие говорит о скрытых данных —
    # отложенным modeless показом (PR-010), и предложение включения видно.
    flag_value = json.dumps(
        {"enabled": False, "version": DND_MODULE_DATA_VERSION}
    )
    db_path = _make_game_db(tmp_path, flag_value)
    boxes = _install_modal_trap(monkeypatch)
    _install_modal_trap(monkeypatch, "app.dd.module.QMessageBox")

    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        assert boxes == []  # ничего модального на контуре старта
        await asyncio.sleep(0)
        assert len(boxes) == 1
        box = boxes[0]
        assert box.shown_via == "show"
        assert box.parent is window
        assert box.title == DD_MODULE_UNAVAILABLE_TITLE
        assert box.text == DD_MODULE_OFF_WARNING
        assert application._dd_unavailable_box is box
        # путь назад виден: включение предлагается
        assert window.enable_dd_module_action.isVisible()
        # строка при открытии не тронута — предупреждение ничего не пишет
        assert _read_dnd_row(db_path) == flag_value
    finally:
        window.close()
        await application.shutdown()


# ── версия впереди: обычная игра, предупреждение, без предложения включения ─


async def test_ahead_version_gets_warning_and_no_enable_offer(
    qapp, tmp_path, monkeypatch
):
    ahead = json.dumps({"enabled": True, "version": 10_000})
    db_path = _make_game_db(tmp_path, ahead)
    boxes = _install_modal_trap(monkeypatch)
    _install_modal_trap(monkeypatch, "app.dd.module.QMessageBox")

    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        assert type(application._game_system_module) is NoopGameSystemModule
        await asyncio.sleep(0)
        assert len(boxes) == 1
        assert boxes[0].text == DD_MODULE_VERSION_WARNING
        # включить нельзя честно: признак игры новее, чем понимает сборка, —
        # предложение перезаписало бы версию и солгало о данных
        assert not window.enable_dd_module_action.isVisible()
        assert _read_dnd_row(db_path) == ahead
    finally:
        window.close()
        await application.shutdown()


# ── экран датасетов: пункт меню → лист → единственный экземпляр → detach ────


def test_datasets_entry_absent_without_screen_stack(qtbot):
    """Композиция без экранного стека (флаговые юниты собирали именно её)
    не печатает мёртвый пункт: «D&D» остаётся с одним выключением — и
    случайный зов экрана на прикреплённом без стека фасаде молчит."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMainWindow

    from app.dd.module import DndModule

    window = QMainWindow()
    qtbot.addWidget(window)
    module = DndModule()  # ни сервиса датасетов, ни связей, ни импорта
    module.attach(window, SimpleNamespace())
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        assert menu is not None
        names = [action.objectName() for action in menu.actions()]
        assert names == ["ddDisableAction"]
        module._on_datasets_requested()  # окно/коннектор есть, стека нет
        assert module._datasets_sheet is None
    finally:
        module.detach()


async def test_datasets_entry_opens_one_sheet_and_detach_takes_it_down(
    qapp, tmp_path, monkeypatch
):
    """Задача 5.2 живьём: живой лист строится штатным путём коннектора
    (Qt.Sheet, родитель — окно, заголовок шапки = название пункта), второй
    триггер поднимает живой лист вместо башни-близнеца, а отключение модуля
    убирает экран его же каналом finished и отпускает стек."""
    from PySide6.QtCore import Qt

    from app.dd.module import DndModule
    from app.dd.presentation.datasets_sheet import (
        DD_DATASETS_SHEET_TITLE,
        DndDatasetsSheet,
    )

    flag_value = json.dumps(
        {"enabled": True, "version": DND_MODULE_DATA_VERSION}
    )
    db_path = _make_game_db(tmp_path, flag_value)
    main_boxes = _install_modal_trap(monkeypatch)
    dd_boxes = _install_modal_trap(monkeypatch, "app.dd.module.QMessageBox")

    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        module = application._game_system_module
        assert isinstance(module, DndModule) and module.enabled
        # Живая композиция дала модулю экран датасетов — пункт на месте.
        _datasets_action(window)

        _datasets_action(window).trigger()
        sheet = window.findChild(DndDatasetsSheet)
        assert sheet is not None and sheet.isVisible()
        assert sheet.windowFlags() & Qt.WindowType.Sheet
        assert sheet.windowModality() == Qt.WindowModality.NonModal
        assert sheet.parent() is window
        title = sheet.findChild(QLabel, "sheetFrameTitle")
        assert title.text() == DD_DATASETS_SHEET_TITLE
        assert module._datasets_sheet is sheet
        assert application._wiring._open_sheets == [sheet]

        # Повторный триггер — подъём живого, не второй экземпляр.
        _datasets_action(window).trigger()
        assert application._wiring._open_sheets == [sheet]
        assert window.findChildren(DndDatasetsSheet).__len__() == 1

        # Мастер закрывает лист сам: finished-канал гасит ссылку фасада,
        # стек пустеет, «Закрыть» больше не о чём.
        from PySide6.QtWidgets import QPushButton

        sheet.findChild(QPushButton, "sheetFrameCloseButton").click()
        assert not sheet.isVisible()
        assert module._datasets_sheet is None
        assert sheet not in application._wiring._open_sheets

        # Выключение модуля снимает и его экран — лист уходит Rejected,
        # фасад забывает ссылку, стек пуст (шлюз меню возвращён).
        _disable_action(window).trigger()
        _answer(dd_boxes[-1], "Yes")
        await module._disable_task
        assert not sheet.isVisible()
        assert sheet.result() == sheet.DialogCode.Rejected
        assert module._datasets_sheet is None
        # Стек очищен от листа модуля; первый запуск новой игры оставил на
        # стеке свой визард календаря — он здесь ни при чём (autoaccept
        # гасит его exec, не снимая лист со стека).
        assert sheet not in application._wiring._open_sheets

        # Второй раунд «выключили — включили»: живой лист нового фасада
        # остаётся открытым до shutdown — detach закрывает экран и его же
        # каналом, и ссылкой больше не держит.
        window.enable_dd_module_requested.emit()
        _answer(main_boxes[-1], "Yes")
        await application._dd_flow
        module2 = application._game_system_module
        assert isinstance(module2, DndModule) and module2.enabled
        _datasets_action(window).trigger()
        # Первый лист живёт в дереве до deleteLater — ищем второй, видимый.
        sheet2 = next(
            s
            for s in window.findChildren(DndDatasetsSheet)
            if s is not sheet and s.isVisible()
        )
        await application.shutdown()
        assert not sheet2.isVisible()
        assert module2._datasets_sheet is None
    finally:
        window.close()
        await application.shutdown()
