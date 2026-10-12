"""Лист-задача генерации датасетов (add-dnd-lss-generation, задачи 7.1/7.4/7.5).

Offscreen-контур как в ``test_dd_datasets_sheet.py``: хост-окно, коннектор
целиком (``open_sheet``/``run_locked``), сервисное trio — настоящее поверх
``tmp_path``-хранилища и штатной ``uow``; канал и круг тоже настоящие, а
вместо LLM — скриптованный ответчик. Ловушка PR-010 стоит на QMessageBox
обоих модулей (база + лист): закрытие с in-flight — modeless-подтверждение.

Покрыты: структура и гейт (число 1…10 дефолт 5), полный путь «ответ →
предпросмотр → принятие → автоподключение», лимит автокругов с ручной
«Ещё круг», сбой канала с русским сообщением и перезапуском секции без
частичного предпросмотра, независимость секций, закрытие с in-flight
(подтверждение/отказ/отмена-не-ошибка), отмена секции, released-лист молчит.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

import app.dd.application.prompt_composer as _prompt_composer
from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_import_service import (
    DatasetImportService,
    DatasetImportStatus,
)
from app.dd.application.dataset_index_service import DatasetIndexService
from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.application.dataset_section_channel import (
    DatasetSectionAcceptanceService,
)
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.application.generation_inputs import GenerationInputs
from app.dd.application.generation_loop import AUTO_ROUND_LIMIT
from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.application.grimoire_index_service import GrimoireIndexService
from app.dd.domain.dataset import DatasetMeta, DatasetSource
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.dd.presentation.generation import base as base_module
from app.dd.presentation.generation import dataset_task_sheet as sheet_module
from app.dd.presentation.generation.base import CLOSE_CONFIRM_TEXT
from app.dd.presentation.generation.dataset_task_sheet import (
    DD_DATASET_TASK_TITLE,
    NO_ISSUES_TEXT,
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_CHANNEL_ERROR,
    STATUS_ERRORS,
    STATUS_READY,
    STATUS_RUNNING,
    DndDatasetTaskSheet,
    generation_dataset_id,
)
from app.infrastructure.llm.errors import LlmNetworkError
from app.presentation.wiring import ApplicationWiring
from tests.test_application_settings_errors import _install_modal_trap

GENERATION_DIR = (
    Path(_prompt_composer.__file__).resolve().parent.parent / "resources" / "generation"
)

HINT = "AI-ассистент не настроен.\nНастройте LLM в «О приложении»."


def _fewshot(section: str) -> list[dict]:
    path = GENERATION_DIR / "fewshot" / f"{section}.json"
    return json.loads(path.read_text(encoding="utf-8"))["samples"]


class _ScriptedAsk:
    """Скрипт ответов: очередь на секцию, пустая очередь — честный few-shot.

    Маркер «Секция: <ключ>» живёт в системном промпте и потому неизменен и в
    фидбек-раундах (:func:`format_round_feedback` меняет только пользовательскую
    часть) — маршрутизация по нему не путает параллельные секции.
    """

    def __init__(self, queues: dict[str, list] | None = None) -> None:
        self.queues = {section: list(values) for section, values in (queues or {}).items()}

    @staticmethod
    def _route(system_prompt: str) -> str:
        match = re.search(r"Секция: (\w+)", system_prompt)
        return match.group(1) if match else ""

    def make(self):
        async def ask(system_prompt: str, user_prompt: str, on_phase=None) -> str:
            section = self._route(system_prompt)
            queue = self.queues.get(section)
            if queue:
                item = queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            if on_phase is not None:
                on_phase("повтор 1")
            return json.dumps(_fewshot(section), ensure_ascii=False)

        return ask


class _BlockingAsk(_ScriptedAsk):
    """Ответчик, висящий до события — стенд для закрытия с in-flight."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    def make(self):
        async def ask(system_prompt: str, user_prompt: str, on_phase=None) -> str:
            await self.gate.wait()
            return json.dumps(_fewshot("feats"), ensure_ascii=False)

        return ask


class _Deps:
    """Двери приложения: изменяемый гейт, скриптованный ответчик."""

    def __init__(self, ask: _ScriptedAsk) -> None:
        self.ask = ask
        self.available_flag = True
        self.hint_text = HINT
        self.world_text = "Мир-в-примере"

    def available(self) -> bool:
        return self.available_flag

    def hint(self) -> str:
        return self.hint_text

    def world(self) -> str:
        return self.world_text

    def make_answer(self):
        return self.ask.make()


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


