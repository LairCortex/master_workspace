"""Автозагрузка SRD при attach фаcада (add-dnd-module-foundation, task 3.3;
spec dnd-dataset-library «Автозагрузка SRD-наборов», «Офлайн не ломает игру»,
«Повторный запуск не качает»).

Фаcад от сервисного слоя отделён тонким контрактом: у сервиса спрашивается
только ``download_official_datasets()`` — здесь стоит ФЕЙКОВЫЙ сервис,
отвечающий заготовленным результатом/зависанием/крахом. Настоящая идемпотентность
и сеть проверяются в соседних файлах (сервис + MockTransport-клиент) и живыми
потоками жизненного цикла (там полки уже засеяны фикстурой conftest — бутстрап
молчит и сети не трогает).
"""
from __future__ import annotations

import asyncio

import pytest
from PySide6.QtWidgets import QMainWindow, QMessageBox

from app.dd.domain.dataset import (
    DownloadStatus,
    OfficialDatasetOutcome,
    OfficialDatasetsResult,
)
from app.dd import module as dd_module
from app.dd.module import DD_DATASETS_TITLE, DD_DATASETS_UNEXPECTED_BODY, DndModule


def _result(downloaded: bool = False, failed: bool = False) -> OfficialDatasetsResult:
    if downloaded:
        items = (
            OfficialDatasetOutcome("srd51", "SRD 5.1 (2014)", DownloadStatus.DOWNLOADED, "SRD 5.1"),
        )
    elif failed:
        items = (
            OfficialDatasetOutcome(
                "srd51",
                "SRD 5.1 (2014)",
                DownloadStatus.FAILED,
                "longstoryshort.app недоступен — проверьте подключение к сети",
            ),
        )
    else:
        items = (
            OfficialDatasetOutcome(
                "srd51", "SRD 5.1 (2014)", DownloadStatus.ALREADY_PRESENT, "уже в хранилище"
            ),
        )
    return OfficialDatasetsResult(items=items)


class FakeDatasetsService:
    """Один метод — весь контракт фаcада с библиотекой датасетов."""

    def __init__(self, result=None, hang: bool = False, crash: bool = False):
        self.calls = 0
        self._result = result if result is not None else _result()
        self._hang = hang
        self._crash = crash
        self._gate = asyncio.Event()

    async def download_official_datasets(self) -> OfficialDatasetsResult:
        self.calls += 1
        if self._crash:
            raise RuntimeError("диск кончился")
        if self._hang:
            await self._gate.wait()
        return self._result


def _attach(qtbot, service) -> tuple[DndModule, QMainWindow]:
    window = QMainWindow()
    qtbot.addWidget(window)
    module = DndModule(datasets_service=service)
    module.attach(window, object())  # type: ignore[arg-type]
    return module, window


# ── расписание: когда бутстрап ставится, а когда нет ─────────────────────────


def test_sync_attach_without_loop_skips_the_schedule(qtbot):
    """Вне крутящегося цикла (оффскрин-attach вне qasync) задача не ставится
    и сервис не трогается: следующая игра спросит через тот же attach."""
    service = FakeDatasetsService()
    module, _window = _attach(qtbot, service)
    assert module._bootstrap_task is None  # noqa: SLF001 - внутренний контракт
    assert service.calls == 0
    module.detach()


def test_module_without_dataset_stack_never_asks(qtbot):
    """Композиция без стека датасетов (флаг-тесты ядра) — тишина: attach не
    создаёт задачи, detach не за что цепляться."""
    window = QMainWindow()
    qtbot.addWidget(window)
    module = DndModule()
    module.attach(window, object())  # type: ignore[arg-type]
    assert module._bootstrap_task is None  # noqa: SLF001
    module.detach()


# ── ответы пользователю (spec: «Успех и каждая ошибка … по-русски») ──────────


