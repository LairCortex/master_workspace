"""Вкладка «Встреча» карточки события, offscreen (add-dnd-game-face task
11.1).

Кадр — модульная половина ядренного карточного таба (ядро-хост пинуются в
tests/presentation/test_card_group_tabs.py). Здесь пинуется читательский
контракт:

* загрузка: строки состава с выбранными монстрами, количества, заметка
  дословно; запись без надстройки — пустая подсказка и пустая заметка;
* монстр из сохранённого состава, которого бестиарий уже не знает, —
  журнальная строка и выпадение строки (призрачную строку нельзя ни показать
  picker'ом, ни пересохранить честно);
* staged-редактирование: «+» добавляет строку с первым монстром, «Убрать»
  снимает, подсказка пустоты переключается — до Save ничего не пишется;
* дверь Save (``save_tab``): пишется через сервис без повторного захвата
  лока, источник мирится на месте (apply_saved), а строка без монстра
  отдаёт русскую формулировку ворот прямо в коннектор;
* несохранённое лицо не пишется: загрузка не состоялась — сохранение есть
  журнальное ничего-не-делать (полувстречу карточка не создаёт и чужую
  встречу не удалит);
* ``release_tab`` гасит незавершённую загрузку в тишине.

Сервисы и источник — утки; настоящее дно хранилища пинует
test_encounter_storage.py.
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
)

from app.dd.domain.encounter import (
    COUNT_MAX,
    MONSTER_NOT_PICKED_REFUSAL,
    DdEncounter,
    EncounterEntry,
    normalize_entries,
    normalize_note,
)
from app.dd.presentation.dd_encounter_frame import ADD_ROW_TEXT, DndEncounterTabFrame

#: Та же строка, что живёт в кадре: UNSET-пункт комбобокса.
UNSET_TEXT = "— не выбрано"


async def _drain(times: int = 12) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


def _run_locked(coro):
    return asyncio.ensure_future(coro)


def _boxes(frame) -> list[QMessageBox]:
    # Постулат character_tab_frames: бокс modeless и переживает кадр; ищем
    # показанные (offscreen-кадр сам скрыт, children у скрытого родителя
    # отвечают isHidden() == True, пока box.show() не снял флаг).
    return [box for box in frame.findChildren(QMessageBox) if not box.isHidden()]


class _Monster:
    def __init__(self, mid, name):
        self.id = mid
        self.name = name


class _Monsters:
    def __init__(self, names):
        self.names = list(names)

    async def list_monsters(self):
        return [_Monster(index, name) for index, name in enumerate(self.names, 1)]


class _Encounters:
    """Утка сервиса в объёме дверей кадра; ворота — НАСТОЯЩИЕ
    (normalize_entries поднимает ту же русскую фразу, что и живая запись)."""

    def __init__(self, encounter=None, fail_load=False):
        self.encounter = encounter
        self.fail_load = fail_load
        self.saved = None  # (event_id, entries, note) последнего вызова

    async def get_encounter(self, event_id):
        if self.fail_load:
            raise RuntimeError("диск отказал")
        return self.encounter

    async def save_encounter(self, event_id, entries, note):
        self.saved = (event_id, entries, note)
        clean = normalize_entries(entries)
        if not clean:
            return None
        return DdEncounter(event_id, tuple(clean), normalize_note(note))


class _Source:
    def __init__(self):
        self.applied: list[tuple[int, bool]] = []

    def apply_saved(self, event_id, has_encounter):
        self.applied.append((event_id, has_encounter))


def _frame(encounters, monsters=("Гоблин", "Огр"), event_id=7):
    source = _Source()
    frame = DndEncounterTabFrame(
        event_id=event_id,
        encounter_service=encounters,
        monster_service=_Monsters(monsters),
        source=source,
        run_locked=_run_locked,
    )
    return frame, source


def _empty_hint(frame) -> QLabel:
    return frame.findChild(QLabel, "ddEncounterEmpty")


# ── загрузка ───────────────────────────────────────────────────────────────


async def test_load_publishes_composition_and_note():
    encounters = _Encounters(
        DdEncounter(
            event_id=7,
            entries=(
                EncounterEntry(2, 3, "Огр"),
                EncounterEntry(1, 1, "Гоблин"),
            ),
            note="на рассвете",
        )
    )
    frame, _source = _frame(encounters)
    await _drain()
    assert frame.findChild(QPlainTextEdit).toPlainText() == "на рассвете"
    combos = frame.findChildren(QComboBox)
    assert [combo.currentData() for combo in combos] == [2, 1]
    assert [combo.currentText() for combo in combos] == ["Огр", "Гоблин"]
    spins = frame.findChildren(QSpinBox)
    assert [spin.value() for spin in spins] == [3, 1]
    assert spins[0].minimum() == 1 and spins[0].maximum() == COUNT_MAX
    # Состав есть — подсказка пустоты убрана (явный hide).
    assert _empty_hint(frame).isHidden()


async def test_no_overlay_shows_the_empty_hint_and_an_empty_note():
    frame, _source = _frame(_Encounters(None))
    await _drain()
    assert not _empty_hint(frame).isHidden()
    assert frame.findChildren(QComboBox) == []
    note = frame.findChild(QPlainTextEdit)
    assert note.accessibleName() == "Заметка встречи"
    assert note.toPlainText() == ""


async def test_ghost_monster_row_drops_with_a_journal_line(caplog):
    encounters = _Encounters(
        DdEncounter(
            event_id=7,
            entries=(
                EncounterEntry(9, 2, "Бу"),  # бестиарий его не знает
                EncounterEntry(1, 1, "Гоблин"),
            ),
            note="",
        )
    )
    frame, _source = _frame(encounters)
    with caplog.at_level(logging.WARNING, logger="app.dd.encounter_tab"):
        await _drain()
    combos = frame.findChildren(QComboBox)
    assert [combo.currentData() for combo in combos] == [1]
    assert any("не найден в бестиарии" in r.getMessage() for r in caplog.records)


async def test_failed_load_is_one_modeless_box():
    frame, _source = _frame(_Encounters(fail_load=True))
    await _drain()
    boxes = _boxes(frame)
    assert len(boxes) == 1
    assert "Не удалось загрузить встречу" in boxes[0].text()


async def test_save_of_a_never_read_face_writes_nothing(caplog):
    """Загрузка не состоялась — сохранение есть журнальное
    ничего-не-делать: кадр не удаляет надстройку, которой не видел."""
    encounters = _Encounters(fail_load=True)
    frame, source = _frame(encounters)
    await _drain()
    with caplog.at_level(logging.WARNING, logger="app.dd.encounter_tab"):
        await frame.save_tab()
    assert encounters.saved is None
    assert source.applied == []
    assert any("не было прочитано" in r.getMessage() for r in caplog.records)


# ── staged-редактирование ──────────────────────────────────────────────────


async def test_add_and_remove_rows_stage_without_writing():
    encounters = _Encounters(None)
    frame, source = _frame(encounters)
    await _drain()
    add = frame.findChild(QPushButton, "ddEncounterAdd")
    assert add.text() == ADD_ROW_TEXT
    add.click()
    assert len(frame.findChildren(QComboBox)) == 1
    combo = frame.findChildren(QComboBox)[0]
    assert combo.currentData() == 1  # «+» — намерение, а не ловушка
    assert combo.itemText(0) == UNSET_TEXT
    assert combo.accessibleName() == "Монстр"
    frame.findChild(QPushButton, "ddEncounterAdd").click()
    assert len(frame.findChildren(QComboBox)) == 2
    assert _empty_hint(frame).isHidden()
    frame.findChildren(QPushButton, "ddEncounterRemove")[0].click()
    combos = frame.findChildren(QComboBox)
    assert len(combos) == 1
    assert combos[0].currentData() == 1  # снята ПЕРВАЯ строка
    frame.findChildren(QPushButton, "ddEncounterRemove")[0].click()
    assert frame.findChildren(QComboBox) == []
    assert not _empty_hint(frame).isHidden()
    # staged: до Save хранилище и источник не тронуты
    assert encounters.saved is None
    assert source.applied == []


# ── дверь Save ─────────────────────────────────────────────────────────────


async def test_save_writes_staged_face_and_reconciles_the_source():
    encounters = _Encounters(None)
    frame, source = _frame(encounters)
    await _drain()
    frame.findChild(QPushButton, "ddEncounterAdd").click()
    combo = frame.findChildren(QComboBox)[0]
    combo.setCurrentIndex(2)  # Огр
    spin = frame.findChildren(QSpinBox)[0]
    assert spin.accessibleName() == "Количество"
    spin.setValue(4)
    frame.findChild(QPlainTextEdit).setPlainText("засада у брода")
    await frame.save_tab()
    event_id, entries, note = encounters.saved
    assert (event_id, note) == (7, "засада у брода")
    assert entries == [EncounterEntry(2, 4, "Огр")]
    assert source.applied == [(7, True)]


async def test_empty_save_removes_the_overlay_and_says_so_to_the_source():
    encounters = _Encounters(DdEncounter(7, (EncounterEntry(1, 1, "Гоблин"),), ""))
    frame, source = _frame(encounters)
    await _drain()
    frame.findChildren(QPushButton, "ddEncounterRemove")[0].click()
    await frame.save_tab()
    assert encounters.saved is not None and encounters.saved[1] == []
    assert source.applied == [(7, False)]


async def test_unpicked_row_raises_the_gate_at_the_connector():
    """«— не выбрано» дожил до Save (пользователь вернул UNSET обратно):
    ворота домена отвечают русской формулировкой прямо в коннектор,
    карточка остаётся открытой для починки."""
    encounters = _Encounters(None)
    frame, source = _frame(encounters, monsters=("Гоблин",))
    await _drain()
    frame.findChild(QPushButton, "ddEncounterAdd").click()
    frame.findChildren(QComboBox)[0].setCurrentIndex(0)  # обратно в UNSET
    with pytest.raises(ValueError) as exc:
        await frame.save_tab()
    assert str(exc.value) == MONSTER_NOT_PICKED_REFUSAL
    assert source.applied == []


async def test_release_tab_cancels_the_load_in_silence():
    started = asyncio.Event()
    encounters = _Encounters(None)

    async def slow_get(event_id):
        started.set()
        await asyncio.sleep(10)
        return None

    encounters.get_encounter = slow_get
    frame, _source = _frame(encounters)
    await started.wait()
    await _drain()
    frame.release_tab()
    await _drain()
    assert _boxes(frame) == []
