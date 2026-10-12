"""Лист-задача генерации файла заклинаний (add-dnd-lss-generation, 7.2/7.4/7.5).

Тот же offscreen-контур, что у листа датасетов: коннектор целиком, гримуарное
дверное trio настоящее поверх ``tmp_path``; круг и канал настоящие, LLM —
скриптованный ответчик. Проверки спеки: предупреждение НЕ блокирует принятие
(число заклинаний 1…10, дефолт 5), структурные ошибки блокируют, принятие
создаёт НОВЫЙ гримуар, повторная полка — вопрос двери с подтверждением, сбой
канала — русским текстом в листе с перезапуском.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton, QSpinBox, QWidget

import app.dd.application.prompt_composer as _prompt_composer
from app.dd.application.generation_inputs import GenerationInputs
from app.dd.application.dataset_connections_service import (
    DatasetConnectionsService,
)
from app.dd.application.dataset_import_service import DatasetImportService
from app.dd.application.dataset_index_service import DatasetIndexService
from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.application.dataset_validator_service import DatasetValidatorService
from app.dd.application.generation_loop import AUTO_ROUND_LIMIT
from app.dd.application.grimoire_connections_service import (
    GrimoireConnectionsService,
)
from app.dd.application.grimoire_import_service import GrimoireImportService
from app.dd.application.grimoire_index_service import GrimoireIndexService
from app.dd.application.spellbook_channel import SpellbookAcceptanceService
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from app.dd.presentation.generation import base as base_module
from app.dd.presentation.generation import spellbook_task_sheet as sheet_module
from app.dd.presentation.generation.spellbook_task_sheet import (
    DD_SPELLBOOK_TASK_TITLE,
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_CHANNEL_ERROR,
    STATUS_ERRORS,
    STATUS_RUNNING,
    DndSpellbookTaskSheet,
)
from app.infrastructure.llm.errors import LlmTimeoutError
from app.presentation.wiring import ApplicationWiring
from tests.test_application_settings_errors import _install_modal_trap

GENERATION_DIR = (
    Path(_prompt_composer.__file__).resolve().parent.parent / "resources" / "generation"
)

HINT = "AI-ассистент не настроен.\nНастройте LLM в «О приложении»."


def _fewshot_spells() -> list[dict]:
    path = GENERATION_DIR / "fewshot" / "spellbook.json"
    return json.loads(path.read_text(encoding="utf-8"))["samples"]


def _answer_with_empty_text() -> str:
    """Честный few-shot с обнулённым описанием одного заклинания —
    предупреждение CODE_SPELL_TEXT_EMPTY, не ошибка: принятие остаётся
    правом мастера."""
    spells = copy.deepcopy(_fewshot_spells())
    spells[0]["system"]["description"]["value"] = ""
    return json.dumps(spells, ensure_ascii=False)


class _ScriptedAsk:
    def __init__(self, queue: list | None = None) -> None:
        self.queue = list(queue or [])

    def make(self):
        async def ask(system_prompt: str, user_prompt: str, on_phase=None) -> str:
            assert "Секция" not in system_prompt  # это промпт файла заклинаний
            if self.queue:
                item = self.queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            return json.dumps(_fewshot_spells(), ensure_ascii=False)

        return ask


class _Deps:
    def __init__(self, ask: _ScriptedAsk) -> None:
        self.ask = ask
        self.available_flag = True

    def available(self) -> bool:
        return self.available_flag

    def hint(self) -> str:
        return HINT

    def world(self) -> str:
        return "Мир-в-примере"

    def make_answer(self):
        return self.ask.make()


def _make_wiring(window) -> ApplicationWiring:
    app = SimpleNamespace(_image_store=None, _theme=None)
    return ApplicationWiring(
        app, window, None, None, None, None, None,
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
        self.grimoire_storage = GrimoireStorage(tmp_path / "grimoires")
        self.grimoire_connections = GrimoireConnectionsService(
            uow, self.grimoire_storage
        )
        self.grimoire_index = GrimoireIndexService(
            self.grimoire_connections, self.grimoire_storage
        )
        dataset_storage = DatasetStorage(tmp_path / "datasets")
        dataset_connections = DatasetConnectionsService(uow, dataset_storage)
        library = DatasetLibraryService(dataset_storage, SimpleNamespace())
        importer = DatasetImportService(
            library,
            dataset_connections,
            DatasetValidatorService(),
            dataset_storage,
            self.grimoire_index,
        )
        index = DatasetIndexService(dataset_connections, dataset_storage)
        self.inputs = GenerationInputs(
            index=index, importer=importer, grimoire_index=self.grimoire_index
        )
        self.ask = _ScriptedAsk()
        self.deps = _Deps(self.ask)
        self.boxes = _install_modal_trap(
            monkeypatch, f"{base_module.__name__}.QMessageBox"
        )
        self.sheet_boxes = _install_modal_trap(
            monkeypatch, f"{sheet_module.__name__}.QMessageBox"
        )
        self.sheet = DndSpellbookTaskSheet(
            deps=self.deps,
            inputs=self.inputs,
            acceptance=SpellbookAcceptanceService(
                GrimoireImportService(self.grimoire_storage)
            ),
            run_locked=self.wiring.run_locked,
            parent=self.window,
            theme=None,
        )
        qtbot.addWidget(self.sheet)
        self.wiring.open_sheet(self.sheet)

    def label(self, name: str):
        return self.sheet.findChild(QLabel, f"ddSpellbookGen{name}")

    def button(self, name: str) -> QPushButton:
        return self.sheet.findChild(QPushButton, f"ddSpellbookGen{name}")

    def status(self) -> str:
        return self.label("Status").text()

    def preview(self) -> QPlainTextEdit:
        return self.sheet.findChild(QPlainTextEdit, "ddSpellbookGenPreview")

    async def wait_status(self, expected: str) -> None:
        await _wait_until(
            lambda: expected in self.status(),
            describe=lambda: f"status={self.status()!r}",
        )


@pytest.fixture
async def harness(qtbot, uow, tmp_path, monkeypatch):
    built = _Harness(qtbot, uow, tmp_path, monkeypatch)
    yield built
    built.sheet.force_close()
    await asyncio.sleep(0.02)


def test_sheet_count_default_and_gate_tooltip(qtbot, uow, tmp_path, monkeypatch):
    h = _Harness(qtbot, uow, tmp_path, monkeypatch)
    assert h.sheet.windowTitle() == DD_SPELLBOOK_TASK_TITLE
    count = h.sheet.findChild(QSpinBox, "ddSpellbookGenCount")
    assert count.value() == 5
    assert count.minimum() == 1
    assert count.maximum() == 10
    start = h.button("Start")
    assert start.isEnabled() and start.toolTip() == ""
    h.deps.available_flag = False
    h.sheet.refresh_gate()
    assert not start.isEnabled()
    assert start.toolTip() == HINT
    h.sheet.force_close()


async def test_generate_accept_stores_new_grimoire(harness):
    h = harness
    h.sheet.findChild(QSpinBox, "ddSpellbookGenCount").setValue(3)
    h.button("Start").click()
    await h.wait_status("готово")
    assert h.preview().toPlainText().strip()
    accept = h.button("Accept")
    assert accept.isEnabled()
    accept.click()
    await h.wait_status(STATUS_ACCEPTED)
    stored = h.grimoire_storage.list_grimoires()
    assert len(stored) == 1
    # Принятие — одна полка; кнопка после принятия неактивна.
    assert not accept.isEnabled()


async def test_warnings_do_not_block_acceptance(harness):
    h = harness
    h.ask.queue = [_answer_with_empty_text()]
    h.button("Start").click()
    await h.wait_status("готово")
    report = h.label("Report").text()
    assert "пустой текст" in report  # предупреждение показано
    assert h.sheet._result.ok  # …ошибок нет
    assert h.button("Accept").isEnabled()  # принятие остаётся правом мастера
    h.button("Accept").click()
    await h.wait_status(STATUS_ACCEPTED)


async def test_structural_errors_block_and_manual_round_fixes(harness):
    h = harness
    h.ask.queue = [json.dumps({"не": "массив"}, ensure_ascii=False)] * (
        AUTO_ROUND_LIMIT + 1
    ) + [json.dumps(_fewshot_spells(), ensure_ascii=False)]
    h.button("Start").click()
    await h.wait_status(STATUS_ERRORS)
    assert not h.button("Accept").isEnabled()
    assert h.button("Again").isEnabled()
    h.button("Again").click()
    await h.wait_status("готово")
    assert h.button("Accept").isEnabled()


async def test_channel_error_is_russian_and_restarts(harness):
    h = harness
    h.ask.queue = [LlmTimeoutError("Время ожидания ответа истекло")]
    h.button("Start").click()
    await h.wait_status(STATUS_CHANNEL_ERROR)
    assert "истекло" in h.label("Report").text()
    assert h.preview().toPlainText() == ""  # частичное не показываем
    assert not h.button("Accept").isEnabled()
    h.button("Regen").click()
    await h.wait_status("готово")
    assert not h.boxes
    assert not h.sheet_boxes


async def test_cancel_stops_task_without_error(harness):
    h = harness
    gate = asyncio.Event()

    async def hang(system_prompt: str, user_prompt: str, on_phase=None) -> str:
        await gate.wait()
        return "{}"

    h.ask.make = lambda: hang
    h.button("Start").click()
    await h.wait_status(STATUS_RUNNING)
    h.button("Cancel").click()
    assert h.status() == STATUS_CANCELLED
    assert not h.boxes and not h.sheet_boxes
    # Отменённый лист можно перезапустить.
    h.ask.make = _ScriptedAsk().make
    h.button("Start").click()
    await h.wait_status("готово")


async def test_same_shelf_twice_asks_replace_then_stores(harness):
    h = harness
    h.button("Start").click()
    await h.wait_status("готово")
    h.button("Accept").click()
    await h.wait_status(STATUS_ACCEPTED)
    # Тот же документ вторично — content-addressed полка занята: перегенерация
    # даёт тот же ответ, принятие спрашивает замену, Yes подтверждает дверь.
    h.button("Regen").click()
    await h.wait_status("готово")
    h.button("Accept").click()
    await _wait_until(lambda: bool(h.sheet_boxes))
    _answer(h.sheet_boxes[-1], "Yes")
    await h.wait_status(STATUS_ACCEPTED)
    assert len(h.grimoire_storage.list_grimoires()) == 1


# ── приёмочные ветки редковетвящихся обработчиков (8.1) ───────────────────────


async def test_start_inert_while_busy_closed_gate_or_released(harness):
    # Повторный запуск при живой задаче, прямой вызов при закрытом гейте и
    # любой вход released-листа — бездействие без боксов.
    h = harness
    gate = asyncio.Event()

    async def hang(system_prompt: str, user_prompt: str, on_phase=None) -> str:
        await gate.wait()
        return json.dumps(_fewshot_spells(), ensure_ascii=False)

    h.ask.make = lambda: hang
    h.button("Start").click()
    await h.wait_status(STATUS_RUNNING)
    before = h.sheet._task
    h.sheet._start(previous=None)  # живой круг — второй не заводится
    assert h.sheet._task is before
    # Штатный индикатор фаз озвучивает повтор в статусе.
    h.sheet._on_phase("повтор 1")
    assert "повтор 1" in h.status()
    gate.set()
    await h.wait_status("готово")

    h.deps.available_flag = False
    h.sheet._start(previous=None)  # закрытый гейт — прямо не запускается
    assert h.sheet._task is None
    h.sheet.force_close()
    h.sheet._start(previous=None)
    h.sheet.refresh_gate()
    h.sheet._on_cancel_clicked()
    assert not h.boxes and not h.sheet_boxes


def test_render_without_result_is_a_noop(qtbot, uow, tmp_path, monkeypatch):
    h = _Harness(qtbot, uow, tmp_path, monkeypatch)
    h.sheet._render()  # result None — раньше, чем круг
    assert h.status() == "ожидает"
    h.sheet._on_accept_clicked()  # прямой клик без результата — гейт держит
    assert not h.sheet._task
    h.sheet.force_close()


async def test_program_error_in_round_gets_russian_notice(harness):
    # Программа-ошибка внутри круга (не сбой канала): русский бокс, статус
    # сбоя, лист жив.
    h = harness

    async def boom(*args, **kwargs):
        raise RuntimeError("кривой контекст")

    h.sheet._inputs.spellbook_context = boom
    h.button("Start").click()
    await h.wait_status(STATUS_CHANNEL_ERROR)
    await _wait_until(lambda: bool(h.boxes))
    assert "непредвиденной ошибкой" in h.boxes[-1].text
    assert h.sheet._task is None
    _answer(h.boxes[-1], "Ok")
    assert h.sheet._notice_box is None


async def test_accept_done_tolerates_cancel_program_error_and_blocked(harness):
    # Молчаливая отмена, программа-ошибка двери — русский бокс, BLOCKED с
    # отчётом — бокс с телом двери и строками отчёта; released — тишина.
    from app.dd.application.grimoire_import_service import (
        GrimoireImportOutcome,
        GrimoireImportStatus,
    )
    from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport

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

    h.button("Start").click()
    await h.wait_status("готово")

    class _BlockedDoor:
        # Дверь синхронная — как SpellbookAcceptanceService (task 4.2).
        def accept(self, document, *, confirmed, srd_slugs):
            return GrimoireImportOutcome(
                status=GrimoireImportStatus.BLOCKED,
                message="Отказ двери: файл не принят.",
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

    h.sheet._acceptance = _BlockedDoor()
    h.button("Accept").click()
    await _wait_until(lambda: len(h.boxes) >= 2)
    assert "Отказ двери" in h.boxes[-1].text
    assert "полка защищена" in h.boxes[-1].text
    assert "готово" in h.status()
    _answer(h.boxes[-1], "Ok")
    assert h.sheet._notice_box is None

    h.sheet.force_close()
    ready = asyncio.Future()
    ready.set_result(None)
    h.sheet._on_accept_done(ready)  # released — молчит
    assert len(h.boxes) == 2


async def test_replace_refusal_does_not_store(harness):
    # Вопрос двери о своей полке: «Нет» — бездействие (return в обработчике
    # ответа), статус и хранилище прежние.
    h = harness
    h.button("Start").click()
    await h.wait_status("готово")
    h.button("Accept").click()
    await h.wait_status(STATUS_ACCEPTED)
    h.button("Regen").click()
    await h.wait_status("готово")
    h.button("Accept").click()
    await _wait_until(lambda: bool(h.sheet_boxes))
    _answer(h.sheet_boxes[-1], "No")
    await asyncio.sleep(0.02)
    assert "готово" in h.status()
    assert len(h.grimoire_storage.list_grimoires()) == 1