async def test_downloaded_result_shows_russian_info_box(qtbot, monkeypatch):
    # Offscreen-квирк Qt 6 (тот же класс, что пустой QAccessible.Name у штатных
    # контролов): QMessageBox.windowTitle() читается пустым, хотя сеттер
    # отрабатывает — заголовок пионится spy-подклассом в пространстве имён
    # модуля («Name equals the visible text» живёт в live-аудите).
    titles: list[str] = []

    class TitleSpyBox(QMessageBox):
        def setWindowTitle(self, title):
            titles.append(title)
            super().setWindowTitle(title)

    # Патч — по объекту модуля, захваченному импортом файла: test_dd_module_profile
    # вычищает app.dd.* из sys.modules, и строковый таргет monkeypatch импортировал
    # бы СВЕЖУЮ копию модуля, а класс DndModule жил бы в старой.
    monkeypatch.setattr(dd_module, "QMessageBox", TitleSpyBox)
    service = FakeDatasetsService(result=_result(downloaded=True))
    module, _window = _attach(qtbot, service)
    await asyncio.sleep(0)  # задача стартует на первом тике цикла
    assert service.calls == 1 and module._bootstrap_task is not None  # noqa: SLF001
    await module._bootstrap_task  # noqa: SLF001
    await asyncio.sleep(0)  # done-callback ставится следующим тиком цикла
    box = module._datasets_box  # noqa: SLF001
    assert box is not None
    assert titles == [DD_DATASETS_TITLE]
    assert "SRD 5.1 (2014)" in box.text() and "загружены" in box.text()
    assert box.icon() == QMessageBox.Icon.Information
    box.done(QMessageBox.StandardButton.Ok)  # закрытие сбрасывает live-ссылку
    assert module._datasets_box is None  # noqa: SLF001
    module.detach()


async def test_failed_result_shows_russian_warning_box(qtbot):
    """Спека «Офлайн не ломает игру»: краха нет, есть предупреждение с
    русской причиной; игра под окном живёт."""
    service = FakeDatasetsService(result=_result(failed=True))
    module, _window = _attach(qtbot, service)
    await module._bootstrap_task  # noqa: SLF001
    await asyncio.sleep(0)
    box = module._datasets_box  # noqa: SLF001
    assert box is not None and box.icon() == QMessageBox.Icon.Warning
    assert "Не удалось загрузить официальные наборы SRD" in box.text()
    assert "недоступен" in box.text()
    module.detach()


async def test_all_present_answer_stays_silent(qtbot):
    """Спека «Повторный запуск не качает» на стороне фаcада: «уже в
    хранилище» — это не событие для пользователя, коробка не показывается."""
    service = FakeDatasetsService(result=_result())
    module, _window = _attach(qtbot, service)
    await module._bootstrap_task  # noqa: SLF001
    await asyncio.sleep(0)
    assert module._datasets_box is None  # noqa: SLF001
    module.detach()


async def test_unexpected_crash_still_reaches_the_user(qtbot):
    """Service выдал то, что не замаплено в строки (принцип 3: сетевые/
    дисковые ошибки не молчат) — журнал + коробка с общим текстом."""
    service = FakeDatasetsService(crash=True)
    module, _window = _attach(qtbot, service)
    with pytest.raises(RuntimeError):
        await module._bootstrap_task  # noqa: SLF001
    await asyncio.sleep(0)
    box = module._datasets_box  # noqa: SLF001
    assert box is not None and box.icon() == QMessageBox.Icon.Warning
    assert box.text() == DD_DATASETS_UNEXPECTED_BODY
    module.detach()


# ── detach гасит незавершённый бутстрап ──────────────────────────────────────


async def test_detach_cancels_inflight_bootstrap_and_stays_quiet(qtbot):
    service = FakeDatasetsService(hang=True)
    module, _window = _attach(qtbot, service)
    await asyncio.sleep(0)  # задача успела стартовать и сесть на gate
    task = module._bootstrap_task  # noqa: SLF001
    assert task is not None and not task.done()
    module.detach()
    assert module._bootstrap_task is None  # noqa: SLF001
    with pytest.raises(asyncio.CancelledError):
        await task
    assert module._datasets_box is None  # noqa: SLF001 - отчёт ушёл с окном


async def test_late_answer_after_detach_is_silent(qtbot):
    """Done-callback, дошедший уже после detach (окно снято, а задача успела
    завершиться НЕ отменённой), не рисует окно без родителя: ветка «окна
    нет» — тишина. Колбэк прогоняется напрямую synthetic-задачей: через
    публичный detach в такую ветку попадает только отменённая задача, а эта
    ветка — страховка от гонки «задача завершилась между detach и колбэком»."""
    module, _window = _attach(qtbot, FakeDatasetsService(hang=True))
    inflight = module._bootstrap_task  # noqa: SLF001
    module.detach()
    with pytest.raises(asyncio.CancelledError):
        await inflight
    late = asyncio.ensure_future(_done_coroutine())
    await late
    module._on_datasets_bootstrapped(late)  # noqa: SLF001 - прямой прогон ветки
    assert module._datasets_box is None  # noqa: SLF001


async def _done_coroutine() -> OfficialDatasetsResult:
    return _result(downloaded=True)
