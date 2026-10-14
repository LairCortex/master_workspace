"""Дверь «Экспорт для LSS…» на блочном канале «Основного» (add-dnd-lss-
generation, задача 5.3; дверь переехала с D&D-таба в dd-card-redesign 5.5;
spec dnd-character-export «Кнопка „Экспорт для LSS…“»).

Лицо двери — опция блока «lss_doors» — и её Press-канал пинят
``tests/presentation/test_module_blocks_render.py``; общие ветки (отвод без
вызова сборщика, один звонок, гейты) — в ``test_character_main_blocks.py``.
Здесь остаётся дверной контракт у диска: панель вызывается системная (русская
подпись, без нативной панели), точные русские тексты успеха и отказа, и
постулат release: экспорт в полёте снимается молча.
"""
from __future__ import annotations

import asyncio

from PySide6.QtWidgets import QMessageBox, QWidget

from app.dd.application.dataset_index_service import IndexSnapshot
from app.dd.domain.character import LINK_SLOTS, empty_ext
from app.dd.domain.character_mechanics import CharacterMechanics
from app.dd.presentation import character_main_blocks as blocks
from app.dd.presentation.character_main_blocks import (
    DOORS_BLOCK_ID,
    CharacterMainBlockController,
)
from app.dd.presentation.character_tab_frames import (
    CHARACTER_FILE_FILTER,
    EXPORT_FOR_LSS_TEXT,
)


async def _drain(times: int = 10) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class _ExtService:
    async def get_ext(self, character_id):
        return empty_ext()

    async def get_mechanics(self, character_id):
        return CharacterMechanics()


class _Index:
    async def snapshot(self):
        return IndexSnapshot(ids=(), titles={}, sections={}, slugs={})


class _Builder:
    """Сборщик документа как его видит контроллер: запись вызовов, разный
    исход, опциональный гейт для «экспорта в полёте»."""

    def __init__(self, *, fail: bool = False, hang: bool = False) -> None:
        self.calls: list[tuple[int, str]] = []
        self.fail = fail
        self.gate = asyncio.Event() if hang else None

    async def export_document(self, character_id: int, path: str) -> None:
        self.calls.append((character_id, path))
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise OSError("диск отказался принять файл")


def _pick_save(monkeypatch, path: str) -> list[dict]:
    """Панель сохранения отвечает ``path``; заодно записывает, кем и с какими
    аргументами была вызвана (постулат системной двери: русная Qt-панель, а
    не нативная; тот же постулат пинит глобальный whitelist-тест
    ``test_interface_language`` — здесь он замкнут на саму дверь)."""
    seen: list[dict] = []

    def _fake(*args, **kwargs):
        seen.append({"args": args, "kwargs": kwargs})
        return (path, "")

    monkeypatch.setattr(
        blocks.QFileDialog, "getSaveFileName", staticmethod(_fake)
    )
    return seen


def _boxes(parent) -> list[QMessageBox]:
    return [box for box in parent.findChildren(QMessageBox) if not box.isHidden()]


def _make_controller(qtbot, builder):
    dialog = QWidget()
    qtbot.addWidget(dialog)
    controller = CharacterMainBlockController(
        character_id=7,
        service=_ExtService(),  # type: ignore[arg-type]
        dataset_index=_Index(),  # type: ignore[arg-type]
        record_labels={type_key: type_key for _slot, _s, type_key in LINK_SLOTS},
        run_locked=lambda coro: asyncio.ensure_future(coro),
        dialog=dialog,
        republish=lambda entries, hidden: None,
        document_builder=builder,
    )
    return controller, dialog


# ── запись: системная панель, один вызов, русское окно успеха ───────────────


async def test_chosen_path_uses_the_system_panel_and_reports_success(
    qtbot, monkeypatch, tmp_path
):
    builder = _Builder()
    controller, dialog = _make_controller(qtbot, builder)
    target = str(tmp_path / "character.json")
    seen = _pick_save(monkeypatch, target)
    await _drain()

    controller.handle_write(DOORS_BLOCK_ID, "export", True)
    await _drain()

    assert builder.calls == [(7, target)]
    # системная дверь вызвана с русным фильтром и без нативной панели (L1)
    call = seen[0]
    assert EXPORT_FOR_LSS_TEXT in call["args"]
    assert CHARACTER_FILE_FILTER in call["args"]
    assert call["kwargs"]["options"] == blocks.QFileDialog.Option.DontUseNativeDialog

    boxes = _boxes(dialog)
    assert len(boxes) == 1
    assert boxes[0].icon() == QMessageBox.Icon.Information
    assert "записан" in boxes[0].text()


async def test_failure_answers_russian_box_about_untouched_card(
    qtbot, monkeypatch, tmp_path
):
    builder = _Builder(fail=True)
    controller, dialog = _make_controller(qtbot, builder)
    _pick_save(monkeypatch, str(tmp_path / "character.json"))
    await _drain()

    controller.handle_write(DOORS_BLOCK_ID, "export", True)
    await _drain()

    boxes = _boxes(dialog)
    assert len(boxes) == 1
    assert boxes[0].icon() == QMessageBox.Icon.Warning
    assert "не изменены" in boxes[0].text()


async def test_released_card_stays_silent_about_an_in_flight_export(
    qtbot, monkeypatch
):
    builder = _Builder(hang=True)
    controller, dialog = _make_controller(qtbot, builder)
    _pick_save(monkeypatch, "/nowhere/character.json")
    await _drain()

    controller.handle_write(DOORS_BLOCK_ID, "export", True)
    await _drain()
    assert builder.calls == [(7, "/nowhere/character.json")]  # задача в полёте

    controller.release()
    await _drain()
    assert _boxes(dialog) == []  # отменённый экспорт не показывает ничего
    builder.gate.set()
    await _drain()
