"""The import's UI doors, offscreen (add-dnd-game-face task 9.4; spec
dnd-character-import «Точки входа явные», «Перезапись требует подтверждения»).

Two entry points, one tree of answers:

* the module menu «Импорт персонажа из файла LSS…» — creation: the entry
  exists only when the import service was composed, an empty pick is a
  no-op, an unreadable file answers a Russian box without ever approaching
  the service, and every outcome (success with its warning list, refusal
  with the report lines, crash) gets its modeless box; a detach cancels an
  in-flight import in silence;
* the card's file doors live on the «Основное» block channel since
  dd-card-redesign task 5.5 — their flow (unconfirmed verdict, the Yes/No
  question, the byte-for-byte confirmed re-request, the save-raw truth and
  every crash belt) is pinned in ``test_character_main_blocks.py``;
* the no-dead-controls posture: without a composed service the menu entry
  does not exist at all (the door row's half of this posture is pinned
  beside the flows above).

The service door is a stub of canned outcomes; the decision tree itself
belongs to ``test_character_import_service.py`` — what lives here is only
which box the master sees and which request the screen dares to send.
"""
from __future__ import annotations

import asyncio
import types

from PySide6.QtWidgets import QMainWindow, QMessageBox

from app.dd import module as dd_module
from app.dd.application.character_import_service import (
    OVERWRITE_CONFIRM_BODY,
    CharacterImportOutcome,
    CharacterImportStatus,
)
from app.dd.application.dataset_index_service import IndexSnapshot
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.dd.module import DD_CHARACTER_IMPORT_TITLE, DndModule
from app.dd.presentation.section import (
    DD_CHARACTER_IMPORT_ACTION_TEXT,
    DndWindowSection,
)

_EMPTY_SNAP = IndexSnapshot(ids=(), titles={}, sections={}, slugs={})


async def _drain(times: int = 10) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


def _warn(path: str, message: str) -> CheckIssue:
    return CheckIssue(code="W", severity=Severity.WARNING, path=path, message=message)


def _err(path: str, message: str) -> CheckIssue:
    return CheckIssue(code="E", severity=Severity.ERROR, path=path, message=message)


def _pick(monkeypatch, target_module, path: str) -> None:
    """The file panel answers ``path`` (empty string — the отвод)."""
    monkeypatch.setattr(
        target_module.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (path, "")),
    )


def _boxes(parent) -> list[QMessageBox]:
    return [box for box in parent.findChildren(QMessageBox) if not box.isHidden()]


# ── the section entry (menu half) ──────────────────────────────────────────


