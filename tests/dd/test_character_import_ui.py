"""The import's UI doors, offscreen (add-dnd-game-face task 9.4; spec
dnd-character-import «Точки входа явные», «Перезапись требует подтверждения»).

Two entry points, one tree of answers:

* the module menu «Импорт персонажа из файла LSS…» — creation: the entry
  exists only when the import service was composed, an empty pick is a
  no-op, an unreadable file answers a Russian box without ever approaching
  the service, and every outcome (success with its warning list, refusal
  with the report lines, crash) gets its modeless box; a detach cancels an
  in-flight import in silence;
* the «D&D» tab buttons: «Перезаписать из файла LSS…» asks the service for
  the unconfirmed verdict, shows the Yes/No question ONLY for a clean
  document, and on Yes re-requests the very bytes of the first read;
  «Сохранить исходный файл…» prints the truth about a character with no
  stored snapshot;
* the no-dead-controls posture: without a composed service neither the
  menu entry nor the tab buttons exist at all.

The service door is a stub of canned outcomes; the decision tree itself
belongs to ``test_character_import_service.py`` — what lives here is only
which box the master sees and which request the screen dares to send.
"""
from __future__ import annotations

import asyncio
import types

from PySide6.QtWidgets import QMainWindow, QMessageBox, QPushButton

from app.dd import module as dd_module
from app.dd.application.character_import_service import (
    OVERWRITE_CONFIRM_BODY,
    CharacterImportOutcome,
    CharacterImportStatus,
)
from app.dd.application.dataset_index_service import IndexSnapshot
from app.dd.domain.character import LINK_SLOTS, empty_ext
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.dd.module import DD_CHARACTER_IMPORT_TITLE, DndModule
from app.dd.presentation import character_tab_frames as frames
from app.dd.presentation.character_tab_frames import (
    IMPORT_OVERWRITE_TEXT,
    SAVE_RAW_TEXT,
    DndCharacterTabFrame,
)
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


