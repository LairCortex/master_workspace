"""Лист «Датасеты D&D…» (add-dnd-module-foundation, tasks 5.1/5.2;
spec dnd-dataset-library «Экран датасетов», «Импорт пользовательского
датасета файлом», «Подключение наборов к игре», dnd-dataset-validator
«Порог импорта»).

Оффскрин-контур листа строится как в ``test_llm_setup_sheet.py``: хост-окно,
коннектор целиком (``open_sheet``/``run_locked``/стек — настоящие), а trio
библиотека+связи+импорт — настоящие поверх ``tmp_path``-хранилища и штатной
``uow``. Ловушка PR-010 стоит на ``app.dd.presentation.datasets_sheet.QMessageBox``:
каждый ответ потока — modeless ``show()``; ловушка сверяет тексты и эмитит
``finished`` сама. Файловый выбор — подмена ``getOpenFileName`` (выбор сам —
системное всплывающее окно, фиксированный класс-исключение контракта окон).

Покрыты: контракт листа (заголовок = windowTitle, Qt.Sheet без Qt-модальности,
стек), таблица хранилища с состоянием проверки/источником, чекбокс
подключения по строке, строка-маркер пропавшего набора, кнопки SRD/Импорт/
Повторная проверка со всеми ветками спека, и отмена незавершённых задач при
закрытии (PR-037, виджет-издание).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QWidget,
)

from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_import_service import DatasetImportService
from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.domain.dataset import DatasetMeta, DatasetSource
from app.dd.domain.validation_report import (
    CheckIssue,
    Severity,
    ValidationReport,
)
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.presentation.datasets_sheet import (
    DD_DATASETS_SHEET_TITLE,
    DD_IMPORT_TITLE,
    DD_IMPORT_UNEXPECTED_BODY,
    DD_RECHECK_GHOST_BODY,
    DD_RECHECK_NO_CHOICE_BODY,
    DD_SRD_TITLE,
    DD_SRD_UNEXPECTED_BODY,
    DndDatasetsSheet,
    report_lines,
)
from app.presentation.wiring import ApplicationWiring
from tests.dd.lss_check_fixtures import base_dataset, class_with
from tests.test_application_settings_errors import _install_modal_trap

_SHELF_ROOT = "datasets"


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


def _seed_storage(tmp_path) -> DatasetStorage:
    """Две полки: служебный SRD без отметки проверки и домашний набор с
    двумя ошибками последней проверки и битой лицензией в самих байтах."""
    storage = DatasetStorage(tmp_path / _SHELF_ROOT)
    storage.save(
        "srd51",
        json.dumps(base_dataset(id="srd51"), ensure_ascii=False),
        DatasetMeta(
            source=DatasetSource.SRD, imported_at="2026-10-01", sha256="0" * 64
        ),
    )
    storage.save(
        "my-pack",
        json.dumps(
            base_dataset(id="my-pack", license="Public Domain"), ensure_ascii=False
        ),
        DatasetMeta(
            source=DatasetSource.HOMEBREW,
            imported_at="2026-10-02",
            sha256="1" * 64,
            check_errors=2,
        ),
    )
    return storage


class _SheetHarness:
    """Окно + коннектор + сервисное trio + сам лист, уже на стеке."""

    def __init__(self, qtbot, uow, tmp_path, monkeypatch):
        self.window = QWidget()
        qtbot.addWidget(self.window)
        self.window.show()
        self.wiring = _make_wiring(self.window)
        self.states: list[bool] = []
        self.wiring.sheet_stack_changed.connect(self.states.append)
        self.storage = _seed_storage(tmp_path)
        self.connections = DatasetConnectionsService(uow, self.storage)
        self.library = DatasetLibraryService(
            self.storage, SimpleNamespace()  # тип-обманка: сеть не нужна
        )
        self.importer = DatasetImportService(
            self.library, self.connections, DatasetValidatorService(), self.storage
        )
        self.boxes = _install_modal_trap(
            monkeypatch, "app.dd.presentation.datasets_sheet.QMessageBox"
        )
        # Каждая задача потока — ещё и сюда: тесты ждут их завершения.
        self.tasks: list[asyncio.Task] = []

        def _run_locked(coro):
            task = self.wiring.run_locked(coro)
            self.tasks.append(task)
            return task

        self.sheet = DndDatasetsSheet(
            library=self.library,
            connections=self.connections,
            importer=self.importer,
            run_locked=_run_locked,
            parent=self.window,
            theme=None,
        )
        qtbot.addWidget(self.sheet)

    def open(self) -> DndDatasetsSheet:
        self.wiring.open_sheet(self.sheet)
        self.sheet.request_refresh()
        return self.sheet

    async def flush(self, rounds: int = 60) -> None:
        """Крутим цикл до тишины: потоковые шаги ходят в aiosqlite-потоки,
        которым нужны настоящие проходы цикла (sleep(0) тут не доводчик);
        три тихих раунда подряд — тишина наступила. Незавершённая задача
        (тест отмены) не вешает тест: раунды считаны."""
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
        return self.sheet.findChild(QTableWidget, "ddDatasetTable")

    def row_of(self, dataset_id: str) -> int:
        return self.sheet._row_ids.index(dataset_id)

    def check_box(self, dataset_id: str) -> QCheckBox:
        holder = self.table.cellWidget(self.row_of(dataset_id), 3)
        return holder.findChild(QCheckBox)

    def last_box(self):
        assert self.boxes, "ни одного boxes-окна не показано"
        return self.boxes[-1]

    def pick_file(self, monkeypatch, path: str) -> None:
        monkeypatch.setattr(
            "app.dd.presentation.datasets_sheet.QFileDialog.getOpenFileName",
            lambda *args, **kwargs: (path, ""),
        )


@pytest.fixture
async def harness(qtbot, uow, tmp_path, monkeypatch):
    harness = _SheetHarness(qtbot, uow, tmp_path, monkeypatch)
    yield harness
    # Разбор: закрытие снимает незавершённые потоки (done()), затем их
    # добиваем здесь — задача не должна прийти к уже утилизированной БД.
    harness.sheet.close()
    for task in list(harness.tasks):
        if not task.done():
            task.cancel()
    await asyncio.gather(*harness.tasks, return_exceptions=True)
    for _ in range(4):
        await asyncio.sleep(0.005)


def _answer(box, button_name: str) -> None:
    """Эмит «ответа» сигналом finished — как настоящая кнопка своей ловушки."""
    for handler in box.finished.handlers:
        handler(getattr(box.StandardButton, button_name))


def _button(sheet: DndDatasetsSheet, object_name: str) -> QPushButton:
    return sheet.findChild(QPushButton, object_name)


# ── лист и его контракт (5.2) ────────────────────────────────────────────────


async def test_sheet_rides_the_open_sheet_contract(qtbot, harness):
    """Спека оконного контракта: заголовок шапки = windowTitle = пункт меню,
   Attached-лист Qt.Sheet БЕЗ Qt-модальности (PR-012), дефолт 680×560, стек
    поднимается открытием и отпускается закрытием «Закрыть»."""
    sheet = harness.open()
    await harness.flush()

    assert sheet.windowTitle() == DD_DATASETS_SHEET_TITLE
    assert sheet.findChild(QLabel, "sheetFrameTitle").text() == DD_DATASETS_SHEET_TITLE
    assert sheet.size() == QSize(680, 560)
    assert sheet.windowFlags() & Qt.WindowType.Sheet
    assert sheet.windowModality() == Qt.WindowModality.NonModal
    assert sheet.isVisible()
    assert harness.states == [True]

    sheet.findChild(QPushButton, "sheetFrameCloseButton").click()
    assert not sheet.isVisible()
    assert harness.states == [True, False]
    assert sheet.result() == sheet.DialogCode.Rejected


async def test_storage_table_shows_state_source_and_missing_marker(
    qtbot, harness
):
    """Спека «Список хранилища… с состоянием проверки и источником» +
    «Пропавший набор помечен»: две полки с их состоянием, подключённый
    призрак отдельной строкой и строкой-маркером, чекбоксы названы делом."""
    await harness.connections.connect("my-pack")
    await harness.connections.connect("ghost-set")  # полки нет — призрак
    harness.open()
    await harness.flush()

    table = harness.table
    assert harness.sheet._row_ids == ["my-pack", "srd51", "ghost-set"]
    assert table.item(0, 1).text() == "импортированный"
    assert table.item(0, 2).text() == "ошибок: 2"
    assert table.item(1, 1).text() == "SRD"
    assert table.item(1, 2).text() == "не проверялся"
    # Призрак: имя строки говорит об отсутствии, источник/проверка — прочерк.
    assert "набор отсутствует в хранилище" in table.item(2, 0).text()
    assert table.item(2, 1).text() == "—"
    marker = harness.sheet.findChild(QLabel, "ddMissingDatasetsLabel")
    assert marker.isVisible() and "ghost-set" in marker.text()

    connected_box = harness.check_box("my-pack")
    assert connected_box.isChecked()
    assert connected_box.accessibleName() == "Отключить набор от игры"
    assert not harness.check_box("srd51").isChecked()
    assert harness.check_box("srd51").accessibleName() == "Подключить набор к игре"


async def test_connect_checkbox_writes_link_disconnect_keeps_file(
    qtbot, harness
):
    """Спека «Подключение наборов к игре»: чекбокс строки пишет ссылку,
    снятие убирает ТОЛЬКО ссылку — файл остаётся на полке."""
    harness.open()
    await harness.flush()

    harness.check_box("srd51").click()
    await harness.flush()
    assert await harness.connections.connections() == ["srd51"]
    assert harness.check_box("srd51").isChecked()

    harness.check_box("srd51").click()
    await harness.flush()
    assert await harness.connections.connections() == []
    assert not harness.check_box("srd51").isChecked()
    assert harness.storage.load_content("srd51") is not None  # файл жив


async def test_connection_failure_reports_russian_reason(qtbot, harness):
    """Принцип 3: сбой записи связи доходит до читателя с причиной."""

    async def _boom(_dataset_id):
        raise RuntimeError("база закрыта")

    harness.open()
    await harness.flush()
    harness.connections.connect = _boom  # type: ignore[method-assign]

    harness.check_box("srd51").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == box.Icon.Warning
    assert "база закрыта" in box.text


async def test_frame_load_failure_reports_russian_reason(qtbot, harness):
    async def _boom():
        raise RuntimeError("нет чтения")

    harness.connections.statuses = _boom  # type: ignore[method-assign]
    harness.wiring.open_sheet(harness.sheet)
    harness.sheet.request_refresh()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == box.Icon.Warning
    assert "нет чтения" in box.text


# ── кнопка SRD (5.2: «Загрузить SRD» — повтор идемпотентного бутстрапа) ──────


async def test_srd_button_prints_the_answer_even_when_quiet(
    qtbot, harness, monkeypatch
):
    """Ручной запуск отвечает всегда (спека dnd-dataset-downloader «Успех и
    каждая ошибка выводятся пользователю по-русски»), даже когда система
    отвечает «уже есть, сеть не тронута»; после успеха список обновляется."""
    harness.open()
    await harness.flush()

    async def _already():
        return SimpleNamespace(ok=True, all_present=True, summary="Оба набора уже на месте.")

    monkeypatch.setattr(
        harness.library, "download_official_datasets", _already
    )
    _button(harness.sheet, "ddSrdButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.title == DD_SRD_TITLE
    assert box.text == "Оба набора уже на месте."
    assert box.icon == box.Icon.Information


async def test_srd_button_failure_and_crash_both_answer(qtbot, harness, monkeypatch):
    """Неудачная выгрузка — предупреждение с итогом сервиса; падение задачи —
    общий русский текст с обещанием повтора той же кнопкой."""
    harness.open()
    await harness.flush()

    async def _failed():
        return SimpleNamespace(ok=False, all_present=False, summary="SRD 5.1: сеть недоступна.")

    monkeypatch.setattr(harness.library, "download_official_datasets", _failed)
    _button(harness.sheet, "ddSrdButton").click()
    await harness.flush()
    failed = harness.last_box()
    assert failed.icon == failed.Icon.Warning
    assert "сеть недоступна" in failed.text

    async def _crash():
        raise RuntimeError("взрыв")

    monkeypatch.setattr(harness.library, "download_official_datasets", _crash)
    _button(harness.sheet, "ddSrdButton").click()
    await harness.flush()
    crash = harness.last_box()
    assert crash.text == DD_SRD_UNEXPECTED_BODY


async def test_srd_re_run_result_box_is_nonmodal(qtbot, harness, monkeypatch):
    """fix-dnd-followups Д1 (notes.md 2.1 «тот же дефект с той же причиной»):
    бокс результата кнопки «Загрузить SRD» — parent сам лист — по умолчанию
    ApplicationModal и перехватывал Esc на себя. Дельта dnd-dataset-library:
    «Уведомление результата SHALL быть необязывающим: открытое окно не
    удерживает остальные окна и листы». Пин настоящим классом (ловушка
    сверяет тексты, модалность — свойство Qt): бокс сводки носит NonModal,
    как фасадный ``_show_datasets_box`` (поза PR-012)."""
    harness.open()
    await harness.flush()
    # Ловушка уступает настоящему боксу: модалность живёт только в Qt.
    monkeypatch.setattr(
        "app.dd.presentation.datasets_sheet.QMessageBox", QMessageBox
    )

    async def _failed():
        return SimpleNamespace(
            ok=False, all_present=False, summary="SRD 5.1: сеть недоступна."
        )

    monkeypatch.setattr(harness.library, "download_official_datasets", _failed)
    _button(harness.sheet, "ddSrdButton").click()
    await harness.flush()

    box = harness.sheet._notice_box  # noqa: SLF001 - пин окна уведомления
    assert isinstance(box, QMessageBox) and box.isVisible()
    qtbot.addWidget(box)
    assert box.windowModality() == Qt.WindowModality.NonModal
    assert box.text() == "SRD 5.1: сеть недоступна."
    box.done(QMessageBox.StandardButton.Ok)


def test_srd_button_without_running_loop_is_quiet(qtbot):
    """Вне крутящегося цикла (оффскрин-проба без qasync) кнопка ничего не
    заводит и не падает — следующая попытка пройдёт тем же путём. Фоновый
    поток — единственный способ позвать обработчик вне цикла теста."""
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    library = SimpleNamespace(
        list_storage=lambda: [], download_official_datasets=None
    )
    sheet = DndDatasetsSheet(
        library=library,  # type: ignore[arg-type]
        connections=None,  # type: ignore[arg-type]
        importer=None,  # type: ignore[arg-type]
        run_locked=lambda _coro: None,
        parent=window,
        theme=None,
    )
    qtbot.addWidget(sheet)

    import threading

    worker = threading.Thread(target=sheet._on_srd_clicked)
    worker.start()
    worker.join(5)
    assert sheet._tasks == set()


# ── импорт файла (5.1) ───────────────────────────────────────────────────────


async def test_import_clean_shelves_prints_success_and_repaints(
    qtbot, harness, monkeypatch, tmp_path
):
    path = tmp_path / "homebrew.json"
    path.write_text(json.dumps(base_dataset(id="hb-set"), ensure_ascii=False), "utf-8")
    harness.open()
    await harness.flush()
    harness.pick_file(monkeypatch, str(path))

    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == box.Icon.Information
    assert "импортирован в хранилище" in box.text
    # «ОК» закрытого окна отпускает live-ссылку PR-010 (finished-канал).
    assert harness.sheet._notice_box is box
    for handler in box.finished.handlers:
        handler(0)
    assert harness.sheet._notice_box is None
    await harness.flush()
    assert "hb-set" in harness.sheet._row_ids
    row = harness.row_of("hb-set")
    assert harness.table.item(row, 1).text() == "импортированный"
    assert harness.table.item(row, 2).text() == "ошибок: 0"


async def test_import_with_warnings_imports_and_lists_them(
    qtbot, harness, monkeypatch, tmp_path
):
    """Спека «Импорт с предупреждениями»: файл импортирован, предупреждения
    прочитаны в том же окне."""
    path = tmp_path / "warned.json"
    path.write_text(
        json.dumps(
            base_dataset(id="hb-set", classes=[class_with({"type": "gold-dice", "dice": "2d"})]),
            ensure_ascii=False,
        ),
        "utf-8",
    )
    harness.open()
    await harness.flush()
    harness.pick_file(monkeypatch, str(path))

    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert "Предупреждения" in box.text
    assert harness.storage.load_content("hb-set") is not None


async def test_import_errors_refuse_with_report_storage_untouched(
    qtbot, harness, monkeypatch, tmp_path
):
    """Спека «Отказ с ошибками — хранилище не меняется»: отчёт проверки —
    текст отказа, на полке пусто, чужие полки целы."""
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(base_dataset(id="hb-set", license="Public Domain")), "utf-8"
    )
    harness.open()
    await harness.flush()
    harness.pick_file(monkeypatch, str(path))
    before = harness.storage.load_content("my-pack")

    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.title == DD_IMPORT_TITLE
    assert box.icon == box.Icon.Warning
    assert "Импорт отклонён" in box.text
    assert harness.storage.load_content("hb-set") is None
    assert harness.storage.load_content("my-pack") == before


async def test_import_replacement_no_keeps_bytes_yes_replaces(
    qtbot, harness, monkeypatch, tmp_path
):
    """Спека «заменять только после подтверждения»: вопрос с тем же заголовком
    id; «Нет» — бездействие, «Да» — замена тех же байт и ответ «заменён»."""
    first = tmp_path / "first.json"
    first.write_text(json.dumps(base_dataset(id="hb-set")), "utf-8")
    second = tmp_path / "second.json"
    second.write_text(
        json.dumps(base_dataset(id="hb-set", author="другой")), "utf-8"
    )
    harness.open()
    await harness.flush()

    harness.pick_file(monkeypatch, str(first))
    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()
    harness.pick_file(monkeypatch, str(second))
    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()

    ask = harness.last_box()
    assert ask.icon == ask.Icon.Question
    assert ask.buttons is not ask.StandardButton.Ok  # Да|Нет
    _answer(ask, "No")
    await harness.flush()
    assert harness.storage.load_content("hb-set") == first.read_text("utf-8")

    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()
    _answer(harness.last_box(), "Yes")
    await harness.flush()
    assert harness.storage.load_content("hb-set") == second.read_text("utf-8")
    done = harness.last_box()
    assert "заменён" in done.text


async def test_import_srd_shelf_refused_by_its_own_sentence(
    qtbot, harness, monkeypatch, tmp_path
):
    """SRD-полка: не отчёт проверки, а магазинная фраза защиты; байты те же."""
    path = tmp_path / "onto-srd.json"
    path.write_text(json.dumps(base_dataset(id="srd51")), "utf-8")
    harness.open()
    await harness.flush()
    harness.pick_file(monkeypatch, str(path))

    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()

    box = harness.last_box()
    assert box.icon == box.Icon.Warning
    assert "защищён от замены" in box.text


async def test_import_unreadable_file_says_why_and_unparsable_is_refused(
    qtbot, harness, monkeypatch, tmp_path
):
    harness.open()
    await harness.flush()
    some_dir = tmp_path / "не-файл"
    some_dir.mkdir()
    harness.pick_file(monkeypatch, str(some_dir))
    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()
    box = harness.last_box()
    assert "Не удалось прочитать файл" in box.text

    broken = tmp_path / "broken.json"
    broken.write_text("{битый", "utf-8")
    harness.pick_file(monkeypatch, str(broken))
    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()
    refused = harness.last_box()
    assert "Импорт отклонён" in refused.text


async def test_import_cancelled_pick_is_nothing(qtbot, harness, monkeypatch):
    harness.open()
    await harness.flush()
    harness.pick_file(monkeypatch, "")
    before = [t for t in harness.tasks]

    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()
    assert harness.boxes == []
    assert harness.tasks == before  # к потоку не подходили


async def test_import_crash_reports_generic_russian_body(
    qtbot, harness, monkeypatch, tmp_path
):
    path = tmp_path / "any.json"
    path.write_text(json.dumps(base_dataset()), "utf-8")
    harness.open()
    await harness.flush()
    harness.pick_file(monkeypatch, str(path))

    async def _crash(*args, **kwargs):
        raise RuntimeError("диск кончился")

    monkeypatch.setattr(harness.importer, "import_dataset", _crash)
    _button(harness.sheet, "ddImportButton").click()
    await harness.flush()
    assert harness.last_box().text == DD_IMPORT_UNEXPECTED_BODY


# ── повторная проверка (5.2) ─────────────────────────────────────────────────


async def test_recheck_reports_clean_warning_and_error_shelves(
    qtbot, harness, monkeypatch, tmp_path
):
    """Кнопка проверяет выбранный набор и печатает вердикт; сайдкар получает
    свежий счётчик (у my-pack было «ошибок: 2», проверка нашла одну)."""
    harness.open()
    await harness.flush()

    # Ошибочная полка: LICENSE в байтах, сайдкар обновляется на 1.
    harness.table.selectRow(harness.row_of("my-pack"))
    _button(harness.sheet, "ddRecheckButton").click()
    await harness.flush()
    box = harness.last_box()
    assert box.icon == box.Icon.Warning
    assert "Проверка нашла ошибки" in box.text
    await harness.flush()
    assert harness.storage.load_meta("my-pack").check_errors == 1  # type: ignore[union-attr]
    assert harness.table.item(harness.row_of("my-pack"), 2).text() == "ошибок: 1"

    # Чистая полка — «ошибок и предупреждений нет».
    harness.table.selectRow(harness.row_of("srd51"))
    _button(harness.sheet, "ddRecheckButton").click()
    await harness.flush()
    clean = harness.last_box()
    assert clean.icon == clean.Icon.Information
    assert "Ошибок и предупреждений нет." in clean.text

    # Полка с одним предупреждением — «Ошибок нет. Предупреждения: …».
    harness.storage.save(
        "warned-pack",
        json.dumps(
            base_dataset(id="warned-pack", classes=[class_with({"type": "gold-dice", "dice": "2d"})]),
            ensure_ascii=False,
        ),
        DatasetMeta(
            source=DatasetSource.HOMEBREW,
            imported_at="2026-10-03",
            sha256="2" * 64,
        ),
    )
    harness.sheet.request_refresh()
    await harness.flush()
    harness.table.selectRow(harness.row_of("warned-pack"))
    _button(harness.sheet, "ddRecheckButton").click()
    await harness.flush()
    warned = harness.last_box()
    assert warned.icon == warned.Icon.Information
    assert "Ошибок нет. Предупреждения" in warned.text


async def test_recheck_without_choice_and_for_ghost_says_choose(
    qtbot, harness
):
    """Ни строки не выбрано и призрак выбран — один и тот же вежливый ответ:
    проверка только для выбранного набора хранилища."""
    await harness.connections.connect("ghost-set")
    harness.open()
    await harness.flush()

    _button(harness.sheet, "ddRecheckButton").click()  # selection none
    box = harness.last_box()
    assert box.text == DD_RECHECK_NO_CHOICE_BODY

    harness.table.selectRow(harness.row_of("ghost-set"))
    _button(harness.sheet, "ddRecheckButton").click()
    await harness.flush()
    assert harness.boxes[-1].text == DD_RECHECK_NO_CHOICE_BODY


async def test_recheck_ghost_and_crash_answer(qtbot, harness, monkeypatch):
    """Полка исчезла между кликом и чтением — честное «проверять нечего» и
    обновлённый список; падение проверки — причина читателю."""
    harness.open()
    await harness.flush()

    async def _gone(_dataset_id):
        return None

    monkeypatch.setattr(harness.importer, "recheck", _gone)
    harness.table.selectRow(harness.row_of("srd51"))
    _button(harness.sheet, "ddRecheckButton").click()
    await harness.flush()
    assert harness.last_box().text == DD_RECHECK_GHOST_BODY

    async def _crash(_dataset_id):
        raise RuntimeError("диск")

    monkeypatch.setattr(harness.importer, "recheck", _crash)
    harness.table.selectRow(harness.row_of("srd51"))
    _button(harness.sheet, "ddRecheckButton").click()
    await harness.flush()
    assert "диск" in harness.last_box().text


# ── закрытие убивает потоки (PR-037, виджет-издание) ─────────────────────────


async def test_closing_the_sheet_cancels_in_flight_tasks(qtbot, harness):
    """Закрытый лист не дорисовывает себя после потоков: незавершённая задача
    снимается в ``done``, множество задач пусто, стек отпущен."""
    release = asyncio.Event()

    async def _slow():
        await release.wait()
        return []

    harness.connections.statuses = _slow  # type: ignore[method-assign]
    harness.wiring.open_sheet(harness.sheet)
    harness.sheet.request_refresh()
    await harness.flush()  # задача успевает стартовать и сесть на event
    assert harness.tasks and not harness.tasks[0].done()

    harness.sheet.close()
    await harness.flush()
    assert harness.tasks[0].cancelled()
    assert harness.sheet._tasks == set()
    assert harness.states == [True, False]


async def test_closing_cancels_every_flow_and_no_callback_speaks(
    qtbot, harness, monkeypatch, tmp_path
):
    """Все четыре потока листа (связь, импорт, SRD, повторная проверка)
    снимаются закрытием молча: cancel-guard каждого done-колбэка — ни окна
    с ответом, ни дорисовки (PR-037, виджет-издание)."""
    release = asyncio.Event()

    async def _slow(*args, **kwargs):
        await release.wait()
        return SimpleNamespace(ok=True, all_present=False, summary="не дойдёт")

    harness.open()
    await harness.flush()
    monkeypatch.setattr(harness.connections, "connect", _slow)
    monkeypatch.setattr(harness.importer, "import_dataset", _slow)
    monkeypatch.setattr(harness.importer, "recheck", _slow)
    monkeypatch.setattr(harness.library, "download_official_datasets", _slow)
    path = tmp_path / "any.json"
    path.write_text(json.dumps(base_dataset()), "utf-8")
    harness.pick_file(monkeypatch, str(path))

    harness.check_box("srd51").click()  # связь
    _button(harness.sheet, "ddImportButton").click()  # импорт
    _button(harness.sheet, "ddSrdButton").click()  # SRD вне лока
    harness.table.selectRow(harness.row_of("srd51"))
    _button(harness.sheet, "ddRecheckButton").click()  # повторная проверка
    await harness.flush()
    pending = [task for task in harness.tasks if not task.done()]
    # Три запертых потока видно здесь; SRD живёт в собственном множестве
    # листа (вне лока) — его проверяем отдельно.
    assert len(pending) >= 3
    assert harness.sheet._tasks
    srd_pending = set(harness.sheet._tasks)
    boxes_before_close = len(harness.boxes)

    harness.sheet.close()
    await harness.flush()
    assert all(task.cancelled() for task in pending)
    assert all(task.cancelled() for task in srd_pending)
    assert harness.sheet._tasks == set()
    # ни один колбэк снятой задачи ничего не показал (тексты-приманки не
    # появились ни в одном окне); стек отпущен ровно на ноль.
    assert len(harness.boxes) == boxes_before_close
    assert harness.states == [True, False]


def test_sheet_skins_margins_from_the_loaded_tokens(qtbot, tmp_path):
    """Токен-ветка размеров: на настоящей теме поля берут px из tokens.json
    (space.md/space.sm), вне кожи — те же числа фоллбэком; лист строится в
    обоих случаях без единого отличия в контракте."""
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    theme = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file_path()
    )
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    storage = _seed_storage(tmp_path)
    sheet = DndDatasetsSheet(
        library=DatasetLibraryService(storage, SimpleNamespace()),  # type: ignore[arg-type]
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
    content = sheet.findChild(QTableWidget, "ddDatasetTable").parentWidget()
    margins = content.layout().contentsMargins()
    assert (margins.left(), margins.top()) == (side, row)
    assert sheet.size() == QSize(680, 560)


# ── чистая функция отчёта ────────────────────────────────────────────────────


def test_report_lines_caps_a_flood_with_honest_tail():
    issues = [
        CheckIssue(
            code="X",
            severity=Severity.ERROR,
            path=f"/{index}",
            message=f"текст {index}",
        )
        for index in range(15)
    ]
    lines = report_lines(ValidationReport.of(issues))
    assert len(lines) == 13  # 12 строк + честный хвост
    assert lines[0] == "/0 — текст 0"
    assert lines[-1] == "… и ещё 3"


# ── рубильник «справочные записи в поиске» (add-dnd-game-face, task 3.3) ────


class _RefHolderStub:
    """Держатель-обманка с настоящей парой дверей ReferenceVisibilityService."""

    def __init__(self, visible: bool = True, fail: bool = False) -> None:
        self.visible = visible
        self.fail = fail
        self.written: list[bool] = []

    async def set_visible(self, enabled: bool) -> None:
        self.written.append(enabled)
        if self.fail:
            raise RuntimeError("диск отказал")
        self.visible = enabled


def _ref_sheet(qtbot, holder, run_locked=None):
    """Лист с держателем поверх обманьего trio — рубильник живет своей жизнью
    и таблицы для проверки не требует."""
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    # Держатель на окно живёт столько же, сколько тест держит лист: окно —
    # C++-владелец QDialog (PySide6 убивает детей вместе с обёрткой родителя).
    sheet = DndDatasetsSheet(
        library=SimpleNamespace(list_storage=lambda: []),
        connections=None,  # type: ignore[arg-type]
        importer=None,  # type: ignore[arg-type]
        run_locked=run_locked or (lambda coro: asyncio.ensure_future(coro)),
        parent=window,
        theme=None,
        reference_visibility=holder,
    )
    qtbot.addWidget(sheet)
    sheet._keepalive_window = window
    return sheet


def _ref_box(sheet) -> QCheckBox:
    return sheet.findChild(QCheckBox, "ddReferenceSearchBox")


def test_toggle_absent_without_holder(qtbot):
    """Частичная композиция (профиль без модуля, юнит-сборки): чекбокса нет
    вовсе — лист не предлагает переключатель, которому некому подчиняться."""
    sheet = _ref_sheet(qtbot, holder=None)
    assert _ref_box(sheet) is None


def test_checkbox_mirrors_holder_state_from_first_pixel(qtbot):
    """Отражение с первого кадра: включённый держатель — тика, выключенный —
    нет; setChecked до connect — зеркало не притворяется кликом."""
    checked_sheet = _ref_sheet(qtbot, _RefHolderStub(visible=True))
    unchecked_sheet = _ref_sheet(qtbot, _RefHolderStub(visible=False))
    assert _ref_box(checked_sheet).isChecked() is True
    assert _ref_box(unchecked_sheet).isChecked() is False


async def test_checkbox_click_writes_through_the_holder(qtbot):
    """Клик — одна запись через держатель (принцип 3: транзакцию ведёт
    сервис), тика остаётся там, куда её поставил пользователь."""
    holder = _RefHolderStub(visible=True)
    sheet = _ref_sheet(qtbot, holder)
    box = _ref_box(sheet)

    box.click()
    for _ in range(50):
        await asyncio.sleep(0.005)
        if holder.written:
            break
    assert holder.written == [False]
    assert holder.visible is False
    assert box.isChecked() is False


async def test_failed_write_walks_the_tick_back(qtbot, monkeypatch):
    """Отказ записи: тика честно шагает назад к состоянию держателя, поток
    не молчит — предупреждающий box с текстом причины (principle 3)."""
    boxes = _install_modal_trap(
        monkeypatch, "app.dd.presentation.datasets_sheet.QMessageBox"
    )
    holder = _RefHolderStub(visible=True, fail=True)
    sheet = _ref_sheet(qtbot, holder)
    box = _ref_box(sheet)

    box.click()
    for _ in range(50):
        await asyncio.sleep(0.005)
        if boxes:
            break
    assert holder.written == [False]
    assert holder.visible is True  # держатель не перевернулся
    assert box.isChecked() is True  # тика вернулась
    assert "диск отказал" in boxes[-1].text


async def test_holder_state_reaches_the_database(qtbot, uow):
    """Настоящий держатель поверх штатной единицы работы: клик чекбокса
    дописывает строку до диска — перезапуск перечитывает её (спец. ветка
    «перезапуск сохраняет» на живом контуре листа)."""
    from app.dd.application.reference_visibility_service import (
        ReferenceVisibilityService,
    )

    holder = ReferenceVisibilityService(uow)
    sheet = _ref_sheet(qtbot, holder)
    _ref_box(sheet).click()
    for _ in range(60):
        await asyncio.sleep(0.005)
        if holder.visible is False:
            break
    assert holder.visible is False
    assert await ReferenceVisibilityService(uow).load() is False


async def test_toggle_close_during_write_is_silent(qtbot):
    """Задача рубильника, застигнутая закрытием, снимается молча (отмена —
    штатный исход, окна нет, в мёртвый C++ колбэк не возвращается; PR-037)."""

    class _SlowHolder:
        def __init__(self) -> None:
            self.visible = True
            self.started = asyncio.Event()

        async def set_visible(self, enabled: bool) -> None:
            self.visible = enabled
            self.started.set()
            await asyncio.Event().wait()  # никогда не завершается сама

    holder = _SlowHolder()
    sheet = _ref_sheet(qtbot, holder)
    box = _ref_box(sheet)
    box.click()
    for _ in range(60):
        await asyncio.sleep(0.005)
        if holder.started.is_set():
            break
    assert holder.started.is_set()
    # Любой путь закрытия («Закрыть»/Esc/close()) проходит done(); непро-
    # явленный оффскрин-лист закрываем самой дверью контракта.
    sheet.done(0)
    for _ in range(30):
        await asyncio.sleep(0.005)
    assert sheet._tasks == set()
