"""Лист «Бестиарий» и фасадный вход в него (add-dnd-game-face task 10.1;
spec dnd-bestiary «Бестиарий — список с входом из меню модуля»).

Оффскрин-контур как у листа справочника: хост-окно и настоящий коннектор
(``open_sheet``/``run_locked`` — штатный attached-лист контракта), а сервис —
утка с готовым списком: лист читает ровно ``list_monsters`` и потому
тестируется без БД.

Покрыты: строки «имя · рейтинг N», клик по строке — дверь карточки с id и
лист НЕ закрывается (карточка — лист поверх стека, возвращаться к фильтру
нечего), фильтр по имени регистронезависимо, пустое состояние с объяснением
и кнопкой создания (спека «видно объяснение и кнопку создания»), нейтральная
подсказка при пустом результате фильтра, одиночный загрузчик и отмена при
закрытии; контракт доступности — штатные контролы с именем = видимый текст.

Фасад: пункт «Бестиарий…» только при собранном сервисе, одиночный живой лист
(повторный триггер поднимает его, а не плодит близнеца), карточки под
одиночным экземпляром на монстра (creation — под ``None``), после первого
сохранения creation-карточка переезжает на ключ своей строки (открытие из
бестиария поднимает ЕЁ), detach снимает и лист, и карточки.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QPushButton, QWidget

from app.dd.domain.monster import DdMonster
from app.dd.presentation.bestiary_sheet import (
    DD_BESTIARY_CREATE_TEXT,
    DD_BESTIARY_EMPTY_TEXT,
    DD_BESTIARY_NO_MATCH_TEXT,
    DD_BESTIARY_SHEET_TITLE,
    DndBestiarySheet,
    monster_row_caption,
)
from app.dd.module import DndModule
from app.presentation.wiring import ApplicationWiring


class _Service:
    """Утка DdMonsterService: список + минимум для карточного flow фасада."""

    def __init__(self, monsters=None) -> None:
        self.monsters = list(monsters or [])
        self.list_calls = 0

    async def list_monsters(self):
        self.list_calls += 1
        return list(self.monsters)

    async def get_monster(self, monster_id):
        return next((m for m in self.monsters if m.id == monster_id), None)

    async def image_preview_path(self, image_id):
        return None

    async def save_monster(
        self, *, monster_id, name, rating, blocks, image_data=None, clear_image=False
    ):
        name = name.strip()
        assert name
        if monster_id is None:
            monster_id = max((m.id for m in self.monsters), default=0) + 1
            monster = DdMonster(
                id=monster_id, name=name, rating=rating, blocks=dict(blocks), image_id=None
            )
            self.monsters.append(monster)
            return monster
        monster = next(m for m in self.monsters if m.id == monster_id)
        return DdMonster(
            id=monster_id, name=name, rating=rating, blocks=dict(blocks),
            image_id=monster.image_id,
        )


def _monster(mid, name, rating=1):
    return DdMonster(id=mid, name=name, rating=rating, blocks={}, image_id=None)


def _make_window(qtbot, main=False):
    window = QMainWindow() if main else QWidget()
    qtbot.addWidget(window)
    window.show()
    app = SimpleNamespace(_image_store=None, _theme=None)
    wiring = ApplicationWiring(
        app,
        window,
        None,
        None,
        None,
        None,
        None,
        SimpleNamespace(lock=asyncio.Lock()),
    )
    return window, wiring


def _make_sheet(qtbot, service, opened=None):
    window, wiring = _make_window(qtbot)
    sheet = DndBestiarySheet(
        service=service,
        run_locked=wiring.run_locked,
        open_card=(opened if opened is not None else lambda monster_id: None),
        parent=window,
    )
    wiring.open_sheet(sheet)
    sheet.request_refresh()
    return sheet


async def _loaded(sheet) -> None:
    await sheet._load_task


def _row_buttons(sheet) -> list[QPushButton]:
    return [
        b
        for b in sheet.findChildren(QPushButton)
        if b.objectName() == "bestiaryRow"
    ]


def test_row_caption_names_the_two_list_fields():
    assert monster_row_caption(_monster(1, "Гоблин", 2)) == "Гоблин · рейтинг 2"


async def test_rows_contract_and_no_close_on_open(qtbot):
    """Штатный attached-лист (Qt.Sheet, не Qt-модальный, заголовок = name),
    строки с рейтингом, клик — дверь карточки; лист остаётся открытым:
    навигация ведёт в лист же, а не под него."""
    opened: list[int | None] = []
    sheet = _make_sheet(
        qtbot, _Service([_monster(1, "Гоблин", 2), _monster(2, "Огр")]), opened.append
    )
    await _loaded(sheet)
    try:
        assert sheet.windowFlags() & Qt.WindowType.Sheet
        assert sheet.windowModality() == Qt.WindowModality.NonModal
        assert sheet.windowTitle() == DD_BESTIARY_SHEET_TITLE
        assert [b.text() for b in _row_buttons(sheet)] == [
            "Гоблин · рейтинг 2",
            "Огр · рейтинг 1",
        ]
        _row_buttons(sheet)[1].click()
        assert opened == [2]
        assert sheet.isVisible()
    finally:
        sheet.close()


async def test_filter_and_create_entries(qtbot):
    opened: list[int | None] = []
    sheet = _make_sheet(
        qtbot, _Service([_monster(1, "Гоблин"), _monster(2, "Огр")]), opened.append
    )
    await _loaded(sheet)
    sheet._filter.setText("огр")
    assert [b.text() for b in _row_buttons(sheet)] == ["Огр · рейтинг 1"]
    sheet._filter.setText("ГОБЛИН")
    assert len(_row_buttons(sheet)) == 1
    sheet._filter.setText("ничего-нет")
    assert _row_buttons(sheet) == []
    assert sheet._empty_label.text() == DD_BESTIARY_NO_MATCH_TEXT
    assert sheet._empty_label.isVisible()
    # при живом бестиарии кнопка пустоты не предлагается, верхняя — живая
    assert not sheet._empty_create_button.isVisible()
    sheet._filter.setText("")
    assert len(_row_buttons(sheet)) == 2
    sheet._create_button.text() == DD_BESTIARY_CREATE_TEXT
    sheet._create_button.click()
    assert opened == [None]  # создание — дверь с None
    sheet.close()


async def test_empty_state_explains_and_creates(qtbot):
    """Спека «Список пуст и подсказывает»: объяснение + кнопка создания."""
    opened: list[int | None] = []
    sheet = _make_sheet(qtbot, _Service([]), opened.append)
    await _loaded(sheet)
    assert sheet._empty_label.text() == DD_BESTIARY_EMPTY_TEXT
    assert sheet._empty_label.isVisible()
    assert sheet._empty_create_button.isVisible()
    sheet._empty_create_button.click()
    assert opened == [None]
    sheet.close()


async def test_single_inflight_loader_and_cancel_on_close(qtbot):
    gate = asyncio.Event()

    class _Slow(_Service):
        async def list_monsters(self):
            self.list_calls += 1
            await gate.wait()
            return self.monsters

    window, wiring = _make_window(qtbot)
    service = _Slow([_monster(1, "Гоблин")])
    sheet = DndBestiarySheet(
        service=service,
        run_locked=wiring.run_locked,
        open_card=lambda monster_id: None,
        parent=window,
    )
    wiring.open_sheet(sheet)
    sheet.request_refresh()
    first = sheet._load_task
    sheet.request_refresh()
    assert sheet._load_task is first
    await asyncio.sleep(0)
    assert service.list_calls == 1
    sheet.close()
    await asyncio.sleep(0)
    assert first.cancelled()
    gate.set()


# ── фасад: пункт меню, одиночные лист и карточки, detach ────────────────────


class _MonsterSource:
    """Утка источника с одним описателем dd_monster (фасад ищет источник
    по декларации, warm пишет в счётчик)."""

    def __init__(self, descriptor) -> None:
        self.type_descriptors = (descriptor,)
        self.warm_calls = 0
        self.visible = True

    async def warm(self) -> None:
        self.warm_calls += 1


async def test_module_bestiary_entry_sheets_and_detach(qtbot):
    from PySide6.QtWidgets import QMenu

    # фаза 1: без сервиса — мёртвый пункт не печатается, случайный зов молчит
    window, wiring = _make_window(qtbot, main=True)
    module = DndModule()
    # belt-and-braces до attach: ни окна, ни коннектора — обе двери молчат
    module._on_bestiary_requested()
    module._open_monster_card(1)
    assert module._bestiary_sheet is None and module._monster_cards == {}
    module.attach(window, wiring)
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        names = [action.objectName() for action in menu.actions()]
        assert "ddBestiaryAction" not in names
        module._on_bestiary_requested()
        module._open_monster_card(1)
        assert module._bestiary_sheet is None and module._monster_cards == {}
    finally:
        module.detach()
        window.deleteLater()

    # фаза 2: сервис + источник собраны — лист один, карточки по ключам
    from app.dd.presentation.monster_source import MONSTER_TYPE

    service = _Service([_monster(1, "Гоблин"), _monster(2, "Огр")])
    source = _MonsterSource(MONSTER_TYPE)
    assert module._monster_source() is None  # без источника — None и до attach
    window, wiring = _make_window(qtbot, main=True)
    module = DndModule(external_sources=(source,), monster_service=service)
    module.attach(window, wiring)
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        action = next(a for a in menu.actions() if a.objectName() == "ddBestiaryAction")
        assert action.text() == "Бестиарий…"
        action.trigger()
        sheet = module._bestiary_sheet
        assert isinstance(sheet, DndBestiarySheet)
        await _loaded(sheet)
        assert [b.text() for b in _row_buttons(sheet)] == [
            "Гоблин · рейтинг 1",
            "Огр · рейтинг 1",
        ]
        action.trigger()  # повторный триггер поднимает живой лист
        assert module._bestiary_sheet is sheet
        # клик по строке открывает карточку этого монстра (не близнеца)
        _row_buttons(sheet)[0].click()
        card = module._monster_cards[1]
        _row_buttons(sheet)[0].click()
        assert module._monster_cards[1] is card
        # карточка создания живёт под None
        module._open_monster_card(None)
        creation = module._monster_cards[None]
        assert creation.monster_id is None and creation is not card
        # сохранение creation-карточки перекладывает её на ключ строки
        creation._name.setText("Волк")
        await creation._save()
        assert source.warm_calls == 1
        assert None not in module._monster_cards
        saved_id = creation.monster_id
        assert saved_id is not None and module._monster_cards[saved_id] is creation
        # закрытие карточки снимает ссылку
        creation.close()
        await asyncio.sleep(0)
        assert saved_id not in module._monster_cards
        # закрытие листа снимает резидента через finished-обработчик
        sheet.close()
        assert module._bestiary_sheet is None
        # повторный триггер собирает новый лист; detach снимает его веткой
        # detach'а (лист жив к моменту выхода из игры)
        action.trigger()
        second = module._bestiary_sheet
        assert second is not None and second is not sheet
        await second._load_task
    finally:
        module.detach()
        assert module._bestiary_sheet is None
        assert module._monster_cards == {}
        assert not sheet.isVisible() and not second.isVisible()
        window.deleteLater()