async def _wait_until(predicate, rounds: int = 400, describe=None) -> None:
    for _ in range(rounds):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"условие так и не наступило: {describe() if describe else ''}")


def _answer(box, button_name: str) -> None:
    for handler in box.finished.handlers:
        handler(getattr(box.StandardButton, button_name))


class _Harness:
    def __init__(self, qtbot, uow, tmp_path, monkeypatch):
        self.window = QWidget()
        qtbot.addWidget(self.window)
        self.window.show()
        self.wiring = _make_wiring(self.window)
        self.storage = DatasetStorage(tmp_path / "datasets")
        self.connections = DatasetConnectionsService(uow, self.storage)
        library = DatasetLibraryService(self.storage, SimpleNamespace())
        grimoire_storage = GrimoireStorage(tmp_path / "grimoires")
        grimoire_connections = GrimoireConnectionsService(uow, grimoire_storage)
        grimoire_index = GrimoireIndexService(grimoire_connections, grimoire_storage)
        self.importer = DatasetImportService(
            library,
            self.connections,
            DatasetValidatorService(),
            self.storage,
            grimoire_index,
        )
        index = DatasetIndexService(self.connections, self.storage)
        self.inputs = GenerationInputs(index=index, importer=self.importer)
        self.ask = _ScriptedAsk()
        self.deps = _Deps(self.ask)
        # Подтверждения базы (закрытие/уведомления) и вопрос листа о замене —
        # на отдельных ловушках, чтобы их не смешать.
        self.boxes = _install_modal_trap(
            monkeypatch, f"{base_module.__name__}.QMessageBox"
        )
        self.sheet_boxes = _install_modal_trap(
            monkeypatch, f"{sheet_module.__name__}.QMessageBox"
        )
        self.sheet = DndDatasetTaskSheet(
            deps=self.deps,
            inputs=self.inputs,
            acceptance=DatasetSectionAcceptanceService(
                self.importer, self.connections
            ),
            run_locked=self.wiring.run_locked,
            parent=self.window,
            theme=None,
        )
        qtbot.addWidget(self.sheet)
        self.wiring.open_sheet(self.sheet)

    def check(self, section: str) -> QCheckBox:
        return self.sheet.findChild(QCheckBox, f"ddDatasetGenSection_{section}")

    def spin(self, section: str) -> QSpinBox:
        return self.sheet.findChild(QSpinBox, f"ddDatasetGenCount_{section}")

    def status(self, section: str) -> str:
        return self.sheet.findChild(QLabel, f"ddDatasetGenStatus_{section}").text()

    def preview(self, section: str) -> QPlainTextEdit:
        return self.sheet.findChild(
            QPlainTextEdit, f"ddDatasetGenPreview_{section}"
        )

    def report(self, section: str) -> QLabel:
        return self.sheet.findChild(QLabel, f"ddDatasetGenReport_{section}")

    def button(self, name: str, section: str = "") -> QPushButton:
        return self.sheet.findChild(
            QPushButton, f"ddDatasetGen{name}_{section}" if section else f"ddDatasetGen{name}"
        )

    async def wait_status(self, section: str, expected: str) -> None:
        await _wait_until(
            lambda: expected in self.status(section),
            describe=lambda: f"{section}: {self.status(section)!r}",
        )


@pytest.fixture
async def harness(qtbot, uow, tmp_path, monkeypatch):
    built = _Harness(qtbot, uow, tmp_path, monkeypatch)
    yield built
    built.sheet.force_close()
    await asyncio.sleep(0.02)


# ── структура и гейт (7.1/7.5) ───────────────────────────────────────────────


def test_sheet_prints_sections_count_default_and_gate_tooltip(
    qtbot, uow, tmp_path, monkeypatch
):
    h = _Harness(qtbot, uow, tmp_path, monkeypatch)
    assert h.sheet.windowTitle() == DD_DATASET_TASK_TITLE
    for section in ("classes", "feats", "backgrounds"):
        assert h.check(section) is not None
        assert h.spin(section).value() == 5
        assert h.spin(section).minimum() == 1
        assert h.spin(section).maximum() == 10
    start = h.button("Start")
    assert start.isEnabled()
    assert start.toolTip() == ""
    # Закрытый гейт: неактивная кнопка несёт общую подсказку AI-кнопок.
    h.deps.available_flag = False
    h.sheet.refresh_gate()
    assert not start.isEnabled()
    assert start.toolTip() == HINT
    # Перепоказ перечитывает гейт сам (настройка LLM меняется посреди сессии).
    h.deps.available_flag = True
    h.sheet.hide()
    h.sheet.show()
    assert start.isEnabled()
    h.sheet.force_close()