def test_section_without_a_service_prints_no_entry(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    section = DndWindowSection(window)
    qtbot.addWidget(section._menu)  # noqa: SLF001 — the menu is the surface
    assert not any(
        act.objectName() == "ddCharacterImportAction"
        for act in section._menu.actions()  # noqa: SLF001
    )
    section.remove()


def test_section_entry_carries_the_caption_and_emits(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    section = DndWindowSection(window, character_import_available=True)
    qtbot.addWidget(section._menu)  # noqa: SLF001
    actions = [
        act
        for act in section._menu.actions()  # noqa: SLF001
        if act.objectName() == "ddCharacterImportAction"
    ]
    assert len(actions) == 1
    assert actions[0].text() == DD_CHARACTER_IMPORT_ACTION_TEXT
    fired: list[bool] = []
    section.character_import_requested.connect(lambda: fired.append(True))
    actions[0].trigger()
    assert fired == [True]
    section.remove()


# ── the module creation flow ───────────────────────────────────────────────


class _StubImporter:
    """The import service as the screens see it: canned outcomes, records."""

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple] = []
        self.gate: asyncio.Event | None = None

    async def import_character(self, content, *, character_id=None, confirmed=False):
        self.calls.append((content, character_id, confirmed))
        if self.gate is not None:
            await self.gate.wait()
        return self.outcomes.pop(0)

    async def save_raw_document(self, character_id, path):  # frames-only door
        self.calls.append(("save", character_id, path))
        return True


def _attach_module(qtbot, importer) -> tuple[DndModule, QMainWindow]:
    window = QMainWindow()
    qtbot.addWidget(window)
    wiring = types.SimpleNamespace(
        run_locked=lambda coro: asyncio.ensure_future(coro)
    )
    module = DndModule(character_import=importer)
    module.attach(window, wiring)  # type: ignore[arg-type]
    return module, window


def _import_action(module: DndModule):
    assert module._section is not None  # noqa: SLF001
    return [
        act
        for act in module._section._menu.actions()  # noqa: SLF001
        if act.objectName() == "ddCharacterImportAction"
    ]


def test_menu_entry_exists_only_with_a_composed_service(qtbot):
    plain = DndModule()
    window = QMainWindow()
    qtbot.addWidget(window)
    plain.attach(window, types.SimpleNamespace(run_locked=None))  # type: ignore[arg-type]
    assert _import_action(plain) == []
    plain.detach()

    importer = _StubImporter([])
    module, _window = _attach_module(qtbot, importer)
    assert len(_import_action(module)) == 1
    module.detach()


async def test_creation_success_box_lists_the_warnings(qtbot, monkeypatch, tmp_path):
    good = tmp_path / "grog.json"
    good.write_text('{"jsonType": "character"}', encoding="utf-8")
    # Offscreen-quirk Qt 6 (the datasets bootstrap's finding): a shown
    # QMessageBox reads its windowTitle empty — the title is pinned through
    # a spy subclass patched on the module's own reference.
    titles: list[str] = []

    class TitleSpyBox(QMessageBox):
        def setWindowTitle(self, title):
            titles.append(title)
            super().setWindowTitle(title)

    monkeypatch.setattr(dd_module, "QMessageBox", TitleSpyBox)
    report = ValidationReport.of([_warn("data.wizardStep", "служебный ключ проигнорирован")])
    importer = _StubImporter(
        [
            CharacterImportOutcome(
                status=CharacterImportStatus.CREATED,
                character_id=7,
                name="Грог",
                message="Персонаж «Грог» создан из файла LSS.",
                report=report,
            )
        ]
    )
    module, window = _attach_module(qtbot, importer)
    _pick(monkeypatch, dd_module, str(good))
    _import_action(module)[0].trigger()
    await _drain()
    boxes = _boxes(window)
    assert len(boxes) == 1
    assert titles == [DD_CHARACTER_IMPORT_TITLE]
    assert "создан из файла LSS" in boxes[0].text()
    assert "Предупреждения:" in boxes[0].text()
    assert "data.wizardStep — служебный ключ" in boxes[0].text()
    assert importer.calls == [('{"jsonType": "character"}', None, False)]
    assert module._character_import_task is None  # noqa: SLF001
    # The box's own close channel drops the live ref (PR-010 hygiene).
    boxes[0].button(QMessageBox.StandardButton.Ok).click()
    await _drain()
    assert module._character_import_box is None  # noqa: SLF001
    module.detach()


async def test_creation_belts_reported_not_swallowed(qtbot):
    # Two belts of the done-callback, exercised through its door: a report
    # that reaches a departed window stays silent, and the confirmation
    # answer (unreachable for a creation by contract) is printed, not lost.
    importer = _StubImporter([])
    module, window = _attach_module(qtbot, importer)

    module._window = None  # noqa: SLF001 — the race the belt stands in for
    loop = asyncio.get_running_loop()
    done_ok: asyncio.Future = loop.create_future()
    done_ok.set_result(
        CharacterImportOutcome(status=CharacterImportStatus.CREATED, name="Грог")
    )
    module._on_character_import_done(done_ok)  # noqa: SLF001
    assert _boxes(window) == []
    module._window = window  # noqa: SLF001

    needs: asyncio.Future = asyncio.get_running_loop().create_future()
    needs.set_result(
        CharacterImportOutcome(
            status=CharacterImportStatus.NEEDS_CONFIRMATION, message=OVERWRITE_CONFIRM_BODY
        )
    )
    module._on_character_import_done(needs)  # noqa: SLF001
    assert any(OVERWRITE_CONFIRM_BODY in b.text() for b in _boxes(window))
    module.detach()


async def test_creation_refusal_prints_the_report_lines(qtbot, monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{{{", encoding="utf-8")
    report = ValidationReport.of([_err("<файл>", "файл не читается как JSON")])
    importer = _StubImporter(
        [CharacterImportOutcome(status=CharacterImportStatus.BLOCKED, report=report)]
    )
    module, window = _attach_module(qtbot, importer)
    _pick(monkeypatch, dd_module, str(bad))
    _import_action(module)[0].trigger()
    await _drain()
    boxes = _boxes(window)
    assert "Импорт отклонён — отчёт проверки:" in boxes[0].text()
    assert "<файл> — файл не читается как JSON" in boxes[0].text()
    module.detach()


async def test_empty_pick_and_unreadable_file_never_reach_the_service(
    qtbot, monkeypatch, tmp_path
):
    importer = _StubImporter([])
    module, window = _attach_module(qtbot, importer)

    _pick(monkeypatch, dd_module, "")  # the отвод
    _import_action(module)[0].trigger()
    await _drain()
    assert importer.calls == []
    assert _boxes(window) == []

    broken = tmp_path / "broken.json"
    broken.write_bytes(b"\xff\xfe not utf-8")
    _pick(monkeypatch, dd_module, str(broken))
    _import_action(module)[0].trigger()
    await _drain()
    assert importer.calls == []
    boxes = _boxes(window)
    assert "Не удалось прочитать файл" in boxes[0].text()
    module.detach()


async def test_crashed_import_answers_one_box_detach_silence(qtbot, monkeypatch, tmp_path):
    good = tmp_path / "g.json"
    good.write_text("{}", encoding="utf-8")

    class _BoomImporter(_StubImporter):
        async def import_character(self, content, **kwargs):  # noqa: ANN002, ANN003
            self.calls.append((content, None, False))
            raise RuntimeError("диск кончился")

    module, window = _attach_module(qtbot, _BoomImporter([]))
    _pick(monkeypatch, dd_module, str(good))
    _import_action(module)[0].trigger()
    await _drain()
    boxes = _boxes(window)
    assert "Импорт персонажа не завершился" in boxes[0].text()
    module.detach()

    # The cancel posture: a detach with a request in flight cancels it and
    # the callback keeps quiet (no box on a dying window).
    hang = _StubImporter([])
    hang.gate = asyncio.Event()
    module2, window2 = _attach_module(qtbot, hang)
    _pick(monkeypatch, dd_module, str(good))
    _import_action(module2)[0].trigger()
    await _drain(2)
    task = module2._character_import_task  # noqa: SLF001
    assert task is not None
    module2.detach()
    await _drain()
    assert task.cancelled()
    assert _boxes(window2) == []


def test_unattached_belt_returns_in_silence(qtbot):
    module = DndModule(character_import=_StubImporter([]))
    module._on_character_import_requested()  # noqa: SLF001 — no window yet
    attached = DndModule()  # no import service: the belt under a missing entry
    window = QMainWindow()
    qtbot.addWidget(window)
    attached.attach(window, types.SimpleNamespace(run_locked=None))  # type: ignore[arg-type]
    attached._on_character_import_requested()  # noqa: SLF001
    attached.detach()