def _pick_save(monkeypatch, path: str) -> None:
    monkeypatch.setattr(
        frames.QFileDialog,
        "getSaveFileName",
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


# ── the «D&D» tab file doors ───────────────────────────────────────────────


class _TabService:
    def __init__(self) -> None:
        self.loads = 0

    async def get_ext(self, character_id):
        self.loads += 1
        return empty_ext()

    async def set_reference_link(self, character_id, slot, link):
        pass

    async def set_level(self, character_id, level):
        pass

    async def set_lss_sheet_id(self, character_id, sheet_id):
        pass


async def _open_tab(qtbot, importer) -> tuple[DndCharacterTabFrame, QMainWindow]:
    window = QMainWindow()
    qtbot.addWidget(window)
    frame = DndCharacterTabFrame(
        character_id=7,
        service=_TabService(),  # type: ignore[arg-type]
        dataset_index=types.SimpleNamespace(snapshot=lambda: _async_value(_EMPTY_SNAP)),
        record_labels={type_key: type_key for _slot, _s, type_key in LINK_SLOTS},
        run_locked=lambda coro: asyncio.ensure_future(coro),
        import_service=importer,
        parent=window,
    )
    await _drain()
    return frame, window


async def _async_value(value):
    return value


def _button(frame, object_name: str) -> QPushButton | None:
    return frame.findChild(QPushButton, object_name)


async def test_tab_without_a_service_prints_no_file_buttons(qtbot):
    frame, _window = await _open_tab(qtbot, None)
    assert _button(frame, "ddDndImportOverwrite") is None
    assert _button(frame, "ddDndSaveRaw") is None


async def test_overwrite_flow_question_yes_then_report_with_warnings(
    qtbot, monkeypatch, tmp_path
):
    good = tmp_path / "c.json"
    good.write_text("{}", encoding="utf-8")
    importer = _StubImporter(
        [
            CharacterImportOutcome(
                status=CharacterImportStatus.NEEDS_CONFIRMATION,
                character_id=7,
                message=OVERWRITE_CONFIRM_BODY,
            ),
            CharacterImportOutcome(
                status=CharacterImportStatus.OVERWRITTEN,
                character_id=7,
                name="Грог",
                message="Персонаж «Грог» перезаписан из файла LSS.",
                report=ValidationReport.of([_warn("data.avatar", "аватар пропущен")]),
            ),
        ]
    )
    frame, window = await _open_tab(qtbot, importer)
    loads_before = frame._service.loads  # noqa: SLF001
    overwrite_button = _button(frame, "ddDndImportOverwrite")
    assert overwrite_button.text() == IMPORT_OVERWRITE_TEXT
    assert _button(frame, "ddDndSaveRaw").text() == SAVE_RAW_TEXT
    _pick(monkeypatch, frames, str(good))
    overwrite_button.click()
    await _drain()
    questions = [b for b in _boxes(window) if b.icon() == QMessageBox.Icon.Question]
    assert len(questions) == 1
    assert questions[0].text() == OVERWRITE_CONFIRM_BODY
    assert importer.calls == [("{}", 7, False)]

    questions[0].button(QMessageBox.StandardButton.Yes).click()
    await _drain()
    assert importer.calls == [("{}", 7, False), ("{}", 7, True)]  # the very bytes
    boxes = _boxes(window)
    assert any("перезаписан из файла LSS" in b.text() for b in boxes)
    assert any("data.avatar — аватар пропущен" in b.text() for b in boxes)
    assert frame._service.loads > loads_before  # the tab face reloaded  # noqa: SLF001


async def test_overwrite_answered_no_requests_nothing(qtbot, monkeypatch, tmp_path):
    good = tmp_path / "c.json"
    good.write_text("{}", encoding="utf-8")
    importer = _StubImporter(
        [
            CharacterImportOutcome(
                status=CharacterImportStatus.NEEDS_CONFIRMATION,
                character_id=7,
                message=OVERWRITE_CONFIRM_BODY,
            )
        ]
    )
    frame, window = await _open_tab(qtbot, importer)
    _pick(monkeypatch, frames, str(good))
    _button(frame, "ddDndImportOverwrite").click()
    await _drain()
    question = [b for b in _boxes(window) if b.icon() == QMessageBox.Icon.Question][0]
    question.button(QMessageBox.StandardButton.No).click()
    await _drain()
    assert importer.calls == [("{}", 7, False)]  # the бездействие half


async def test_tab_refusal_answers_without_a_question_and_read_errors(
    qtbot, monkeypatch, tmp_path
):
    importer = _StubImporter(
        [
            CharacterImportOutcome(
                status=CharacterImportStatus.BLOCKED,
                report=ValidationReport.of([_err("jsonType", "чужой файл")]),
            )
        ]
    )
    frame, window = await _open_tab(qtbot, importer)
    bad = tmp_path / "bad.json"
    bad.write_text("{{{", encoding="utf-8")
    _pick(monkeypatch, frames, str(bad))
    _button(frame, "ddDndImportOverwrite").click()
    await _drain()
    boxes = _boxes(window)
    assert not any(b.icon() == QMessageBox.Icon.Question for b in boxes)
    assert "Импорт отклонён — отчёт проверки:" in boxes[-1].text()
    assert "jsonType — чужой файл" in boxes[-1].text()

    broken = tmp_path / "b2.json"
    broken.write_bytes(b"\xff\xfe")
    _pick(monkeypatch, frames, str(broken))
    _button(frame, "ddDndImportOverwrite").click()
    await _drain()
    assert "Не удалось прочитать файл" in _boxes(window)[-1].text()
    # The empty pick stays a no-op even with the buttons on screen.
    _pick(monkeypatch, frames, "")
    _button(frame, "ddDndImportOverwrite").click()
    await _drain()
    assert importer.calls == [
        ("{{{", 7, False)
    ]  # only the refusal read reached the service


async def test_tab_save_raw_all_three_answers(qtbot, monkeypatch, tmp_path):
    class _SaveStub(_StubImporter):
        def __init__(self, result: object) -> None:
            super().__init__([])
            self.result = result

        async def save_raw_document(self, character_id, path):
            self.calls.append(("save", character_id, path))
            return self.result

    target = str(tmp_path / "out.json")

    saved = _SaveStub(True)
    frame, window = await _open_tab(qtbot, saved)
    _pick_save(monkeypatch, target)
    _button(frame, "ddDndSaveRaw").click()
    await _drain()
    assert "байт-в-байт" in _boxes(window)[-1].text()
    assert saved.calls == [("save", 7, target)]

    empty = _SaveStub(False)
    frame2, window2 = await _open_tab(qtbot, empty)
    _pick_save(monkeypatch, target)
    _button(frame2, "ddDndSaveRaw").click()
    await _drain()
    assert "ещё не импортирован файл LSS" in _boxes(window2)[-1].text()

    class _BoomSave(_SaveStub):
        async def save_raw_document(self, character_id, path):
            raise OSError("диск отвалился")

    boom = _BoomSave(False)
    frame3, window3 = await _open_tab(qtbot, boom)
    _pick_save(monkeypatch, target)
    _button(frame3, "ddDndSaveRaw").click()
    await _drain()
    assert "Не удалось записать файл на диск" in _boxes(window3)[-1].text()

    refused = _SaveStub(True)
    frame4, window4 = await _open_tab(qtbot, refused)
    _pick_save(monkeypatch, "")  # the отвод
    _button(frame4, "ddDndSaveRaw").click()
    await _drain()
    assert refused.calls == []
    assert _boxes(window4) == []


async def test_tab_precheck_crash_answers_a_box(qtbot, monkeypatch, tmp_path):
    class _Boom(_StubImporter):
        async def import_character(self, content, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("сервис лёг")

    good = tmp_path / "c.json"
    good.write_text("{}", encoding="utf-8")
    frame, window = await _open_tab(qtbot, _Boom([]))
    _pick(monkeypatch, frames, str(good))
    _button(frame, "ddDndImportOverwrite").click()
    await _drain()
    assert "Не удалось проверить файл персонажа" in _boxes(window)[-1].text()


async def test_tab_confirmed_rerequest_crash_answers_a_box(
    qtbot, monkeypatch, tmp_path
):
    class _BoomSecond(_StubImporter):
        async def import_character(self, content, *, character_id=None, confirmed=False):
            self.calls.append((content, character_id, confirmed))
            if confirmed:
                raise RuntimeError("запись не прошла")
            return CharacterImportOutcome(
                status=CharacterImportStatus.NEEDS_CONFIRMATION,
                character_id=character_id,
                message=OVERWRITE_CONFIRM_BODY,
            )

    good = tmp_path / "c.json"
    good.write_text("{}", encoding="utf-8")
    frame, window = await _open_tab(qtbot, _BoomSecond([]))
    _pick(monkeypatch, frames, str(good))
    _button(frame, "ddDndImportOverwrite").click()
    await _drain()
    question = [b for b in _boxes(window) if b.icon() == QMessageBox.Icon.Question][0]
    question.button(QMessageBox.StandardButton.Yes).click()
    await _drain()
    assert "Импорт персонажа не завершился" in _boxes(window)[-1].text()


async def test_tab_report_belt_prints_the_confirmation_answer(qtbot):
    # The belt of _report_import_outcome: a confirmed request does not ask
    # twice — the honest message is printed once, as a plain notice.
    frame, window = await _open_tab(qtbot, _StubImporter([]))
    frame._report_import_outcome(  # noqa: SLF001 — the belt's own door
        CharacterImportOutcome(
            status=CharacterImportStatus.NEEDS_CONFIRMATION,
            message=OVERWRITE_CONFIRM_BODY,
        )
    )
    boxes = _boxes(window)
    assert boxes[-1].text() == OVERWRITE_CONFIRM_BODY
    assert boxes[-1].icon() == QMessageBox.Icon.Warning