# ── полный путь: круг → предпросмотр → принятие → автоподключение (7.1) ──────


async def test_generate_preview_accept_shelves_and_autoconnects(harness):
    h = harness
    h.check("feats").setChecked(True)
    h.spin("feats").setValue(2)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_READY)
    assert h.preview("feats").toPlainText().strip()  # документ виден
    assert h.report("feats").text() == NO_ISSUES_TEXT
    accept = h.button("Accept", "feats")
    assert accept.isEnabled()
    accept.click()
    await h.wait_status("feats", STATUS_ACCEPTED)
    # Полка встала с лицензией принятия и автоподключилась к игре.
    content = json.loads(h.storage.load_content(generation_dataset_id("feats")))
    assert content["id"] == generation_dataset_id("feats")
    assert content["license"] == "CC-BY-4.0"
    assert generation_dataset_id("feats") in await h.connections.connections()


# ── лимит автокругов и ручная «Ещё круг» (7.1) ───────────────────────────────


async def test_auto_round_limit_shows_errors_then_manual_round_fixes(harness):
    h = harness
    broken = json.dumps({"не": "массив"}, ensure_ascii=False)
    h.ask.queues["feats"] = [broken] * (AUTO_ROUND_LIMIT + 1) + [
        json.dumps(_fewshot("feats"), ensure_ascii=False)
    ]
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_ERRORS)
    assert not h.button("Accept", "feats").isEnabled()  # с ошибками не принимается
    again = h.button("Again", "feats")
    assert again.isEnabled()  # ручной круг доступен неограниченно
    again.click()
    await h.wait_status("feats", STATUS_READY)
    assert h.button("Accept", "feats").isEnabled()


# ── сбой канала: русское сообщение, перезапуск, без частичного предпросмотра ─


async def test_channel_error_shows_russian_text_and_section_restarts(harness):
    h = harness
    h.ask.queues["classes"] = [LlmNetworkError("Сервер LLM недоступен")]
    h.check("classes").setChecked(True)
    h.button("Start").click()
    await h.wait_status("classes", STATUS_CHANNEL_ERROR)
    # Ошибка на русском в листе; предпросмотр пуст (частичное не показываем);
    # принять нельзя; перезапуск — штатным «Перегенерировать».
    assert "недоступен" in h.report("classes").text()
    assert h.preview("classes").toPlainText() == ""
    assert not h.button("Accept", "classes").isEnabled()
    h.button("Regen", "classes").click()
    await h.wait_status("classes", STATUS_READY)
    # Сбой канала — не программа-ошибка: боксов не было.
    assert not h.boxes
    assert not h.sheet_boxes


# ── независимость секций: одна упала, соседняя цела (7.1) ────────────────────


async def test_failed_section_does_not_touch_ready_neighbour(harness):
    h = harness
    h.ask.queues["feats"] = ["мусор не-json"] * 99
    h.check("feats").setChecked(True)
    # Сосед — races: его few-shot самодостаточен (backgrounds ссылается на
    # фиты и на пустом корпусе дал бы LINK_FEAT, а не чистый ответ).
    h.check("races").setChecked(True)
    h.button("Start").click()
    # «готово» — общая основа обоих готовых статусов (чистый и с
    # предупреждениями: races few-shot отдаёт неопасные предупреждения).
    await h.wait_status("races", "готово")
    await h.wait_status("feats", STATUS_ERRORS)
    assert h.button("Accept", "races").isEnabled()
    assert not h.button("Accept", "feats").isEnabled()
    assert h.preview("races").toPlainText().strip()


# ── жизнь задачи в листе: закрытие с in-flight (7.4) ─────────────────────────


