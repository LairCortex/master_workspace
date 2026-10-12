"""Точки входа генерации (add-dnd-lss-generation, задачи 7.2/7.3/7.5).

Три двери в листы-задачи и жизнь фасада под ними:

* пункт меню «Сгенерировать персонажа…» печатается только при собранной
  генерации и поднимает сигнал (гейты перечитывает façade при срабатывании);
* кнопки «Сгенерировать ИИ» в листах датасетов/гримуаров живут только с
  opener'ом, неактивны при закрытом AI-гейте с общей русской подсказкой;
* «Дозаполнить ИИ» на D&D-табе собирает документ дверью и зовёт opener,
  а «пусто дозаполнять» — отказ Information-боксом без запуска;
* façade: закрытый гейт и пустое подключение объясняются modeless-боксом
  без открытия листа; живой лист-задача поднимается, близнец не штабелируется;
  detach снимает лист тихо (force_close).

Настоящие входы/контекст/принятие пинят Qt-free тесты и тесты самих листов;
здесь утки ровно там, где проверяется дверь, а не её содержимое.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMainWindow, QMessageBox, QPushButton

from app.dd.application.dataset_index_service import IndexSnapshot
from app.dd.application.generation_deps import GenerationBundle
from app.dd.application.character_channel import TOP_UP_NOTHING_REFUSAL
from app.dd.domain.character import LINK_SLOTS
from app.dd import module as dd_module
from app.dd.module import DndModule
from app.dd.presentation.character_tab_frames import DndCharacterTabFrame
from app.dd.presentation.section import (
    DD_CHARACTER_GENERATION_ACTION_TEXT,
    DndWindowSection,
)
from app.dd.presentation.datasets_sheet import DndDatasetsSheet
from app.dd.presentation.grimoires_sheet import DndGrimoiresSheet
from tests.test_application_settings_errors import _install_modal_trap

HINT = "AI-ассистент не настроен.\nНастройте LLM в «О приложении»."


class _Deps:
    def __init__(self, available: bool = True) -> None:
        self.available_flag = available

    def available(self) -> bool:
        return self.available_flag

    def hint(self) -> str:
        return HINT

    def world(self) -> str:
        return "Мир"

    def make_answer(self):
        async def ask(system_prompt, user_prompt, on_phase=None):
            return "{}"

        return ask


class _StubInputs:
    async def section_entries(self, section):
        return ()

    async def character_context(self, **kwargs):  # pragma: no cover - не зовётся
        raise AssertionError("вход только проверяет дверь, круг не крутится")


class _StubConnections:
    def __init__(self, ids=()) -> None:
        self.ids = list(ids)

    async def connections(self):
        return list(self.ids)

    async def statuses(self):
        return []

    async def connect(self, dataset_id):
        self.ids.append(dataset_id)

    async def disconnect(self, dataset_id):
        self.ids.remove(dataset_id)


class _StubLibrary:
    def list_storage(self):
        return []

    def list_connections_view(self):
        return []

    def download_official_datasets(self):  # pragma: no cover - attach не зовёт
        raise AssertionError


class _StubWiring:
    """Двери, которыми façade трогает коннектор в этих тестах: лок и стек."""

    def __init__(self) -> None:
        self.opened: list = []

    def run_locked(self, coro):
        return asyncio.ensure_future(coro)

    def open_sheet(self, sheet):
        self.opened.append(sheet)
        sheet.show()


def _bundle(available: bool = True) -> GenerationBundle:
    return GenerationBundle(
        deps=_Deps(available),
        inputs=_StubInputs(),
        dataset_acceptance=object(),
        spellbook_acceptance=object(),
        character_import=object(),
        character_document=object(),
    )


def _drain(rounds: int = 30) -> asyncio.Future | asyncio.Future:
    async def _spin():
        for _ in range(rounds):
            await asyncio.sleep(0.005)

    return _spin()


# ── меню модуля (7.3) ────────────────────────────────────────────────────────


def test_generation_menu_entry_prints_only_with_bundle_and_emits(qtbot):
    plain = DndWindowSection(QMainWindow())
    qtbot.addWidget(plain._menu)  # noqa: SLF001 — меню и есть поверхность
    assert not any(
        act.objectName() == "ddCharacterGenerationAction"
        for act in plain._menu.actions()  # noqa: SLF001
    )
    plain.remove()

    window = QMainWindow()
    qtbot.addWidget(window)
    section = DndWindowSection(window, character_generation_available=True)
    qtbot.addWidget(section._menu)  # noqa: SLF001
    actions = [
        act
        for act in section._menu.actions()  # noqa: SLF001
        if act.objectName() == "ddCharacterGenerationAction"
    ]
    assert len(actions) == 1
    assert actions[0].text() == DD_CHARACTER_GENERATION_ACTION_TEXT
    fired: list[bool] = []
    section.character_generation_requested.connect(lambda: fired.append(True))
    actions[0].trigger()
    assert fired == [True]
    section.remove()


# ── кнопки «Сгенерировать ИИ» в листах-источниках (7.2/7.5) ──────────────────


def _datasets_sheet(qtbot, tmp_path, monkeypatch, *, opener, deps):
    from app.dd.application.dataset_import_service import DatasetImportService
    from app.dd.application.dataset_validator_service import DatasetValidatorService
    from app.dd.infrastructure.dataset_storage import DatasetStorage

    storage = DatasetStorage(tmp_path / "datasets")
    connections = _StubConnections()
    library = _StubLibrary()
    importer = DatasetImportService(
        library, connections, DatasetValidatorService(), storage, None
    )
    window = QMainWindow()
    qtbot.addWidget(window)
    sheet = DndDatasetsSheet(
        library=library,
        connections=connections,
        importer=importer,
        run_locked=lambda coro: asyncio.ensure_future(coro),
        parent=window,
        theme=None,
        reference_visibility=None,
        generation_open=opener,
        generation_deps=deps,
    )
    qtbot.addWidget(sheet)
    # pytest-qt держит виджеты СЛАБЫМИ ссылками: окно-родитель должно быть
    # живым рефом у теста, иначе shiboken сносит QDialog вместе с родителем.
    return sheet, window


def test_datasets_generation_button_lives_with_opener_and_gate(qtbot, tmp_path, monkeypatch):
    calls: list[bool] = []
    deps = _Deps(True)
    sheet, _window = _datasets_sheet(
        qtbot, tmp_path, monkeypatch, opener=lambda: calls.append(True), deps=deps
    )
    button = sheet.findChild(QPushButton, "ddGenerateAiButton")
    assert button is not None
    assert button.isEnabled() and button.toolTip() == ""
    deps.available_flag = False
    sheet._apply_generation_gate()
    assert not button.isEnabled()
    assert button.toolTip() == HINT
    deps.available_flag = True
    sheet._apply_generation_gate()
    button.click()
    assert calls == [True]


def test_datasets_without_opener_prints_no_generation_button(qtbot, tmp_path, monkeypatch):
    sheet, _window = _datasets_sheet(
        qtbot, tmp_path, monkeypatch, opener=None, deps=None
    )
    assert sheet.findChild(QPushButton, "ddGenerateAiButton") is None


def test_datasets_button_without_door_reactors_live(qtbot, tmp_path, monkeypatch):
    # Opener есть, дверей гейта нет (тестовая композиция): гейт не тушит
    # кнопку — нечего читать, кнопка живая.
    sheet, _window = _datasets_sheet(
        qtbot, tmp_path, monkeypatch, opener=lambda: None, deps=None
    )
    button = sheet.findChild(QPushButton, "ddGenerateAiButton")
    assert button is not None
    sheet._apply_generation_gate()  # noqa: SLF001 —deps None: молчаливый return
    assert button.isEnabled() and button.toolTip() == ""


async def test_grimoires_generation_button_opens_opener(qtbot, tmp_path, monkeypatch):
    from app.dd.application.grimoire_import_service import GrimoireImportService
    from app.dd.infrastructure.grimoire_storage import GrimoireStorage

    calls: list[bool] = []
    storage = GrimoireStorage(tmp_path / "grimoires")
    window = QMainWindow()
    qtbot.addWidget(window)

    class _Uow:  # подключения в этом тесте не пишут: утка без транзакций
        pass

    deps = _Deps(True)
    sheet = DndGrimoiresSheet(
        storage=storage,
        connections=_StubConnections(),
        importer=GrimoireImportService(storage),
        run_locked=lambda coro: asyncio.ensure_future(coro),
        parent=window,
        theme=None,
        generation_open=lambda: calls.append(True),
        generation_deps=deps,
    )
    qtbot.addWidget(sheet)
    button = sheet.findChild(QPushButton, "ddGrimoireGenerateAiButton")
    assert button is not None
    deps.available_flag = False
    sheet._apply_generation_gate()
    assert not button.isEnabled() and button.toolTip() == HINT
    deps.available_flag = True
    sheet._apply_generation_gate()
    button.click()
    assert calls == [True]


# ── «Дозаполнить ИИ» на D&D-табе (7.3/7.5) ──────────────────────────────────


class _StubService:
    def __init__(self) -> None:
        self.asks: list = []

    async def get_ext(self, character_id):
        self.asks.append(("get_ext", character_id))
        from app.dd.domain.character import DdCharacterExt, ReferenceLink

        return DdCharacterExt(
            links={slot: ReferenceLink("", "", "") for slot, _s, _t in LINK_SLOTS}
        )


class _StubIndex:
    def __init__(self) -> None:
        self._snap = IndexSnapshot(ids=(), titles={}, sections={}, slugs={})

    async def snapshot(self):
        return self._snap


class _Builder:
    """Сборщик документа уткой: отдаёт заготовленный текст (или бросает)."""

    def __init__(self, document: str, *, boom: bool = False) -> None:
        self.document = document
        self.boom = boom
        self.calls: list[int] = []

    async def build(self, character_id: int) -> str:
        self.calls.append(character_id)
        if self.boom:
            raise RuntimeError("диск кончился")
        return self.document


def _top_up_frame(qtbot, builder, opener, deps):
    frame = DndCharacterTabFrame(
        character_id=7,
        service=_StubService(),
        dataset_index=_StubIndex(),
        record_labels={type_key: type_key for _slot, _s, type_key in LINK_SLOTS},
        run_locked=lambda coro: asyncio.ensure_future(coro),
        document_builder=builder,
        generation_open=opener,
        generation_deps=deps,
    )
    qtbot.addWidget(frame)
    return frame


def _lss_document(data: dict) -> str:
    return json.dumps(
        {
            "jsonType": "character",
            "version": "1.0",
            "data": json.dumps(data, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


# Дозаполняемый: имя есть, всё остальное пусто.
PARTIAL = _lss_document({"name": "Половина"})
# Полный по гейту канала: пять ссылок, уровень, заклинания.
FULL = _lss_document(
    {
        "name": "Готов",
        "level": 3,
        "info": {
            "race": {"id": "Elf", "name": "Эльф"},
            "subrace": {"id": "HighElf", "name": "Высший эльф"},
            "charClass": {"id": "Fighter", "name": "Воин"},
            "subclass": {"id": "BattleMaster", "name": "Боевой мастер"},
            "background": {"id": "GuildArtisan", "name": "Гильдейский ремесленник"},
        },
        "blocks": {"Внешность": "рост"},
        "spells": {"list": ["fire-ball"]},
    }
)


async def test_top_up_button_opens_sheet_with_document(qtbot):
    opened: list[tuple] = []
    frame = _top_up_frame(qtbot, _Builder(PARTIAL), lambda cid, doc: opened.append((cid, doc)), _Deps(True))
    await _drain()
    button = frame.findChild(QPushButton, "ddDndTopUpAi")
    assert button is not None
    button.click()
    await _drain()
    assert opened == [(7, PARTIAL)]


async def test_top_up_refuses_when_nothing_missing(qtbot):
    opened: list[tuple] = []
    frame = _top_up_frame(qtbot, _Builder(FULL), lambda *a: opened.append(a), _Deps(True))
    await _drain()
    frame.findChild(QPushButton, "ddDndTopUpAi").click()
    await _drain()
    assert opened == []  # генерация не запускается (spec «Пусто дозаполнять»)
    visible = [box for box in frame.findChildren(QMessageBox) if not box.isHidden()]
    assert any(TOP_UP_NOTHING_REFUSAL in box.text() for box in visible)


async def test_top_up_button_disabled_without_open_opener_gate(qtbot):
    frame = _top_up_frame(qtbot, _Builder(PARTIAL), lambda *a: None, _Deps(False))
    await _drain()
    button = frame.findChild(QPushButton, "ddDndTopUpAi")
    assert not button.isEnabled()
    assert button.toolTip() == HINT


# ── façade: гейты, единственный экземпляр, detach (7.3/7.4) ──────────────────


def _datasets_service():
    """Библиотека для attach: идемпотентный бутстрап без сети (поза файла
    bootstrap-тестов)."""
    from app.dd.domain.dataset import (
        DownloadStatus,
        OfficialDatasetOutcome,
        OfficialDatasetsResult,
    )

    class _Lib:
        def list_storage(self):
            return []

        async def download_official_datasets(self):
            return OfficialDatasetsResult(
                items=(
                    OfficialDatasetOutcome(
                        "srd51",
                        "SRD 5.1 (2014)",
                        DownloadStatus.ALREADY_PRESENT,
                        "уже в хранилище",
                    ),
                )
            )

    return _Lib()


def _attach_module(qtbot, monkeypatch, *, bundle, connections, with_library=False):
    boxes = _install_modal_trap(monkeypatch, f"{dd_module.__name__}.QMessageBox")
    window = QMainWindow()
    qtbot.addWidget(window)
    wiring = _StubWiring()
    module = DndModule(
        datasets_service=_datasets_service() if with_library else None,
        connections_service=connections,
        import_service=object(),
        generation=bundle,
    )
    module.attach(window, wiring)  # type: ignore[arg-type]
    return module, wiring, boxes


async def test_menu_gate_closed_explains_without_sheet(qtbot, monkeypatch):
    module, wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(available=False), connections=_StubConnections(["srd"])
    )
    module._on_character_generation_requested()  # noqa: SLF001
    assert boxes and HINT in boxes[-1].text
    assert wiring.opened == []
    module.detach()


async def test_dataset_gate_empty_explains_without_sheet(qtbot, monkeypatch):
    module, wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections()
    )
    module._on_character_generation_requested()  # noqa: SLF001
    await _drain()
    assert boxes and DndModule.GENERATION_NO_DATASET_BODY in boxes[-1].text
    assert wiring.opened == []
    module.detach()


async def test_character_sheet_opens_once_and_detach_force_closes(qtbot, monkeypatch):
    module, wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections(["srd"])
    )
    module._on_character_generation_requested()  # noqa: SLF001
    await _drain()
    assert len(wiring.opened) == 1
    sheet = wiring.opened[0]
    from app.dd.presentation.generation.character_task_sheet import (
        DndCharacterTaskSheet,
    )

    assert isinstance(sheet, DndCharacterTaskSheet)
    # Второй вызов поднимает живой лист, близнеца не штабелирует.
    module._on_character_generation_requested()  # noqa: SLF001
    await _drain()
    assert len(wiring.opened) == 1
    module.detach()
    assert sheet._released
    # Тихое снятие: ни подтверждающих боксов, ни уведомлений.
    assert not boxes


async def test_dataset_and_spellbook_entries_single_instance(qtbot, monkeypatch):
    from app.dd.infrastructure.grimoire_storage import GrimoireStorage

    storage = GrimoireStorage("/tmp/unused-grimoires-test")  # только реф хранилища
    module, wiring, _ = _attach_module(
        qtbot,
        monkeypatch,
        bundle=_bundle(),
        connections=_StubConnections(["srd"]),
        with_library=True,
    )
    module._grimoire_storage = storage
    module._grimoire_connections = _StubConnections()
    module._grimoire_import = object()
    module._open_dataset_task_sheet()  # noqa: SLF001
    module._open_dataset_task_sheet()  # noqa: SLF001
    module._open_spellbook_task_sheet()  # noqa: SLF001
    module._open_spellbook_task_sheet()  # noqa: SLF001
    assert len(wiring.opened) == 2
    from app.dd.presentation.generation.dataset_task_sheet import (
        DndDatasetTaskSheet,
    )
    from app.dd.presentation.generation.spellbook_task_sheet import (
        DndSpellbookTaskSheet,
    )

    assert isinstance(wiring.opened[0], DndDatasetTaskSheet)
    assert isinstance(wiring.opened[1], DndSpellbookTaskSheet)
    module.detach()


# ── утина дверь set_generation у источника таба (7.3) ────────────────────────


async def test_source_generation_door_travels_into_tab(qtbot):
    from app.dd.presentation.character_tab_source import DndCharacterTabSource

    source = DndCharacterTabSource(
        character_service=_StubService(),
        dataset_index=_StubIndex(),
        character_document=_Builder(PARTIAL),
    )
    wiring = SimpleNamespace(run_locked=lambda coro: asyncio.ensure_future(coro))
    before = source._build_character_tab(wiring, "7")  # noqa: SLF001
    qtbot.addWidget(before)
    assert before.findChild(QPushButton, "ddDndTopUpAi") is None
    source.set_generation(lambda cid, doc: None, _Deps(True))
    after = source._build_character_tab(wiring, "7")  # noqa: SLF001
    qtbot.addWidget(after)
    assert after.findChild(QPushButton, "ddDndTopUpAi") is not None
    source.set_generation(None, None)  # detach-поза: дверь гаснет
    off = source._build_character_tab(wiring, "7")  # noqa: SLF001
    qtbot.addWidget(off)
    assert off.findChild(QPushButton, "ddDndTopUpAi") is None


async def test_façade_pushes_generation_door_into_sources(qtbot, monkeypatch):
    from app.dd.presentation.character_tab_source import DndCharacterTabSource

    source = DndCharacterTabSource(
        character_service=_StubService(),
        dataset_index=_StubIndex(),
        character_document=_Builder(PARTIAL),
    )
    module, _wiring, _boxes = _attach_module(
        qtbot,
        monkeypatch,
        bundle=_bundle(),
        connections=_StubConnections(["srd"]),
    )
    # attach без источников — дверь стоит на месте; проверяем сам механизм
    # façade: ставим источник руками и перекладываем двери, как attach.
    module._external_sources = (source,)  # noqa: SLF001
    module._set_generation_doors()  # noqa: SLF001
    assert source._generation_open is not None  # noqa: SLF001
    module.detach()
    assert source._generation_open is None  # noqa: SLF001


# ── приёмочные ветки гейтов façade (8.1) ──────────────────────────────────────


def _answer_box(box, button_name: str) -> None:
    for handler in box.finished.handlers:
        handler(getattr(box.StandardButton, button_name))


async def test_openers_are_inert_detached_and_without_bundle(qtbot, monkeypatch):
    # Снятый модуль и разборка без генерации: ни одна дверь не открывает лист
    # и не объясняет — неактивные действия не печатаются (belt-and-braces).
    module, wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections(["srd"])
    )
    module.detach()
    assert wiring.opened == []
    module._open_dataset_task_sheet()  # noqa: SLF001
    module._open_spellbook_task_sheet()  # noqa: SLF001
    module._on_character_generation_requested()  # noqa: SLF001
    module._open_character_top_up(7, PARTIAL)  # noqa: SLF001
    module._show_character_sheet(None, None)  # noqa: SLF001
    assert wiring.opened == [] and not boxes

    # Живой модуль, но генерации нет (частичная композиция) — та же тишина.
    module2, wiring2, boxes2 = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections(["srd"])
    )
    module2._generation = None  # noqa: SLF001
    module2._open_dataset_task_sheet()  # noqa: SLF001
    module2._open_spellbook_task_sheet()  # noqa: SLF001
    module2._on_character_generation_requested()  # noqa: SLF001
    module2._open_character_top_up(7, PARTIAL)  # noqa: SLF001
    assert wiring2.opened == [] and not boxes2
    module2.detach()


async def test_top_up_opens_sheet_with_document_single_instance(qtbot, monkeypatch):
    # Дверь дозаполнения: карточка отдала документ — лист в режиме дозаполнения
    # поднимается один раз, близнец не штабелируется; закрытый AI-гейт — бокс.
    module, wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections(["srd"])
    )
    module._open_character_top_up(7, PARTIAL)  # noqa: SLF001
    await _drain()
    assert len(wiring.opened) == 1
    sheet = wiring.opened[0]
    from app.dd.presentation.generation.character_task_sheet import (
        DndCharacterTaskSheet,
    )

    assert isinstance(sheet, DndCharacterTaskSheet)
    assert sheet._top_up and sheet._character_id == 7
    module._open_character_top_up(7, PARTIAL)  # noqa: SLF001
    await _drain()
    assert len(wiring.opened) == 1  # живой лист поднят, второй не заведён
    # Прямой заход в _show_character_sheet при живом листе — тоже бездействие.
    module._show_character_sheet(7, PARTIAL)  # noqa: SLF001
    assert len(wiring.opened) == 1
    module.detach()


async def test_top_up_closed_gate_explains_without_sheet(qtbot, monkeypatch):
    module, wiring, boxes = _attach_module(
        qtbot,
        monkeypatch,
        bundle=_bundle(available=False),
        connections=_StubConnections(["srd"]),
    )
    module._open_character_top_up(7, PARTIAL)  # noqa: SLF001
    assert boxes and HINT in boxes[-1].text
    assert wiring.opened == []
    module.detach()


async def test_top_up_without_connections_service_explains(qtbot, monkeypatch):
    # Композиция без стека датасетов (частичная сборка): дверь дозаполнения
    # объясняет отказ русским телом гейта — читать список некому, листа нет.
    module, wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections(["srd"])
    )
    module._connections = None  # noqa: SLF001
    module._open_character_top_up(7, PARTIAL)  # noqa: SLF001
    assert boxes and DndModule.GENERATION_NO_DATASET_BODY in boxes[-1].text
    assert wiring.opened == []
    module.detach()


class _HangingConnections(_StubConnections):
    """Чтение списка подключённых висит — гейт стоит на одном чтении."""

    def __init__(self) -> None:
        super().__init__(["srd"])
        self.gate = asyncio.Event()

    async def connections(self):
        await self.gate.wait()
        return list(self.ids)


async def test_gate_single_flight_cancelled_by_detach_and_notice_channels(qtbot, monkeypatch):
    # Гейт читается один раз: второй зов при живой задаче — бездействие;
    # detach снимает чтение тихо; callback видит снятый модуль и не трогает
    # мир. Отдельно: отменённая/сбойная проверка — тишина/русский бокс.
    hanging = _HangingConnections()
    module, wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=hanging
    )
    opened: list[bool] = []
    module._check_dataset_gate(lambda: opened.append(True))  # noqa: SLF001
    module._check_dataset_gate(lambda: opened.append(True))  # noqa: SLF001
    assert module._generation_gate_task is not None  # noqa: SLF001
    assert wiring.opened == [] and opened == []
    module.detach()  # тихая отмена чтения (369-370)
    assert module._generation_gate_task is None  # noqa: SLF001
    await _drain()
    assert opened == [] and not boxes  # callback: модуль снялся — тишина

    # Живой модуль: отменённая проверка — молча; сбойная — русский бокс.
    module2, _wiring2, boxes2 = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections(["srd"])
    )
    cancelled = asyncio.ensure_future(asyncio.sleep(5))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    module2._on_gate_checked(cancelled, lambda: None)  # noqa: SLF001
    assert not boxes2
    failed = asyncio.Future()
    failed.set_exception(RuntimeError("база легла"))
    module2._on_gate_checked(failed, lambda: None)  # noqa: SLF001
    assert boxes2 and "Не удалось проверить подключённые датасеты" in boxes2[-1].text
    module2.detach()


async def test_gate_notice_box_forgets_itself_on_close(qtbot, monkeypatch):
    # Закрытый бокс объяснения не остаётся живой ссылкой (поза PR-010):
    # finished сбрасывает _generation_gate_box.
    module, _wiring, boxes = _attach_module(
        qtbot, monkeypatch, bundle=_bundle(), connections=_StubConnections()
    )
    module._on_character_generation_requested()  # noqa: SLF001
    await _drain()
    assert boxes and module._generation_gate_box is not None  # noqa: SLF001
    _answer_box(boxes[-1], "Ok")
    assert module._generation_gate_box is None  # noqa: SLF001
    module.detach()


# ── молчаливые гейты двери дозаполнения на табе (8.1) ────────────────────────


async def test_top_up_click_inert_without_door_builder_or_gate(qtbot):
    # Прямой тычок в обработчик: нет двери или сборщика — молчание; закрытый
    # гейт — молчание (объяснение живёт на кнопке, не в клике).
    opened: list[tuple] = []
    frame = _top_up_frame(qtbot, _Builder(PARTIAL), lambda *a: opened.append(a), _Deps(True))
    await _drain()
    frame._generation_open = None  # noqa: SLF001
    frame._on_top_up_clicked()  # noqa: SLF001
    await _drain()
    assert opened == []
    frame2 = _top_up_frame(qtbot, None, lambda *a: opened.append(a), _Deps(True))
    await _drain()
    frame2._on_top_up_clicked()  # noqa: SLF001
    await _drain()
    assert opened == []
    frame3 = _top_up_frame(qtbot, _Builder(PARTIAL), lambda *a: opened.append(a), _Deps(False))
    await _drain()
    frame3._on_top_up_clicked()  # noqa: SLF001
    await _drain()
    assert opened == []


async def test_top_up_document_build_failure_explains_in_russian(qtbot):
    # Сборка документа упала: русский бокс, карточка не изменена, дверь не
    # вызвана.
    opened: list[tuple] = []
    frame = _top_up_frame(qtbot, _Builder(PARTIAL, boom=True), lambda *a: opened.append(a), _Deps(True))
    await _drain()
    frame.findChild(QPushButton, "ddDndTopUpAi").click()
    await _drain()
    visible = [
        box
        for box in frame.findChildren(QMessageBox)
        if not box.isHidden() and "Не удалось собрать документ" in box.text()
    ]
    assert visible
    assert opened == []
