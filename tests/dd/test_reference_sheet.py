"""Лист «Справочник…» (add-dnd-game-face, task 6.3; spec dnd-reference-records
«Справочный лист с вкладками по типам»).

Оффскрин-контур как у листа датасетов: хост-окно и настоящий коннектор
(``open_sheet``/``run_locked`` — стек и Qt.Sheet штатные), а источники — утки
протокола с готовыми строками: лист читает РОВНО двери ``type_descriptors`` и
``search`` и потому тестируется без датасетов и гримуаров (их связка
покрыта в test_reference_source.py).

Покрыты: вкладки по описателям (капча — множественное имя), строки с подписью
источника и без неё, клик — дверь предпросмотра + закрытие листа, фильтр по
имени (нейтральная подсказка при пустом результате), пустое состояние с
объяснением и входом в лист датасетов (и его отсутствие при не-составленном
экране датасетов), скрытый источник не греется, одиночный незавершённый
загрузчик, отмена задачи при закрытии; контракт доступности — штатные контролы
с именем = видимый текст (кнопки-строки, вкладка, фильтр).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget

from app.dd.presentation.reference_sheet import (
    DD_REFERENCE_EMPTY_TEXT,
    DD_REFERENCE_NO_MATCH_TEXT,
    DD_REFERENCE_OPEN_DATASETS_TEXT,
    DD_REFERENCE_SHEET_TITLE,
    DndReferenceSheet,
)
from app.presentation.modules.protocol import ExternalHit
from app.presentation.wiring import ApplicationWiring


class _Source:
    """Утка ExternalEntitySource ровно в том объёме, который лист читает
    (с task 10.1 — ещё и флаг ``reference``: лист смотрит на него, отсевая
    не-справочные типы)."""

    def __init__(self, descriptors, rows, visible=True) -> None:
        self.type_descriptors = [
            SimpleNamespace(key=key, label=label, plural_label=plural, reference=True)
            for key, label, plural in descriptors
        ]
        self.visible = visible
        self._rows = rows
        self.searches: list[str] = []

    async def search(self, query: str):
        self.searches.append(query)
        return self._rows


def _rows() -> list[ExternalHit]:
    return [
        ExternalHit("dd_class", "srd51/cleric", "Клейрик", "SRD 5.1 (2014)"),
        ExternalHit("dd_feat", "hb/lucky", "Везучесть", "Хоумбрю"),
        ExternalHit("dd_spell", "home/true-sight", "Истинное зрение", ""),
    ]


_DESCRIPTORS = [
    ("dd_class", "Класс", "Классы"),
    ("dd_feat", "Черта", "Черты"),
    ("dd_spell", "Заклинание", "Заклинания"),
]


def _make_window(qtbot):
    window = QWidget()
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


def _make_sheet(qtbot, source, open_datasets=lambda: None, extra_sources=()):
    """Лист на настоящем стеке коннектора + нажатие «загрузить» (task 10.1:
    ``extra_sources`` — второй источник в том же кортеже, вкладки строятся
    сразу по обоим)."""
    window, wiring = _make_window(qtbot)
    shown: list[str] = []
    sheet = DndReferenceSheet(
        sources=(source, *extra_sources),
        run_locked=wiring.run_locked,
        show_card=lambda key, source_id: shown.append((key, source_id)),
        open_datasets=open_datasets,
        parent=window,
    )
    wiring.open_sheet(sheet)
    sheet.request_refresh()
    return sheet, shown


async def _loaded(sheet) -> None:
    await sheet._load_task


def _row_buttons(sheet) -> list[QPushButton]:
    tabs = sheet.findChild(QTabWidget)
    page = tabs.currentWidget()
    if page is None:  # вырожденный лист без вкладок
        return []
    return [
        b
        for b in page.findChildren(QPushButton)
        if b.objectName() == "referenceRow"
    ]


async def test_tabs_rows_and_sheet_contract(qtbot):
    """Вкладки — по описателям источника (капча множественная), строки текущей
    вкладки подписаны источником, без origin — без разделителя; окно — штатный
    attached-лист контракта (Qt.Sheet, не Qt-модальный, заголовок = name)."""
    sheet, _ = _make_sheet(qtbot, _Source(_DESCRIPTORS, _rows()))
    await _loaded(sheet)
    try:
        assert sheet.windowFlags() & Qt.WindowType.Sheet
        assert sheet.windowModality() == Qt.WindowModality.NonModal
        assert sheet.windowTitle() == DD_REFERENCE_SHEET_TITLE
        tabs = sheet.findChild(QTabWidget)
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            "Классы",
            "Черты",
            "Заклинания",
        ]
        assert [b.text() for b in _row_buttons(sheet)] == ["Клейрик · SRD 5.1 (2014)"]
        # доступность: у штатной кнопки имя = видимый текст, вкладка — PageTab
        button = _row_buttons(sheet)[0]
        assert button.text() == "Клейрик · SRD 5.1 (2014)"
        tabs.setCurrentIndex(2)  # смена вкладки перерисовывает список
        assert [b.text() for b in _row_buttons(sheet)] == ["Истинное зрение"]
    finally:
        sheet.close()


async def test_row_click_opens_preview_and_closes_sheet(qtbot):
    """Спека «клик по строке открывает карточку в правой колонке»: дверь —
    (ключ, source_id) коннекторного show_external_card; лист закрывается,
    чтобы колонку было видно (docstring листа)."""
    sheet, shown = _make_sheet(qtbot, _Source(_DESCRIPTORS, _rows()))
    await _loaded(sheet)
    button = _row_buttons(sheet)[0]
    button.click()
    assert shown == [("dd_class", "srd51/cleric")]
    assert not sheet.isVisible()


async def test_filter_narrows_rows_by_name(qtbot):
    """Фильтр — подстрока имени, регистронезависимо; при пустом результате
    фильтра — нейтральная подсказка и НИКАКОЙ кнопки датасетов (полки-то
    собраны); очистка возвращает строки."""
    sheet, _ = _make_sheet(qtbot, _Source(_DESCRIPTORS, _rows()))
    await _loaded(sheet)
    sheet._filter.setText("клей")
    assert [b.text() for b in _row_buttons(sheet)] == ["Клейрик · SRD 5.1 (2014)"]
    sheet._filter.setText("КЛЕЙРИК")
    assert len(_row_buttons(sheet)) == 1
    sheet._filter.setText("ничего-нет")
    assert _row_buttons(sheet) == []
    assert sheet._empty_label.text() == DD_REFERENCE_NO_MATCH_TEXT
    assert sheet._empty_label.isVisible()
    assert not sheet._datasets_button.isVisible()
    sheet._filter.setText("")
    assert len(_row_buttons(sheet)) == 1
    sheet.close()


async def test_filter_matches_identifier_and_slug_and_blank_is_the_whole_tab(
    qtbot,
):
    """fix-dnd-followups 4.2 (spec dnd-reference-records «Фильтр SHALL быть
    регистронезависимой подстрокой»): запись попадает в результат, если текст
    встречается в ИДЕНТИФИКАТОРЕ/СЛОГЕ (source_id), а не только в имени;
    пустой ввод и ввод из одних пробелов показывают весь список вкладки."""
    sheet, _ = _make_sheet(qtbot, _Source(_DESCRIPTORS, _rows()))
    await _loaded(sheet)
    tabs = sheet.findChild(QTabWidget)

    # Идентификатор записи (латиница в source_id) ищется, когда имя на него
    # не похожа: «Клейрик» по «cleric» проходит только через id-ветку.
    sheet._filter.setText("cleric")
    assert [b.text() for b in _row_buttons(sheet)] == ["Клейрик · SRD 5.1 (2014)"]
    # ...регистронезависимо и в другую сторону: запрос в верхнем регистре
    # против идентификатора в нижнем.
    sheet._filter.setText("CLERIC")
    assert len(_row_buttons(sheet)) == 1
    # Обрамляющие пробелы снимаются — тот же hit.
    sheet._filter.setText("  cleric  ")
    assert len(_row_buttons(sheet)) == 1

    # Слаг заклинания — тоже идентификатор: на вкладке «Заклинания» имя
    # «Истинное зрение», слаг «true-sight» — фильтр идёт по слагу.
    tabs.setCurrentIndex(2)
    sheet._filter.setText("true-sight")
    assert [b.text() for b in _row_buttons(sheet)] == ["Истинное зрение"]
    sheet._filter.setText("SIGHT")
    assert len(_row_buttons(sheet)) == 1

    # Пустой ввод = весь список вкладки; пробелы = пустой ввод (spec
    # «пустая строка или только пробелы показывают весь список вкладки»).
    sheet._filter.setText("")
    assert len(_row_buttons(sheet)) == 1
    tabs.setCurrentIndex(1)  # «Черты» — своя строка
    sheet._filter.setText("   ")
    assert [b.text() for b in _row_buttons(sheet)] == ["Везучесть · Хоумбрю"]
    sheet.close()


async def test_empty_shelf_explains_and_offers_datasets(qtbot):
    """Ни одной строки (пустые подключения — спека): объяснение + вход в лист
    датасетов; без собранного экрана датасетов кнопка не предлагается вовсе."""
    opens: list[bool] = []
    sheet, _ = _make_sheet(
        qtbot, _Source(_DESCRIPTORS, []), open_datasets=lambda: opens.append(True)
    )
    await _loaded(sheet)
    assert sheet._empty_label.text() == DD_REFERENCE_EMPTY_TEXT
    assert sheet._empty_label.isVisible()
    # The caption the reader sees (and the tree answers) is the screen's
    # own name: the button's text carries Qt's doubled-ampersand escape,
    # the painted and accessible caption is «Датасеты D&D…» (task 12.1 —
    # a bare '&' would print «Датасеты DD…»).
    assert QAccessible.queryAccessibleInterface(sheet._datasets_button).text(
        QAccessible.Name
    ) == DD_REFERENCE_OPEN_DATASETS_TEXT
    assert sheet._datasets_button.isVisible()
    sheet._datasets_button.click()
    assert opens == [True]
    sheet.close()

    no_way_out, _ = _make_sheet(qtbot, _Source(_DESCRIPTORS, []), open_datasets=None)
    await _loaded(no_way_out)
    assert no_way_out._empty_label.isVisible()
    assert not no_way_out._datasets_button.isVisible()
    no_way_out.close()


async def test_hidden_source_not_consulted_empty_answer(qtbot):
    """Скрытый рубильником источник не отдаёт строк — лист в пустом состоянии
    (объяснение на месте), ``search`` у источника не зовётся: решение о
    видимости — постель самого листа по протокольному флагу."""
    source = _Source(_DESCRIPTORS, _rows(), visible=False)
    sheet, _ = _make_sheet(qtbot, source)
    await _loaded(sheet)
    assert source.searches == []
    assert sheet._empty_label.isVisible()
    sheet.close()


async def test_single_inflight_loader_and_cancel_on_close(qtbot):
    """Повторный request_refresh при живом загрузчике не заводит второй забег;
    закрытие листа отменяет незавершённый (дисциплина PR-037/листа датасетов)."""
    gate = asyncio.Event()
    window, wiring = _make_window(qtbot)

    class _SlowSource(_Source):
        async def search(self, query: str):
            self.searches.append(query)
            await gate.wait()
            return self._rows

    source = _SlowSource(_DESCRIPTORS, _rows())
    sheet = DndReferenceSheet(
        sources=(source,),
        run_locked=wiring.run_locked,
        show_card=lambda key, source_id: None,
        open_datasets=lambda: None,
        parent=window,
    )
    wiring.open_sheet(sheet)
    sheet.request_refresh()
    first = sheet._load_task
    sheet.request_refresh()
    assert sheet._load_task is first
    await asyncio.sleep(0)
    assert source.searches == [""]  # один забег, пустой запрос = перечисление
    sheet.close()
    await asyncio.sleep(0)  # отмена доживает до цикла событий
    assert first.cancelled()
    gate.set()


async def test_non_reference_types_stay_out_of_the_shelf(qtbot):
    """Task 10.1: источник с не-справочным типом (монстр бестиария живёт в
    том же кортеже источников) не получает вкладки, его строки не попадают в
    лист и не портят арифметику пустого состояния — «полки пусты» честно
    объясняется, хотя монстр в источнике есть."""
    monster_source = _Source([], [])
    monster_source.type_descriptors = [
        SimpleNamespace(
            key="dd_monster", label="Монстр", plural_label="Монстры", reference=False
        )
    ]
    monster_source._rows = [ExternalHit("dd_monster", "1", "Гоблин")]
    shelf = _Source(_DESCRIPTORS[:1], [])  # полок ноль, монстр — есть
    sheet, _ = _make_sheet(qtbot, shelf, extra_sources=(monster_source,))
    await _loaded(sheet)
    tabs = sheet.findChild(QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Классы"]
    assert tabs.isHidden()  # полок ни одной строки — объяснение вместо вкладок
    assert sheet._empty_label.text() == DD_REFERENCE_EMPTY_TEXT
    assert sheet._empty_label.isVisible()
    # строки монстра не записаны ни под какой вкладкой
    assert "dd_monster" not in sheet._rows
    sheet.close()

    # монстр + живая справочная строка: вкладки на месте, строка одна
    full_shelf = _Source(_DESCRIPTORS[:1], _rows()[:1])
    second, _ = _make_sheet(qtbot, full_shelf, extra_sources=(monster_source,))
    await _loaded(second)
    assert [b.text() for b in _row_buttons(second)] == ["Клейрик · SRD 5.1 (2014)"]
    assert second._empty_label.isHidden()
    second.close()


async def test_degenerate_source_without_descriptors(qtbot):
    """Источник без описателей — ни вкладок, ни падения: загрузка проходит
    через перерисовку текущей вкладки и молча выходит при отсутствии
    вкладки (фасад печатает пункт только при непустых источниках, но лист
    обязан выдержать и вырожденный)."""
    sheet, _ = _make_sheet(qtbot, _Source([], []))
    await _loaded(sheet)
    tabs = sheet.findChild(QTabWidget)
    assert tabs.count() == 0
    assert _row_buttons(sheet) == []
    sheet.close()


# ── фасад модуля: пункт меню, одиночный экземпляр, detach ─────────────────────


async def test_module_reference_entry_raises_one_sheet(qtbot):
    """Пункт «Справочник…» печатается только при собранных источниках; первый
    триггер строит лист путём коннектора, второй поднимает живой вместо
    башни-близнеца; detach убирает экран и отпускает ссылку."""
    from PySide6.QtWidgets import QMainWindow, QMenu

    from app.dd.module import DndModule

    def _pair():
        window = QMainWindow()
        qtbot.addWidget(window)
        wiring = ApplicationWiring(
            SimpleNamespace(_image_store=None, _theme=None),
            window,
            None,
            None,
            None,
            None,
            None,
            SimpleNamespace(lock=asyncio.Lock()),
        )
        return window, wiring

    # фаза 1: композиция без источников — мёртвый пункт не печатается,
    # случайный зов молчит (оконная пара своя: detach помечает меню к удалению)
    window, wiring = _pair()
    module = DndModule()
    module.attach(window, wiring)
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        names = [action.objectName() for action in menu.actions()]
        assert "ddReferenceAction" not in names
        module._on_reference_requested()  # belt-and-braces выход молча
        assert module._reference_sheet is None
    finally:
        module.detach()

    # фаза 2: источники собраны — пункт на месте, один живой лист
    window, wiring = _pair()
    module = DndModule(external_sources=(_Source(_DESCRIPTORS, _rows()),))
    module.attach(window, wiring)
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        action = next(
            a for a in menu.actions() if a.objectName() == "ddReferenceAction"
        )
        assert action.text() == "Справочник…"
        action.trigger()
        sheet = next(
            (w for w in window.findChildren(DndReferenceSheet)), None
        )
        assert sheet is not None
        await sheet._load_task
        first = module._reference_sheet
        assert first is sheet
        action.trigger()  # второй раз — подъём живого, не близнец
        assert module._reference_sheet is first
        assert len(window.findChildren(DndReferenceSheet)) == 1
        # мастер закрывает лист сам: finished-канал гасит ссылку фасада
        first.reject()
        assert module._reference_sheet is None
        assert wiring._open_sheets == []
        # живой лист на момент detach: фасад снимает его своим каналом
        action.trigger()
        second = module._reference_sheet
        assert second is not None and second.isVisible()
    finally:
        module.detach()
    assert module._reference_sheet is None
    assert not first.isVisible() and not second.isVisible()
    assert wiring._open_sheets == []


async def test_detached_facade_reference_flow_is_inert():
    """Фасад без attach: триггер справочника не рисует окно и не роняет None."""
    from app.dd.module import DndModule

    module = DndModule(external_sources=(_Source(_DESCRIPTORS, _rows()),))
    module._on_reference_requested()
    assert module._reference_sheet is None
