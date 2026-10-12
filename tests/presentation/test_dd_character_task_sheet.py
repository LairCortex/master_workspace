"""Лист-задача генерации персонажа (add-dnd-lss-generation, 7.3/7.4/7.5).

Создание и дозаполнение — один лист в двух режимах. Входы (словарь,
контекст) — уткою: их настоящее разрешение пинят Qt-free тесты
``test_generation_inputs.py``; дверь импорта — тоже утка с настоящими
``CharacterImportOutcome`` (конвейер пинят сервисные тесты). Живыми остаются
лист, круг, канал, гейт, подтверждения и закрытие.

Проверки спеки: два заголовка режимов; пре-выборы уровня/вида/класса
доезжают до контекста; дозаполнение не заводит пре-выборов; «пусто
дозаполнять» — русский отказ конструктора контекста живёт в листе как сбой
круга; перезапись карточки требует подтверждения и доходит ``confirmed=True``.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QLabel, QPlainTextEdit, QPushButton, QWidget

from app.dd.application.character_channel import (
    TOP_UP_NOTHING_REFUSAL,
    CharacterContext,
)
from app.dd.application.character_import_service import (
    CharacterImportOutcome,
    CharacterImportStatus,
)
from app.dd.application.prompt_composer import SlugVocabularyEntry
from app.dd.presentation.generation import base as base_module
from app.dd.presentation.generation import character_task_sheet as sheet_module
from app.dd.presentation.generation.character_task_sheet import (
    DD_CHARACTER_TASK_TITLE,
    DD_TOP_UP_TASK_TITLE,
    STATUS_ACCEPTED_CREATE,
    STATUS_ACCEPTED_TOP_UP,
    STATUS_CHANNEL_ERROR,
    STATUS_CANCELLED,
    STATUS_READY,
    STATUS_RUNNING,
    DndCharacterTaskSheet,
)
from app.infrastructure.llm.errors import LlmNetworkError
from app.presentation.wiring import ApplicationWiring
from tests.test_application_settings_errors import _install_modal_trap

HINT = "AI-ассистент не настроен.\nНастройте LLM в «О приложении»."

_VOCABULARY = (
    SlugVocabularyEntry("srd", "Elf", "Эльф"),
    SlugVocabularyEntry("srd", "Fighter", "Воин"),
)
_RECORD_IDS = ("Elf", "Fighter")

CONTENT = {
    "name": "Мариссель Тал",
    "level": 3,
    "info": {
        "race": {"id": "Elf", "name": "Эльф"},
        "charClass": {"id": "Fighter", "name": "Воин"},
    },
    "blocks": {"Внешность": "Прямая спина, седина рано тронула виски."},
}

# Дозаполняемый документ: обложка есть, блоков нет — полному листу чего
# дописать (гейт «пусто дозаполнять» конструктора контекста не срабатывает).
PARTIAL_DOCUMENT = json.dumps(
    {
        "jsonType": "character",
        "version": "1.0",
        "data": json.dumps({"name": "Половина"}, ensure_ascii=False),
    },
    ensure_ascii=False,
)


def _answer(**over) -> str:
    data = dict(CONTENT)
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


class _ScriptedAsk:
    def __init__(self, queue: list | None = None) -> None:
        self.queue = list(queue or [])

    def make(self):
        async def ask(system_prompt: str, user_prompt: str, on_phase=None) -> str:
            if self.queue:
                item = self.queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            return _answer()

        return ask


class _StubInputs:
    """Дверь контекста: записи словаря и сборка CharacterContext уткою —
    настоящее разрешение пинят Qt-free тесты GenerationInputs."""

    def __init__(self, refuse: str | None = None) -> None:
        self.refuse = refuse
        self.kwargs: dict | None = None

    async def section_entries(self, section: str):
        if section == "races":
            return (_VOCABULARY[0],)
        if section == "classes":
            return (_VOCABULARY[1],)
        return ()

    async def character_context(self, **kwargs) -> CharacterContext:
        self.kwargs = kwargs
        if self.refuse is not None:
            raise ValueError(self.refuse)
        return CharacterContext(
            vocabulary=_VOCABULARY,
            record_ids=_RECORD_IDS,
            spell_slugs=None,
            **kwargs,
        )


class _ImportDoor:
    """Импортный конвейер уткой с настоящими исходными типами: перезапись
    (character_id задан) требует подтверждения — как живая дверь."""

    def __init__(self) -> None:
        self.calls: list[tuple[int | None, bool]] = []

    async def import_character(
        self, content: str, *, character_id: int | None = None, confirmed: bool = False
    ) -> CharacterImportOutcome:
        self.calls.append((character_id, confirmed))
        if character_id is not None and not confirmed:
            return CharacterImportOutcome(
                status=CharacterImportStatus.NEEDS_CONFIRMATION,
                message="Карточка будет перезаписана — нужно подтверждение.",
            )
        if character_id is None:
            return CharacterImportOutcome(
                status=CharacterImportStatus.CREATED, character_id=101
            )
        return CharacterImportOutcome(
            status=CharacterImportStatus.OVERWRITTEN, character_id=character_id
        )


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


def _answer_box(box, button_name: str) -> None:
    for handler in box.finished.handlers:
        handler(getattr(box.StandardButton, button_name))


class _Harness:
    """Сборка листа: create (character_id=None) или top-up (документ+id)."""

    def __init__(
        self,
        qtbot,
        monkeypatch,
        *,
        character_id: int | None = None,
        current_document: str | None = None,
        inputs: _StubInputs | None = None,
        ask: _ScriptedAsk | None = None,
        door: _ImportDoor | None = None,
    ):
        self.window = QWidget()
        qtbot.addWidget(self.window)
        self.window.show()
        self.wiring = _make_wiring(self.window)
        self.inputs = inputs or _StubInputs()
        self.ask = ask or _ScriptedAsk()
        self.deps = _Deps(self.ask)
        self.door = door or _ImportDoor()
        self.boxes = _install_modal_trap(
            monkeypatch, f"{base_module.__name__}.QMessageBox"
        )
        self.sheet_boxes = _install_modal_trap(
            monkeypatch, f"{sheet_module.__name__}.QMessageBox"
        )
        self.sheet = DndCharacterTaskSheet(
            deps=self.deps,
            inputs=self.inputs,
            character_import=self.door,
            run_locked=self.wiring.run_locked,
            character_id=character_id,
            current_document=current_document,
            parent=self.window,
            theme=None,
        )
        qtbot.addWidget(self.sheet)
        self.wiring.open_sheet(self.sheet)

    def combo(self, name: str) -> QComboBox | None:
        return self.sheet.findChild(QComboBox, f"ddCharacterGen{name}")

    def label(self, name: str) -> QLabel:
        return self.sheet.findChild(QLabel, f"ddCharacterGen{name}")

    def button(self, name: str) -> QPushButton:
        prefix = (
            "ddCharacterTopUp"
            if name == "Start" and self.sheet._top_up
            else "ddCharacterGen"
        )
        return self.sheet.findChild(QPushButton, f"{prefix}{name}")

    def preview(self) -> QPlainTextEdit:
        return self.sheet.findChild(QPlainTextEdit, "ddCharacterGenPreview")

    def status(self) -> str:
        return self.label("Status").text()

    async def wait_status(self, expected: str) -> None:
        await _wait_until(
            lambda: expected in self.status(),
            describe=lambda: f"status={self.status()!r}",
        )

    async def choices_ready(self) -> None:
        if self.sheet._top_up:
            return
        await _wait_until(lambda: self.combo("Race").count() > 1)


@pytest.fixture
async def harness(qtbot, monkeypatch):
    built = _Harness(qtbot, monkeypatch)
    yield built
    built.sheet.force_close()
    await asyncio.sleep(0.02)


def _top_up_harness(qtbot, monkeypatch, **over) -> _Harness:
    return _Harness(
        qtbot,
        monkeypatch,
        character_id=42,
        current_document=PARTIAL_DOCUMENT,
        **over,
    )


# ── режимы и гейт (7.3/7.5) ──────────────────────────────────────────────────


async def test_create_mode_prints_preselects_and_gate(qtbot, monkeypatch):
    h = _Harness(qtbot, monkeypatch)
    assert h.sheet.windowTitle() == DD_CHARACTER_TASK_TITLE
    assert h.combo("Level") is not None
    assert h.combo("Race") is not None
    assert h.combo("Class") is not None
    start = h.button("Start")
    assert start.text() == "Сгенерировать"
    h.deps.available_flag = False
    h.sheet.refresh_gate()
    assert not start.isEnabled() and start.toolTip() == HINT
    h.sheet.force_close()


async def test_top_up_mode_reuses_sheet_without_preselects(qtbot, monkeypatch):
    h = _top_up_harness(qtbot, monkeypatch)
    try:
        assert h.sheet.windowTitle() == DD_TOP_UP_TASK_TITLE
        # Пре-выборов нет: дозаполнение дописывает пустое, лицо не выбирает.
        assert h.combo("Race") is None
        assert h.combo("Level") is None
        assert h.button("Start").text() == "Дозаполнить"
    finally:
        h.sheet.force_close()


# ── создание: круг → предпросмотр → принятие (7.3) ───────────────────────────


async def test_create_round_accept_creates_character(harness):
    h = harness
    await h.choices_ready()
    h.button("Start").click()
    await h.wait_status(STATUS_READY)
    # Предпросмотр раскрывает data-конверт: читается содержательная часть.
    assert "Мариссель Тал" in h.preview().toPlainText()
    h.button("Accept").click()
    await h.wait_status(STATUS_ACCEPTED_CREATE)
    assert h.door.calls == [(None, False)]
    assert not h.button("Accept").isEnabled()


async def test_preselects_travel_into_context(qtbot, monkeypatch):
    h = _Harness(qtbot, monkeypatch)
    try:
        await h.choices_ready()
        h.combo("Level").setCurrentText("7")
        h.combo("Race").setCurrentIndex(1)  # за «—» — Эльф из словаря
        h.combo("Class").setCurrentIndex(1)
        h.button("Start").click()
        await h.wait_status(STATUS_READY)
        assert h.inputs.kwargs["level"] == 7
        assert h.inputs.kwargs["race"] == _VOCABULARY[0]
        assert h.inputs.kwargs["char_class"] == _VOCABULARY[1]
    finally:
        h.sheet.force_close()


# ── дозаполнение: подтверждённая перезапись (7.3) ─────────────────────────────


async def test_top_up_overwrite_requires_confirmation(qtbot, monkeypatch):
    h = _top_up_harness(qtbot, monkeypatch)
    try:
        h.button("Start").click()
        await h.wait_status(STATUS_READY)
        h.button("Accept").click()
        # Дверь спросила — modeless-вопрос листа; No = бездействие.
        await _wait_until(lambda: bool(h.sheet_boxes))
        _answer_box(h.sheet_boxes[-1], "No")
        await asyncio.sleep(0.02)
        assert h.door.calls == [(42, False)]
        assert h.status() not in (STATUS_ACCEPTED_TOP_UP,)
        # Да — новый заход: дверь снова спрашивает и получает Yes, повтор
        # доходит confirmed=True.
        h.button("Accept").click()
        await _wait_until(lambda: len(h.sheet_boxes) >= 2)
        _answer_box(h.sheet_boxes[-1], "Yes")
        await h.wait_status(STATUS_ACCEPTED_TOP_UP)
        assert h.door.calls == [(42, False), (42, False), (42, True)]
    finally:
        h.sheet.force_close()


async def test_top_up_refusal_lives_in_sheet(qtbot, monkeypatch):
    # Гейт «пусто дозаполнять» — право конструктора контекста; лист несёт
    # русский отказ как сбой круга: предпросмотра нет, боксов нет, restartable.
    h = _Harness(
        qtbot,
        monkeypatch,
        character_id=42,
        current_document=PARTIAL_DOCUMENT,
        inputs=_StubInputs(refuse=TOP_UP_NOTHING_REFUSAL),
    )
    try:
        h.button("Start").click()
        await h.wait_status(STATUS_CHANNEL_ERROR)
        assert "дозаполнять" in h.label("Report").text()
        assert h.preview().toPlainText() == ""
        assert not h.boxes
        assert not h.sheet_boxes
    finally:
        h.sheet.force_close()


# ── канал-ошибки и круг (7.5) ─────────────────────────────────────────────────


async def test_channel_error_russian_and_restarts(harness):
    h = harness
    await h.choices_ready()
    h.ask.queue = [LlmNetworkError("Сервер LLM недоступен")]
    h.button("Start").click()
    await h.wait_status(STATUS_CHANNEL_ERROR)
    assert "недоступен" in h.label("Report").text()
    assert h.preview().toPlainText() == ""
    h.button("Regen").click()
    await h.wait_status(STATUS_READY)
    assert not h.boxes and not h.sheet_boxes


async def test_structural_answer_errors_allow_manual_round(harness):
    h = harness
    await h.choices_ready()
    h.ask.queue = ["не json вообще", "тоже мимо", "третий мимо", _answer(level=3)]
    h.button("Start").click()
    # Два автокруга съедены, третий — стоп с ошибочным статусом.
    await h.wait_status("ошибки валидатора")
    assert not h.button("Accept").isEnabled()
    assert h.button("Again").isEnabled()
    h.button("Again").click()
    await h.wait_status(STATUS_READY)


async def test_cancel_stops_without_error_and_restarts(harness):
    h = harness
    await h.choices_ready()
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
    h.ask.make = _ScriptedAsk().make
    h.button("Start").click()
    await h.wait_status(STATUS_READY)
    gate.set()


# ── приёмочные ветки редковетвящихся обработчиков (8.1) ───────────────────────


class _BoomInputs(_StubInputs):
    """Словарь падает программной ошибкой — лист обязан доложить боксом."""

    async def section_entries(self, section: str):
        raise RuntimeError("полка словаря упала")


class _BoomContextInputs(_StubInputs):
    """Программа-ошибка сборки контекста (не русское «пусто дозаполнять»)."""

    async def character_context(self, **kwargs) -> CharacterContext:
        raise RuntimeError("кривой контекст")


async def test_choices_program_error_gets_russian_notice(qtbot, monkeypatch):
    # Словарь пре-выборов упал программной ошибкой: русский бокс из базы,
    # лист жив (создание без словаря всё равно возможно — пре-выборы «—»).
    h = _Harness(qtbot, monkeypatch, inputs=_BoomInputs())
    try:
        await _wait_until(lambda: bool(h.boxes))
        assert "непредвиденной ошибкой" in h.boxes[-1].text
        assert h.combo("Race").count() == 1  # остался только «—»
        _answer_box(h.boxes[-1], "Ok")
        assert h.sheet._notice_box is None
    finally:
        h.sheet.force_close()


async def test_program_error_in_round_gets_russian_notice(qtbot, monkeypatch):
    # Программа-ошибка внутри круга: русский бокс + статус сбоя, лист жив.
    h = _Harness(qtbot, monkeypatch, inputs=_BoomContextInputs())
    try:
        await h.choices_ready()
        h.button("Start").click()
        await h.wait_status(STATUS_CHANNEL_ERROR)
        await _wait_until(lambda: bool(h.boxes))
        assert "непредвиденной ошибкой" in h.boxes[-1].text
        _answer_box(h.boxes[-1], "Ok")
    finally:
        h.sheet.force_close()


async def test_inert_entries_released_busy_and_closed_gate(harness):
    # Молчаливые гейты: запуск при закрытом гейте и при живой задаче, прямой
    # клик принятия без результата, рендер без результата, refresh_gate,
    # «Отменить» и любые done-callbacks released-листа — бездействие.
    h = harness
    await h.choices_ready()
    h.sheet._render()  # result None — раньше, чем круг
    assert h.status() == "ожидает"
    h.sheet._on_accept_clicked()  # прямой клик без результата — гейт держит
    assert not h.boxes and not h.sheet_boxes

    h.deps.available_flag = False
    h.sheet._start(previous=None)  # закрытый гейт — прямо не запускается
    assert h.sheet._task is None

    h.deps.available_flag = True
    gate = asyncio.Event()

    async def hang(system_prompt: str, user_prompt: str, on_phase=None) -> str:
        await gate.wait()
        return "{}"

    h.ask.make = lambda: hang
    h.button("Start").click()
    await h.wait_status(STATUS_RUNNING)
    before = h.sheet._task
    h.sheet._start(previous=None)  # живой круг — второй не заводится
    assert h.sheet._task is before
    # Индикатор фаз озвучивает ход круга в статусе.
    h.sheet._on_phase("шаг 2")
    assert "шаг 2" in h.status()
    h.button("Cancel").click()
    gate.set()
    await asyncio.sleep(0.02)

    h.sheet.force_close()
    h.sheet._start(previous=None)
    h.sheet.refresh_gate()
    h.sheet._on_cancel_clicked()
    ready = asyncio.Future()
    ready.set_result(None)
    h.sheet._on_accept_done(ready)  # released — молчит
    assert not h.boxes and not h.sheet_boxes


def test_pretty_tolerates_non_json_and_broken_envelope():
    # Предпросмотр не теряет текст: не-JSON отдаётся как есть, а living-конверт
    # с непарсящейся data-строкой печатается целым (data остаётся строкой).
    assert DndCharacterTaskSheet._pretty("не json вообще") == "не json вообще"
    envelope = json.dumps({"data": "не json {{{"}, ensure_ascii=False)
    pretty = DndCharacterTaskSheet._pretty(envelope)
    assert "не json {{{" in pretty


async def test_accept_done_tolerates_cancel_program_error_and_blocked(harness):
    # Молчаливая отмена, программа-ошибка двери — русский бокс, BLOCKED с
    # отчётом — бокс с телом двери и строками отчёта; статус не «принято».
    from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport

    h = harness
    await h.choices_ready()

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
    _answer_box(h.boxes[-1], "Ok")

    h.button("Start").click()
    await h.wait_status(STATUS_READY)

    class _BlockedDoor:
        async def import_character(
            self, content: str, *, character_id=None, confirmed: bool = False
        ):
            return CharacterImportOutcome(
                status=CharacterImportStatus.BLOCKED,
                message="Отказ двери: документ не принят.",
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

    h.sheet._importer = _BlockedDoor()
    h.button("Accept").click()
    await _wait_until(lambda: len(h.boxes) >= 2)
    assert "Отказ двери" in h.boxes[-1].text
    assert "полка защищена" in h.boxes[-1].text
    assert h.status() == STATUS_READY
    _answer_box(h.boxes[-1], "Ok")
    assert h.sheet._notice_box is None
