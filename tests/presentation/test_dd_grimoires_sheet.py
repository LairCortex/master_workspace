"""Лист «Гримуары…» (add-dnd-game-face, task 4.5; spec dnd-grimoire-import
«Гримуары доступны из интерфейса игры»).

Оффскрин-контур — как у листа датасетов: хост-окно, коннектор целиком
(``open_sheet``/``run_locked``/стек — настоящие), а trio
хранилище+связи+импорт — настоящие поверх ``tmp_path``-полки и штатной
``uow``. Ловушка PR-010 стоит на
``app.dd.presentation.grimoires_sheet.QMessageBox``; файловый выбор — подмена
``getOpenFileName`` (сам выбор — системное всплывающее окно, фиксированный
класс-исключение контракта окон).

Покрыты: контракт листа (заголовок = windowTitle = пункт меню, Qt.Sheet без
Qt-модальности, стек), список хранилища с призраком и строкой-маркером,
подключение/отключение чекбоксом с сохранением файла, все ветки импорта
(успех, предупреждения, отказ с отчётом, «id не может именем файла», замена
Да/Нет, нечитаемый файл, отмена выбора, падение импортера), провал загрузки
рамки и провал записи подключения, отмена незавершённых задач при закрытии
(PR-037, виджет-издание) — включая снятую задачу самой рамки и отпуск
ссылки notice-бокса после ответа, русские формы счётчика заклинаний,
токен-ветка полей на настоящей теме, и сценарий спека «подключил из списка
— заклинания видно» на настоящих индексе и справочном источнике.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QTableWidget, QWidget

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_index_service import DatasetIndexService
from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.application.grimoire_import_service import GrimoireImportService
from app.dd.application.grimoire_index_service import GrimoireIndexService
from app.dd.application.reference_visibility_service import (
    ReferenceVisibilityService,
)
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.dd.presentation.grimoires_sheet import (
    DD_GRIMOIRES_CONFIRM_TITLE,
    DD_GRIMOIRES_IMPORT_TITLE,
    DD_GRIMOIRES_IMPORT_UNEXPECTED_BODY,
    DD_GRIMOIRES_SHEET_TITLE,
    DndGrimoiresSheet,
    _spell_phrase,
)
from app.dd.presentation.reference_source import DndReferenceSource
from app.presentation.wiring import ApplicationWiring
from tests.dd.grimoire_fixtures import (
    content_of,
    foundry_compendium_export,
    foundry_item_list_export,
    foundry_single_item_export,
    foundry_spells_key_export,
)
from tests.test_application_settings_errors import _install_modal_trap

TINA_ID = "tina-grimoire"
SINGLE_ID = "kn3v7dqm1xt0abcd"


def _make_wiring(window) -> ApplicationWiring:
    app = SimpleNamespace(_image_store=None, _theme=None)
    return ApplicationWiring(
        app,
        window,
        None,
        None,
        None,
        None,
        None,
        SimpleNamespace(lock=asyncio.Lock()),
    )


def _seed_storage(tmp_path) -> GrimoireStorage:
    """Две полки: компендиум «Гримуар Тины» и одиночный предмет-выгрузка."""
    storage = GrimoireStorage(tmp_path / "grimoires")
    storage.save(TINA_ID, content_of(foundry_compendium_export()))
    storage.save(SINGLE_ID, content_of(foundry_single_item_export()))
    return storage


class _SheetHarness:
    """Окно + коннектор + сервисное trio + сам лист, уже на стеке."""

    def __init__(self, qtbot, uow, tmp_path, monkeypatch):
        self.uow = uow
        self.monkeypatch = monkeypatch
        self.window = QWidget()
        qtbot.addWidget(self.window)
        self.window.show()
        self.wiring = _make_wiring(self.window)
        self.states: list[bool] = []
        self.wiring.sheet_stack_changed.connect(self.states.append)
        self.storage = _seed_storage(tmp_path)
        self.connections = GrimoireConnectionsService(uow, self.storage)
        self.importer = GrimoireImportService(self.storage)
        self.boxes = _install_modal_trap(
            monkeypatch, "app.dd.presentation.grimoires_sheet.QMessageBox"
        )
        self.tasks: list[asyncio.Task] = []

        def _run_locked(coro):
            task = self.wiring.run_locked(coro)
            self.tasks.append(task)
            return task

        self.sheet = DndGrimoiresSheet(
            storage=self.storage,
            connections=self.connections,
            importer=self.importer,
            run_locked=_run_locked,
            parent=self.window,
            theme=None,
        )
        qtbot.addWidget(self.sheet)

    def open(self) -> DndGrimoiresSheet:
        self.wiring.open_sheet(self.sheet)
        self.sheet.request_refresh()
        return self.sheet

    async def flush(self, rounds: int = 60) -> None:
        """Крутим цикл до тишины (aiosqlite-потокам нужны настоящие проходы
        цикла; три тихих раунда — тишина наступила)."""
        quiet = 0
        for _ in range(rounds):
            await asyncio.sleep(0.005)
            if all(task.done() for task in self.tasks):
                quiet += 1
                if quiet >= 3:
                    return
            else:
                quiet = 0

    @property
    def table(self) -> QTableWidget:
        return self.sheet.findChild(QTableWidget, "ddGrimoireTable")

    def row_of(self, grimoire_id: str) -> int:
        return self.sheet._row_ids.index(grimoire_id)

    def check_box(self, grimoire_id: str) -> QCheckBox:
        holder = self.table.cellWidget(self.row_of(grimoire_id), 1)
        return holder.findChild(QCheckBox)

    def last_box(self):
        assert self.boxes, "ни одного boxes-окна не показано"
        return self.boxes[-1]

    def pick_file(self, monkeypatch, path: str) -> None:
        monkeypatch.setattr(
            "app.dd.presentation.grimoires_sheet.QFileDialog.getOpenFileName",
            lambda *args, **kwargs: (path, ""),
        )

    def write_file(self, name: str, document) -> str:
        path = Path(name)
        path.write_text(content_of(document), encoding="utf-8")
        return str(path)


@pytest.fixture
async def harness(qtbot, uow, tmp_path, monkeypatch):
    harness = _SheetHarness(qtbot, uow, tmp_path, monkeypatch)
    yield harness
    harness.sheet.close()
    for task in list(harness.tasks):
        if not task.done():
            task.cancel()
    await asyncio.gather(*harness.tasks, return_exceptions=True)
    for _ in range(4):
        await asyncio.sleep(0.005)


def _answer(box, button_name: str) -> None:
    for handler in box.finished.handlers:
        handler(getattr(box.StandardButton, button_name))


# ── лист и его контракт (4.5) ─────────────────────────────────────────────────


async def test_sheet_rides_the_open_sheet_contract(qtbot, harness):
    """Оконный контракт: заголовок шапки = windowTitle = пункт меню,
    Attached-лист Qt.Sheet БЕЗ Qt-модальности (PR-012), стек поднимается
    открытием и отпускается закрытием «Закрыть» (тот же reject, что Esc)."""
    sheet = harness.open()
    await harness.flush()

    assert sheet.windowTitle() == DD_GRIMOIRES_SHEET_TITLE
    assert sheet.findChild(QLabel, "sheetFrameTitle").text() == (
        DD_GRIMOIRES_SHEET_TITLE
    )
    assert sheet.size() == QSize(620, 520)
    assert sheet.windowFlags() & Qt.WindowType.Sheet
    assert sheet.windowModality() == Qt.WindowModality.NonModal
    assert sheet.isVisible()
    assert harness.states == [True]

    sheet.findChild(QPushButton, "sheetFrameCloseButton").click()
    assert not sheet.isVisible()
    assert harness.states == [True, False]
    assert sheet.result() == sheet.DialogCode.Rejected


async def test_storage_table_lists_shelf_ghost_and_checkboxes(qtbot, harness):
    """Список хранилища по id, подключённый призрак отдельной строкой и
    строкой-маркером, чекбоксы названы своим делом на строке."""
    await harness.connections.connect(TINA_ID)
    await harness.connections.connect("lost-grimoire")  # полки нет — призрак
    harness.open()
    await harness.flush()

    table = harness.table
    assert harness.sheet._row_ids == [SINGLE_ID, TINA_ID, "lost-grimoire"]
    assert "Гримуар Тины" in table.item(1, 0).text()
    # Призрак: имя строки говорит об отсутствии файла, чекбокс включён.
    assert "файл отсутствует в хранилище" in table.item(2, 0).text()
    assert harness.check_box("lost-grimoire").isChecked()
    marker = harness.sheet.findChild(QLabel, "ddMissingGrimoiresLabel")
    assert marker.isVisible() and "lost-grimoire" in marker.text()

    connected_box = harness.check_box(TINA_ID)
    assert connected_box.isChecked()
    assert connected_box.accessibleName() == "Отключить гримуар от игры"
    assert not harness.check_box(SINGLE_ID).isChecked()
    assert harness.check_box(SINGLE_ID).accessibleName() == "Подключить гримуар к игре"


async def test_connect_checkbox_writes_link_disconnect_keeps_file(
    qtbot, harness
):
    """Спека «Игра подключает гримуары списком, отключение обратимо»:
    чекбокс пишет ссылку, снятие убирает ТОЛЬКО ссылку — файл жив."""
    harness.open()
    await harness.flush()

    harness.check_box(SINGLE_ID).click()
    await harness.flush()
    assert SINGLE_ID in await harness.connections.connections()
    stored = harness.storage.load_content(SINGLE_ID)
    assert stored is not None

    harness.check_box(SINGLE_ID).click()
    await harness.flush()
    assert SINGLE_ID not in await harness.connections.connections()
    # файл остался на полке и тот же — отключение обратимо, перечитать можно
    assert harness.storage.load_content(SINGLE_ID) == stored
    assert not harness.check_box(SINGLE_ID).isChecked()


async def test_ghost_disconnect_clears_the_marker(qtbot, harness):
    """Призрака можно отключить тем же чекбоксом — маркер гаснет."""
    await harness.connections.connect("lost-grimoire")
    harness.open()
    await harness.flush()

    harness.check_box("lost-grimoire").click()
    await harness.flush()

    marker = harness.sheet.findChild(QLabel, "ddMissingGrimoiresLabel")
    assert not marker.isVisible()
    assert "lost-grimoire" not in await harness.connections.connections()


# ── импорт файла (спека «Импорт из интерфейса») ──────────────────────────────


async def test_import_success_reports_and_lists_new_shelf(qtbot, harness, tmp_path):
    """Успех: INFORMATION-бокс с числом заклинаний, полка появилась в списке."""
    harness.open()
    await harness.flush()
    path = harness.write_file(
        str(tmp_path / "notes.json"), foundry_spells_key_export()
    )
    harness.pick_file(harness.monkeypatch, path)

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "information"
    assert box.title == DD_GRIMOIRES_IMPORT_TITLE
    assert "Заметки о заклинаниях" in box.text
    assert "импортирован в хранилище" in box.text
    assert "1 заклинание" in box.text
    assert "Предупреждения" not in box.text
    # список перезагружен: новая полка уже в таблице
    assert len(harness.sheet._row_ids) == 3


async def test_import_warnings_accompany_the_import(qtbot, harness, tmp_path):
    """Предупреждения не мешают импорту и печатаются в отчёте (спека)."""
    harness.open()
    await harness.flush()
    path = harness.write_file(
        str(tmp_path / "world.json"), foundry_item_list_export()
    )
    harness.pick_file(harness.monkeypatch, path)

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "information"
    assert "Предупреждения" in box.text
    assert "уже занят" in box.text
    assert len(harness.storage.list_grimoires()) == 3


async def test_import_refused_shows_report_and_touches_nothing(
    qtbot, harness, tmp_path
):
    """Отчёт с ошибкой — импорт отклонён, полки не появились."""
    harness.open()
    await harness.flush()
    path = harness.write_file(str(tmp_path / "empty.json"), [])
    harness.pick_file(harness.monkeypatch, path)

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "warning"
    assert "Импорт отклонён" in box.text
    assert "в файле нет ни одного заклинания" in box.text
    assert len(harness.storage.list_grimoires()) == 2
    assert harness.sheet._row_ids == [SINGLE_ID, TINA_ID]


async def test_import_invalid_id_reports_the_sentence(qtbot, harness, tmp_path):
    """«Идентификатор … не может именем файла» — своей фразой сервиса,
    хранилище не тронуто."""
    harness.open()
    await harness.flush()
    doc = {
        "id": "Гримуар Тины",
        "name": "Гримуар Тины",
        "items": foundry_compendium_export()["items"],
    }
    path = harness.write_file(str(tmp_path / "bad.json"), doc)
    harness.pick_file(harness.monkeypatch, path)

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "warning"
    assert "не может именем файла" in box.text
    assert len(harness.storage.list_grimoires()) == 2


async def test_replacement_no_changes_nothing(qtbot, harness, tmp_path):
    """Спека «Замена подтверждается»: файл уже на полке — вопрос; ответ
    Ничего не меняет — байты прежние, новых боксов нет."""
    harness.open()
    await harness.flush()
    path = harness.write_file(str(tmp_path / "spell.json"), foundry_single_item_export())
    harness.pick_file(harness.monkeypatch, path)
    before = harness.storage.load_content(SINGLE_ID)

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()
    ask = harness.last_box()
    assert ask.icon == "question"
    assert ask.title == DD_GRIMOIRES_CONFIRM_TITLE
    assert "заменить" in ask.text
    _answer(ask, "No")
    await harness.flush()

    assert harness.storage.load_content(SINGLE_ID) == before
    assert harness.last_box() is ask  # после «Нет» boxes молчит


async def test_replacement_yes_overwrites_and_reports(qtbot, harness, tmp_path):
    """«Да» шлёт ТЕ ЖЕ байты с подтверждением: полка заменена, бокс «заменён»."""
    harness.open()
    await harness.flush()
    path = harness.write_file(str(tmp_path / "spell.json"), foundry_single_item_export())
    harness.pick_file(harness.monkeypatch, path)

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()
    ask = harness.last_box()
    _answer(ask, "Yes")
    await harness.flush()

    box = harness.last_box()
    assert box is not ask
    assert "заменён в хранилище" in box.text
    assert harness.storage.load_content(SINGLE_ID) is not None


async def test_unreadable_file_says_why(qtbot, harness):
    """Нечитаемый файл — бокс с причиной, импортер не тронут, полки прежние."""
    harness.open()
    await harness.flush()
    harness.pick_file(harness.monkeypatch, str(Path("nowhere") / "missing.json"))

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "warning"
    assert "Не удалось прочитать файл" in box.text
    assert len(harness.storage.list_grimoires()) == 2


async def test_cancelled_pick_is_a_noop(qtbot, harness, monkeypatch):
    """Отмена выбора файла — никаких боксов и никакого хранилища."""
    harness.open()
    await harness.flush()
    monkeypatch.setattr(
        "app.dd.presentation.grimoires_sheet.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )

    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    assert harness.boxes == []


async def test_import_crash_prints_the_generic_body(qtbot, harness, tmp_path):
    """Падение импортера — общая русская фраза, молчание запрещено (Д3)."""
    harness.open()
    await harness.flush()
    path = harness.write_file(str(tmp_path / "spell.json"), foundry_single_item_export())
    harness.pick_file(harness.monkeypatch, path)

    def _boom(*args, **kwargs):
        raise RuntimeError("внутренняя поломка")

    harness.monkeypatch.setattr(harness.importer, "import_grimoire", _boom)
    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "warning"
    assert box.text == DD_GRIMOIRES_IMPORT_UNEXPECTED_BODY


# ── отказы сессии ─────────────────────────────────────────────────────────────


async def test_frame_load_failure_surfaces(qtbot, harness, monkeypatch):
    """Провал загрузки рамок — русская причина в боксе, лист жив."""

    async def _boom():
        raise RuntimeError("БД лежит")

    monkeypatch.setattr(harness.connections, "statuses", _boom)
    sheet = harness.sheet
    harness.wiring.open_sheet(sheet)
    sheet.request_refresh()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "warning"
    assert "Не удалось загрузить список гримуаров" in box.text


async def test_toggle_write_failure_surfaces(qtbot, harness, monkeypatch):
    """Провал записи подключения — бокс с причиной (молчание запрещено)."""
    harness.open()
    await harness.flush()

    async def _boom(grimoire_id):
        raise RuntimeError("запись не прошла")

    monkeypatch.setattr(harness.connections, "connect", _boom)
    harness.check_box(SINGLE_ID).click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == "warning"
    assert "Не удалось изменить подключение гримуара" in box.text


# ── отмена при закрытии (PR-037, виджет-издание) ─────────────────────────────


async def test_close_cancels_inflight_toggle(qtbot, harness):
    """Закрытие листа убивает незавершённую потоковую задачу; её done-
    коллбэк не боксит в закрытый лист."""
    harness.open()
    await harness.flush()
    gate = asyncio.Event()
    real_connect = harness.connections.connect

    async def _slow_connect(grimoire_id):
        await gate.wait()
        await real_connect(grimoire_id)

    harness.connections.connect = _slow_connect

    harness.check_box(SINGLE_ID).click()
    await asyncio.sleep(0.01)
    in_flight = [task for task in harness.tasks if not task.done()]
    assert in_flight

    harness.sheet.close()
    # cancel() помечает запрос; переход задачи в cancelled виден после
    # прохода цикла — как и в датасет-источнике этого контура.
    await asyncio.sleep(0.01)
    assert all(task.cancelled() or task.done() for task in in_flight)
    gate.set()
    await asyncio.sleep(0.01)
    assert harness.boxes == []  # закрытый лист молчит


async def test_close_while_frame_load_pending_is_silent(qtbot, harness, monkeypatch):
    """Рамочная половина PR-037: снятая задача загрузки рамки молча выходит
    на task.cancelled() — закрытый лист не боксит и не красит рамку."""
    gate = asyncio.Event()
    real_statuses = harness.connections.statuses

    async def _slow_statuses():
        await gate.wait()
        return await real_statuses()

    monkeypatch.setattr(harness.connections, "statuses", _slow_statuses)
    sheet = harness.sheet
    harness.wiring.open_sheet(sheet)
    sheet.request_refresh()
    await asyncio.sleep(0.01)
    pending = [task for task in harness.tasks if not task.done()]
    assert pending

    sheet.close()
    gate.set()
    await asyncio.sleep(0.02)

    assert all(task.cancelled() for task in pending)
    assert sheet._statuses is None  # рамка не пришла — и не придёт в закрытый лист
    assert harness.boxes == []  # закрытый лист молчит


async def test_answered_notice_releases_its_ref(qtbot, harness):
    """Notice-бокс, закрытый мастером, отпускает живую ссылку листа
    (finished-канал); иначе последний бокс держался бы до конца листа."""
    harness.open()
    await harness.flush()
    harness.pick_file(harness.monkeypatch, str(Path("nowhere") / "missing.json"))
    harness.sheet.findChild(QPushButton, "ddGrimoireImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert harness.sheet._notice_box is box

    _answer(box, "Ok")
    assert harness.sheet._notice_box is None


# ── сценарий спека: «подключил из списка — заклинания видно» ─────────────────


async def test_connected_grimoire_spells_answer_the_reference_search(
    qtbot, harness, tmp_path
):
    """Настоящие индекс и справочный источник (та же сборка, что в main.py):
    подключение чекбоксом листа видно поиску БЕЗ перезапуска — индекс
    сверяется на каждом асинхронном чтении."""
    dataset_storage = DatasetStorage(tmp_path / "datasets")
    dataset_connections = DatasetConnectionsService(harness.uow, dataset_storage)
    index = DatasetIndexService(dataset_connections, dataset_storage)
    source = DndReferenceSource(
        index,
        ReferenceVisibilityService(harness.uow),
        grimoire_index=GrimoireIndexService(
            harness.connections, harness.storage
        ),
    )
    harness.open()
    await harness.flush()
    assert await source.search("лунный") == ()  # до подключения — пусто

    harness.check_box(TINA_ID).click()
    await harness.flush()

    hits = await source.search("лунный")
    assert hits, "подключённый гримуар не ответил справочному поиску"
    hit = hits[0]
    assert hit.key == "dd_spell"
    assert hit.origin == "Гримуар Тины"


# ── фасад: пункт меню, одиночный экземпляр, detach ───────────────────────────


async def test_module_grimoires_entry_single_instance_and_detach(qtbot, uow, tmp_path):
    """«Гримуары…» печатается только с полным trio; повторный выбор поднимает
    живой лист; detach снимает лист и гасит пункт вместе с меню."""
    from PySide6.QtWidgets import QMainWindow, QMenu

    from app.dd.module import DndModule

    # фаза 1: без trio — мёртвый пункт не печатается, случайный зов молчит
    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    module = DndModule()
    module._on_grimoires_requested()  # ни окна, ни коннектора — тихо
    assert module._grimoires_sheet is None
    module.attach(window, _make_wiring(window))
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        names = [action.objectName() for action in menu.actions()]
        assert "ddGrimoiresAction" not in names
        module._on_grimoires_requested()
        assert module._grimoires_sheet is None
    finally:
        module.detach()

    # фаза 2: trio собрано — пункт есть, лист один, detach его снимает
    storage = _seed_storage(tmp_path)
    module = DndModule(
        grimoire_storage=storage,
        grimoire_connections=GrimoireConnectionsService(uow, storage),
        grimoire_import=GrimoireImportService(storage),
    )
    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    wiring = _make_wiring(window)
    module.attach(window, wiring)
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        action = next(
            a for a in menu.actions() if a.objectName() == "ddGrimoiresAction"
        )
        assert action.text() == "Гримуары…"
        action.trigger()
        sheet = module._grimoires_sheet
        assert isinstance(sheet, DndGrimoiresSheet)
        for _ in range(40):
            await asyncio.sleep(0.005)
            if sheet._statuses is not None:
                break
        assert sheet._row_ids == [SINGLE_ID, TINA_ID]
        action.trigger()  # повторный выбор — тот же живой лист
        assert module._grimoires_sheet is sheet
    finally:
        module.detach()
    assert module._grimoires_sheet is None
    assert not sheet.isVisible()


async def test_module_forgets_grimoires_sheet_after_master_close(qtbot, uow, tmp_path):
    """Мастер закрывает лист сам (не через detach): finished-канал фасада
    гасит ссылку, пока этот лист ещё резидент, отпускает шлюз меню, и
    следующий выбор собирает свежий лист."""
    from PySide6.QtWidgets import QMainWindow, QMenu

    from app.dd.module import DndModule

    storage = _seed_storage(tmp_path)
    module = DndModule(
        grimoire_storage=storage,
        grimoire_connections=GrimoireConnectionsService(uow, storage),
        grimoire_import=GrimoireImportService(storage),
    )
    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    wiring = _make_wiring(window)
    states: list[bool] = []
    wiring.sheet_stack_changed.connect(states.append)
    module.attach(window, wiring)
    try:
        menu = window.findChild(QMenu, "ddModuleMenu")
        action = next(
            a for a in menu.actions() if a.objectName() == "ddGrimoiresAction"
        )
        action.trigger()
        sheet = module._grimoires_sheet
        assert isinstance(sheet, DndGrimoiresSheet)
        for _ in range(40):
            await asyncio.sleep(0.005)
            if sheet._statuses is not None:
                break
        assert states == [True]

        sheet.findChild(QPushButton, "sheetFrameCloseButton").click()

        assert not sheet.isVisible()
        assert module._grimoires_sheet is None  # ветка «этот лист ещё резидент»
        assert states == [True, False]

        action.trigger()  # ссылка отпущена честно — собирается свежий лист
        fresh = module._grimoires_sheet
        assert isinstance(fresh, DndGrimoiresSheet) and fresh is not sheet
        for _ in range(40):
            await asyncio.sleep(0.005)
            if fresh._statuses is not None:
                break
        assert fresh._row_ids == [SINGLE_ID, TINA_ID]
    finally:
        module.detach()
    assert module._grimoires_sheet is None


# ── чистая функция и кожа (рамочные ветки размеров и отчёта) ─────────────────


def test_spell_phrase_russian_plural_forms():
    """Все три ветки русской плюрализации счётчика импорта: 0/5-9/10-14 →
    «заклинаний», 1 (но не 11) → «заклинание», остальные → «заклинания»."""
    assert _spell_phrase(1) == "1 заклинание"
    assert _spell_phrase(21) == "21 заклинание"
    assert _spell_phrase(121) == "121 заклинание"
    assert _spell_phrase(2) == "2 заклинания"
    assert _spell_phrase(4) == "4 заклинания"
    assert _spell_phrase(24) == "24 заклинания"
    assert _spell_phrase(0) == "0 заклинаний"
    assert _spell_phrase(5) == "5 заклинаний"
    assert _spell_phrase(10) == "10 заклинаний"
    assert _spell_phrase(11) == "11 заклинаний"
    assert _spell_phrase(14) == "14 заклинаний"
    assert _spell_phrase(111) == "111 заклинаний"


def test_sheet_skins_margins_from_the_loaded_tokens(qtbot, tmp_path):
    """Токен-ветка размеров: на настоящей теме поля берут px из tokens.json
    (space.md/space.sm), а не фоллбэк-числа листа; контракт размеров при
    этом не меняется."""
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    theme = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file_path()
    )
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    sheet = DndGrimoiresSheet(
        storage=_seed_storage(tmp_path),
        connections=SimpleNamespace(),  # type: ignore[arg-type]
        importer=SimpleNamespace(),  # type: ignore[arg-type]
        run_locked=lambda _coro: None,
        parent=window,
        theme=theme,
    )
    qtbot.addWidget(sheet)

    tokens = theme.tokens
    side = int(tokens["space.md"][theme.theme].removesuffix("px"))
    row = int(tokens["space.sm"][theme.theme].removesuffix("px"))
    content = sheet.findChild(QTableWidget, "ddGrimoireTable").parentWidget()
    margins = content.layout().contentsMargins()
    assert (margins.left(), margins.top()) == (side, row)
    assert sheet.size() == QSize(620, 520)
