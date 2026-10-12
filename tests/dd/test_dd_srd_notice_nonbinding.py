"""Необязывающее SRD-уведомление (fix-dnd-followups, задача 2.2; spec
dnd-dataset-library «Автозагрузка SRD-наборов»: «Уведомление результата SHALL
быть необязывающим», сценарий «Ошибка загрузки не блокирует работу»).

Красное живое воспроизведение (заметка изменения, `evidence/`): бокс сводки
офлайна показан неблокирующим ``show()``, но ``QMessageBox`` по умолчанию
ApplicationModal — на живом дисплее ``Esc`` открытого листа до листа не
доходил, пока мастер не жмёт «OK». Оффскрин-пин держит обе половины
починки (Д1): бокс Не модальный; при открытом боксе лист закрывается по Esc
без «OK», а само уведомление остаётся открытым.
"""
from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMainWindow, QMessageBox, QWidget

from app.dd.domain.dataset import (
    DownloadStatus,
    OfficialDatasetOutcome,
    OfficialDatasetsResult,
)
from app.dd.module import DndModule
from app.presentation.views.sheet_frame import SheetFrame


def _failed_result() -> OfficialDatasetsResult:
    return OfficialDatasetsResult(
        items=(
            OfficialDatasetOutcome(
                "srd51",
                "SRD 5.1 (2014)",
                DownloadStatus.FAILED,
                "longstoryshort.app недоступен — проверьте подключение к сети",
            ),
        )
    )


class _FailingDatasetsService:
    """Один метод — весь контракт фаcада; всегда отвечает офлайн-провалом."""

    async def download_official_datasets(self) -> OfficialDatasetsResult:
        return _failed_result()


async def test_offline_summary_box_is_not_modal(qtbot):
    """Пин причины из 2.1: ``QMessageBox`` рождается ApplicationModal, и ``show()``
    этого не меняет — бокс уведомления обязан явно носить NonModal (поза
    PR-012 всех окон приложения)."""
    window = QMainWindow()
    qtbot.addWidget(window)
    module = DndModule(datasets_service=_FailingDatasetsService())
    module.attach(window, object())  # type: ignore[arg-type]
    await module._bootstrap_task  # noqa: SLF001 - внутренний контракт
    await asyncio.sleep(0)  # done-callback ставится следующим тиком цикла
    box = module._datasets_box  # noqa: SLF001
    assert box is not None and box.icon() == QMessageBox.Icon.Warning
    assert box.windowModality() == Qt.WindowModality.NonModal
    module.detach()


async def test_sheet_closes_on_escape_while_box_is_open(qtbot):
    """Сценарий «Ошибка загрузки не блокирует работу»: при открытом боксе
    лист закрывается по Esc БЕЗ «OK»; уведомление при этом остаётся открытым
    и ничего не удерживает."""
    window = QMainWindow()
    qtbot.addWidget(window)
    module = DndModule(datasets_service=_FailingDatasetsService())
    module.attach(window, object())  # type: ignore[arg-type]
    await module._bootstrap_task  # noqa: SLF001
    await asyncio.sleep(0)
    box = module._datasets_box  # noqa: SLF001
    assert box is not None and box.isVisible()

    sheet = SheetFrame("Датасеты D&D…", window)
    qtbot.addWidget(sheet)
    content = QWidget(sheet)
    sheet.add_content(content)
    sheet.show()
    content.setFocus()

    QTest.keyClick(content, Qt.Key.Key_Escape)

    assert not sheet.isVisible()  # лист отпустил Esc без «OK» на боксе
    assert box.isVisible()  # # необязывающее: уведомление живёт своей жизнью
    box.done(QMessageBox.StandardButton.Ok)
    module.detach()
