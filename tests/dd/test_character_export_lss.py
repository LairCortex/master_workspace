"""Дверь «Экспорт для LSS…» в D&D-табе (add-dnd-lss-generation, task 5.3;
spec dnd-character-export «Кнопка „Экспорт для LSS…“»).

Что живёт здесь — только лицо двери (сборка документа прикреплена в
``test_character_document_builder.py``, дерево доступности — в
``test_dd_accessibility.py``):

* панель файла — системная дверь (modeless-постулат PR-010 для окон, сам
  диалог — ``DontUseNativeDialog``); отвод не зовёт сборщика и не заводит
  ни одного окна (spec scenario «Сохранение отменено»);
* выбор пути зовёт сборщик один раз под замком сессии и его русское окно
  успеха; сбой сборщика — окно отказа с обещанием «карточка не изменена»,
  журнал — за ``_outcome``;
* снятый таб молчит: отменённая на release задача не показывает ничего;
* канал доступности: Press кнопки — та же дверь (панель вызвана, сборщик
  позван), не только мышиный click.
"""
from __future__ import annotations

import asyncio

from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QMessageBox, QPushButton

from app.dd.application.dataset_index_service import IndexSnapshot
from app.dd.domain.character import empty_ext
from app.dd.presentation import character_tab_frames as frames
from app.dd.presentation.character_tab_frames import EXPORT_FOR_LSS_TEXT

_EMPTY_SNAP = IndexSnapshot(ids=(), titles={}, sections={}, slugs={})


async def _drain(times: int = 10) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class _ExtService:
    async def get_ext(self, character_id):
        return empty_ext()


class _Index:
    async def snapshot(self):
        return _EMPTY_SNAP


class _Builder:
    """Сборщик документа как его видит рамка: запись вызовов, разный исход."""

    def __init__(self, *, fail: bool = False, hang: bool = False) -> None:
        self.calls: list[tuple[int, str]] = []
        self.fail = fail
        self._gate = asyncio.Event() if hang else None

    async def export_document(self, character_id: int, path: str) -> None:
        self.calls.append((character_id, path))
        if self._gate is not None:
            await self._gate.wait()
        if self.fail:
            raise OSError("диск отказался принять файл")


def _pick_save(monkeypatch, path: str) -> list[dict]:
    """Панель сохранения отвечает ``path`` (пустая строка — отвод); заодно
    записывает, кем и с какими аргументами была вызвана (постулат системной
    двери: русная Qt-панель, а не нативная)."""
    seen: list[dict] = []

    def _fake(*args, **kwargs):
        seen.append({"args": args, "kwargs": kwargs})
        return (path, "")

    monkeypatch.setattr(frames.QFileDialog, "getSaveFileName", staticmethod(_fake))
    return seen


def _boxes(parent) -> list[QMessageBox]:
    return [box for box in parent.findChildren(QMessageBox) if not box.isHidden()]


def _button(frame) -> QPushButton:
    button = frame.findChild(QPushButton, "ddDndExportLss")
    assert button is not None
    return button


async def _make_frame(qtbot, builder):
    frame = frames.DndCharacterTabFrame(
        character_id=7,
        service=_ExtService(),
        dataset_index=_Index(),
        record_labels={type_key: type_key for _slot, _s, type_key in frames.LINK_SLOTS},
        run_locked=lambda coro: asyncio.ensure_future(coro),
        document_builder=builder,
    )
    qtbot.addWidget(frame)
    frame.show()
    await _drain()
    return frame


# ── отвод: «пустой ход», ничего не изменено ─────────────────────────────────


async def test_cancelled_dialog_is_a_complete_noop(qtbot, monkeypatch):
    builder = _Builder()
    frame = await _make_frame(qtbot, builder)
    _pick_save(monkeypatch, "")

    _button(frame).click()
    await _drain()

    assert builder.calls == []  # сборщик не подходили
    assert _boxes(frame) == []  # и ни одного окна — тихий отвод


# ── запись: один вызов под замком и русское окно успеха ─────────────────────


async def test_chosen_path_collects_writes_and_reports_success(qtbot, monkeypatch, tmp_path):
    builder = _Builder()
    frame = await _make_frame(qtbot, builder)
    target = str(tmp_path / "character.json")
    seen = _pick_save(monkeypatch, target)

    _button(frame).click()
    await _drain()

    assert builder.calls == [(7, target)]
    # системная дверь вызвана с русным фильтром и без нативной панели (L1)
    call = seen[0]
    assert EXPORT_FOR_LSS_TEXT in call["args"]
    assert call["kwargs"]["options"] == frames.QFileDialog.Option.DontUseNativeDialog

    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert boxes[0].icon() == QMessageBox.Icon.Information
    assert "записан" in boxes[0].text()


async def test_failure_answers_russian_box_about_untouched_card(
    qtbot, monkeypatch, tmp_path
):
    builder = _Builder(fail=True)
    frame = await _make_frame(qtbot, builder)
    _pick_save(monkeypatch, str(tmp_path / "character.json"))

    _button(frame).click()
    await _drain()

    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert boxes[0].icon() == QMessageBox.Icon.Warning
    assert "не изменены" in boxes[0].text()


async def test_released_tab_stays_silent_about_an_in_flight_export(qtbot, monkeypatch):
    builder = _Builder(hang=True)
    frame = await _make_frame(qtbot, builder)
    _pick_save(monkeypatch, "/nowhere/character.json")

    _button(frame).click()
    await _drain()
    assert builder.calls == [(7, "/nowhere/character.json")]  # задача в полёте

    frame.release_tab()
    await _drain()
    assert _boxes(frame) == []  # отменённый экспорт не показывает ничего


# ── канал доступности: Press кнопки — та же дверь ───────────────────────────


async def test_accessibility_press_opens_the_very_door(qtbot, monkeypatch, tmp_path):
    builder = _Builder()
    frame = await _make_frame(qtbot, builder)
    target = str(tmp_path / "pressed.json")
    _pick_save(monkeypatch, target)

    button = _button(frame)
    iface = QAccessible.queryAccessibleInterface(button)
    assert iface is not None
    actions = iface.actionInterface()
    assert actions is not None and "Press" in list(actions.actionNames())
    actions.doAction("Press")
    qtbot.wait(250)  # animateClick's timer releases the click (the module's press() fact)
    await _drain()

    # Press открыл панель (заглушка вернула путь) и сборщик позван — одна и
    # та же дверь для мыши и для читалки, без координат
    assert builder.calls == [(7, target)]
    assert len(_boxes(frame)) == 1