async def test_close_with_inflight_asks_confirm_and_refusal_continues(harness):
    h = harness
    blocking = _BlockingAsk()
    h.deps.ask = blocking
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_RUNNING)
    # Закрытие посреди запроса: лист остаётся, modeless-подтверждение
    # предупреждает об обрыве.
    h.sheet.close()
    await _wait_until(lambda: bool(h.boxes))
    assert h.sheet.isVisible()
    assert CLOSE_CONFIRM_TEXT in h.boxes[-1].text
    # Отказ — задача продолжает жить.
    _answer(h.boxes[-1], "No")
    await asyncio.sleep(0.02)
    assert h.sheet.isVisible()
    assert STATUS_RUNNING in h.status("feats")
    # Согласие — задачи отменены, лист закрыт, released.
    h.sheet.close()
    await _wait_until(lambda: len(h.boxes) >= 2)
    _answer(h.boxes[-1], "Yes")
    await _wait_until(lambda: not h.sheet.isVisible())
    assert h.sheet._released
    # Отменённая задача — не ошибка: третьих боксов (уведомлений) нет.
    assert len(h.boxes) == 2
    assert not h.sheet_boxes
    # Released-лист не отвечает на поздние клики.
    before = len(h.sheet._tasks)
    h.sheet._on_start_clicked()
    h.sheet._start_section("feats", previous=None)
    assert len(h.sheet._tasks) == before


async def test_section_cancel_is_not_an_error(harness):
    h = harness
    blocking = _BlockingAsk()
    h.deps.ask = blocking
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_RUNNING)
    h.button("Cancel", "feats").click()
    assert h.status("feats") == STATUS_CANCELLED
    # Отмена — не ошибка: ни боксов, ни подтверждения о закрытии; лист жив.
    assert not h.boxes
    assert not h.sheet_boxes
    assert h.sheet.isVisible()
    # Отменённую секцию можно запустить заново.
    h.deps.ask = _ScriptedAsk()
    h.button("Start").click()
    await h.wait_status("feats", STATUS_READY)


# ── вопрос двери о замене своей полки — подтверждение доходит door (7.1) ──────


async def test_accept_existing_shelf_asks_replace_then_stores(harness):
    h = harness
    existing = generation_dataset_id("feats")
    h.storage.save(
        existing,
        json.dumps(
            {
                "$schema": "https://example/schema",
                "id": existing,
                "name": "Старый",
                "system": "dnd",
                "edition": "2024",
                "author": "мастер",
                "license": "CC0",
                "feats": [],
            },
            ensure_ascii=False,
        ),
        DatasetMeta(
            source=DatasetSource.HOMEBREW, imported_at="2026-10-01", sha256="9" * 64
        ),
    )
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_READY)
    h.button("Accept", "feats").click()
    await _wait_until(lambda: bool(h.sheet_boxes))
    assert existing in h.sheet_boxes[-1].text
    _answer(h.sheet_boxes[-1], "No")
    # Отказ от замены — бездействие: полка не тронута, статус прежний.
    await asyncio.sleep(0.02)
    assert h.status("feats") == STATUS_READY
    assert json.loads(h.storage.load_content(existing))["name"] == "Старый"
    h.button("Accept", "feats").click()
    await _wait_until(lambda: len(h.sheet_boxes) >= 2)
    _answer(h.sheet_boxes[-1], "Yes")
    await h.wait_status("feats", STATUS_ACCEPTED)
    assert json.loads(h.storage.load_content(existing))["name"] != "Старый"
    assert existing in await h.connections.connections()


# ── приёмочные ветки редковетвящихся обработчиков (8.1) ───────────────────────


async def test_second_close_while_confirm_open_does_not_stack_boxes(harness):
    # Подтверждение уже открыто — второе закрытие не наслаивает бокс (base
    # closeEvent: _closing стоит до ответа).
    h = harness
    blocking = _BlockingAsk()
    h.deps.ask = blocking
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_RUNNING)
    h.sheet.close()
    await _wait_until(lambda: bool(h.boxes))
    h.sheet.close()
    h.sheet.close()
    assert len(h.boxes) == 1
    assert h.sheet.isVisible()
    _answer(h.boxes[-1], "No")


async def test_program_error_in_round_gets_russian_notice(harness):
    # Программа-ошибка внутри круга (не сбой канала): русский бокс из базы,
    # журнал, статус сбоя — лист жив и секция перезапускается.
    h = harness

    async def boom(*args, **kwargs):
        raise RuntimeError("кривой контекст")

    h.sheet._inputs.dataset_section_context = boom
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_CHANNEL_ERROR)
    await _wait_until(lambda: bool(h.boxes))
    assert "непредвиденной ошибкой" in h.boxes[-1].text
    job = h.sheet._jobs["feats"]
    assert job.running is None
    # Чужая задача (ни одна секция её не крутит) — job не находится.
    assert h.sheet._job_from_task(asyncio.Future()) is None
    # Бокс закрыт — живая ссылка сброшена (постулата PR-010).
    _answer(h.boxes[-1], "Ok")
    assert h.sheet._notice_box is None


async def test_inert_entries_released_and_closed_gate(harness):
    # Released-лист не отвечает: перезапуск при закрытом гейте, отмена секции
    # и перечитывание гейта — бездействие и без боксов.
    h = harness
    h.deps.available_flag = False
    h.sheet._start_section("feats", previous=None)  # прямой вызов при гейте
    assert h.sheet._jobs["feats"].running is None
    # Прямой клик принятия без результата круга — гейт молча держит дверь.
    h.sheet._on_accept_clicked("feats")
    assert not h.boxes and not h.sheet_boxes
    h.sheet.force_close()
    h.sheet.refresh_gate()
    h.sheet._on_cancel_clicked("feats")
    assert not h.boxes and not h.sheet_boxes


def test_render_without_result_is_a_noop(qtbot, uow, tmp_path, monkeypatch):
    h = _Harness(qtbot, uow, tmp_path, monkeypatch)
    h.sheet._render(h.sheet._jobs["feats"])  # result None — раньше, чем круг
    assert h.status("feats") == "ожидает"
    h.sheet.force_close()


async def test_accept_door_blocked_reports_in_notice(harness):
    # Дверь импорта ответила BLOCKED с отчётом: русский бокс с телом двери
    # и строками отчёта; статус не «принято».
    from app.dd.application.dataset_import_service import DatasetImportOutcome
    from app.dd.application.dataset_section_channel import DatasetAcceptanceOutcome
    from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport

    h = harness
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_READY)

    class _BlockedDoor:
        async def accept(self, document, license_choice, *, confirmed):
            return DatasetAcceptanceOutcome(
                import_outcome=DatasetImportOutcome(
                    status=DatasetImportStatus.BLOCKED,
                    message="Отказ двери: набор не принят.",
                    report=ValidationReport.of(
                        [
                            CheckIssue(
                                code="BLOCKED_TEST",
                                severity=Severity.ERROR,
                                path="<тест>",
                                message="полка защищена",
                            )
                        ]
                    ),
                )
            )

    h.sheet._acceptance = _BlockedDoor()
    h.button("Accept", "feats").click()
    await _wait_until(lambda: bool(h.boxes))
    assert "Отказ двери" in h.boxes[-1].text
    assert "полка защищена" in h.boxes[-1].text
    assert h.status("feats") == STATUS_READY
    _answer(h.boxes[-1], "Ok")
    assert h.sheet._notice_box is None


async def test_accept_done_tolerates_cancel_program_error_and_release(harness):
    # Три молчаливых/аварийных исхода двери: отменённая задача — не ошибка,
    # программа-ошибка — русский бокс, released-лист — тишина.
    h = harness

    cancelled = asyncio.ensure_future(asyncio.sleep(5))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    h.sheet._on_accept_done(cancelled)  # отмена — не ошибка
    assert not h.boxes and not h.sheet_boxes

    failed = asyncio.Future()
    failed.set_exception(RuntimeError("дверь упала"))
    h.sheet._on_accept_done(failed)
    await _wait_until(lambda: bool(h.boxes))
    assert "непредвиденной ошибкой" in h.boxes[-1].text
    _answer(h.boxes[-1], "Ok")

    h.sheet.force_close()
    ready = asyncio.Future()
    ready.set_result((None, None))
    h.sheet._on_accept_done(ready)  # released — молчит
    assert len(h.boxes) == 1


async def test_close_button_finished_peels_sheet_through_done(harness):
    # Дефект-пин 8.1: любой путь закрытия доходит до finished — и подтверждённое
    # закрытие, и «Закрыть»/Esc ведут через reject/done. Подтверждённое закрытие
    # с in-flight тоже обязано увести лист через finished (иначе стек коннектора
    # и рефы держат мёртвый лист).
    h = harness
    blocking = _BlockingAsk()
    h.deps.ask = blocking
    h.check("feats").setChecked(True)
    h.button("Start").click()
    await h.wait_status("feats", STATUS_RUNNING)
    finished: list[int] = []
    h.sheet.finished.connect(lambda code: finished.append(int(code)))
    h.sheet.close()
    await _wait_until(lambda: bool(h.boxes))
    _answer(h.boxes[-1], "Yes")
    await _wait_until(lambda: not h.sheet.isVisible())
    assert finished  # finished дошёл: коннектор снял лист со стека

