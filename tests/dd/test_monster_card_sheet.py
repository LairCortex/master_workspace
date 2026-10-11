"""Карточка монстра — создание и правка (add-dnd-game-face task 10.1;
spec dnd-bestiary «Создание и правка — карточкой с табами»).

Оффскрин-контур как у листа справочника: хост-окно и настоящий коннектор
(run_locked — та же блокированная дверь, что в бою), сервис — утка с ЧЕСТНЫМИ
доменными воротами (тот же normalize_name/validate_rating/normalize_blocks,
что у настоящего сервиса): отказ карточка печатает русским, остаётся открытой
и сохраняет набросок мастера (потерянный текст — баг, ради предотвращения
которого написана строка-уведомление).

Покрыты: табы «Обзор»/«Тексты», спиннинг рейтинга 1..20, загрузка строки
(заголовок = имя, поля, блоки, превью картинки), исчезнувший монстр — отказ
и заблокированная кнопка сохранения, добавление/правка/удаление строк блоков
и пустые заголовки вне словаря, выбор картинки из диалога (валидная —
pending + превью, невалидная — ранний отказ без pending, нечитаемый файл —
свой отказ, отвод — молчание), «убрать изображение» как pending clear,
одиночный save, отмена обеих задач при закрытии, и мёртвый холст: каждый
путь после await проверяет живость (PR-037) и не трогает ушедший виджет.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import (
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
)

from app.dd.application.monster_service import MONSTER_GONE_REFUSAL
from app.dd.domain.monster import (
    NAME_REFUSAL,
    RATING_MAX,
    RATING_MIN,
    DdMonster,
    normalize_blocks,
    normalize_name,
    validate_rating,
)
from app.dd.presentation.monster_card_sheet import (
    DD_MONSTER_CARD_NEW_TITLE,
    DD_MONSTER_IMAGE_UNDECODABLE,
    DD_MONSTER_SAVED_TEXT,
    DD_MONSTER_TAB_OVERVIEW,
    DD_MONSTER_TAB_TEXTS,
    DndMonsterCardSheet,
)
from app.presentation.wiring import ApplicationWiring

# Минимальный настоящий PNG (1×1) — QPixmap обязан его декодировать.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


class _Service:
    """Утка DdMonsterService с честными доменными воротами и записью вызовов.
    Ворота — ПЕРЕД записью вызова, как в настоящем сервисе: отказанный сейв
    не оставляет и следа (для карточки важно, что сохранено ровно一度)."""

    def __init__(self, monsters=(), previews=None) -> None:
        self.monsters = {m.id: m for m in monsters}
        self.next_id = max(self.monsters, default=0) + 1
        self.previews = dict(previews or {})
        self.saves: list[dict] = []

    async def get_monster(self, monster_id):
        return self.monsters.get(monster_id)

    async def image_preview_path(self, image_id):
        return self.previews.get(image_id)

    async def save_monster(
        self, *, monster_id, name, rating, blocks, image_data=None, clear_image=False
    ):
        clean_name = normalize_name(name)
        clean_rating = validate_rating(rating)
        clean_blocks = normalize_blocks(blocks)
        self.saves.append(
            {
                "monster_id": monster_id,
                "name": name,
                "rating": rating,
                "blocks": dict(blocks),
                "image_data": image_data,
                "clear_image": clear_image,
            }
        )
        if monster_id is None:
            monster_id = self.next_id
            self.next_id += 1
            image_id = None
        else:
            image_id = self.monsters[monster_id].image_id
        if image_data is not None:
            image_id = 99
        elif clear_image:
            image_id = None
        monster = DdMonster(
            id=monster_id,
            name=clean_name,
            rating=clean_rating,
            blocks=clean_blocks,
            image_id=image_id,
        )
        self.monsters[monster_id] = monster
        return monster


class _FileDialogStub:
    """Замена имени QFileDialog в модуле карточки: контракт вызова живёт в
    карточке, тест подсовывает ответ и следит, что русская панель включена
    (DontUseNativeDialog — конвенция всех файловых диалогов приложения)."""

    Option = QFileDialog.Option
    answer: tuple[str, str] = ("", "")
    calls: list[dict] = []

    @staticmethod
    def getOpenFileName(*args, **kwargs):
        _FileDialogStub.calls.append({"args": args, "kwargs": kwargs})
        return _FileDialogStub.answer


def _monster(mid=1, name="Гоблин", rating=2, blocks=None, image_id=None):
    return DdMonster(
        id=mid,
        name=name,
        rating=rating,
        blocks=dict(blocks or {}),
        image_id=image_id,
    )


def _make_card(qtbot, service, monster_id=None, source=None, saved=None):
    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    app = SimpleNamespace(_image_store=None, _theme=None)
    wiring = ApplicationWiring(
        app, window, None, None, None, None, None, SimpleNamespace(lock=asyncio.Lock())
    )
    card = DndMonsterCardSheet(
        monster_id,
        service,
        wiring.run_locked,
        saved if saved is not None else lambda c: None,
        source=source,
        parent=window,
    )
    wiring.open_sheet(card)
    return card


def _buttons(card, object_name):
    return [b for b in card.findChildren(QPushButton) if b.objectName() == object_name]


def _rows(card):
    """Живые строки блоков: поля заголовка и текста каждой строки."""
    out = []
    for title in card.findChildren(QLineEdit, "ddMonsterBlockTitle"):
        body = title.parent().findChild(QPlainTextEdit)
        out.append((title, body))
    return out


async def _settle(card) -> None:
    if card._load_task is not None:
        await card._load_task


def _png_file(tmp: Path, name="pic.png") -> Path:
    path = tmp / name
    path.write_bytes(PNG)
    return path


async def test_new_card_fields_tabs_and_the_two_saves(qtbot):
    service = _Service()
    saved: list = []
    card = _make_card(qtbot, service, saved=saved.append)
    try:
        assert card.windowTitle() == DD_MONSTER_CARD_NEW_TITLE
        tabs = card.findChild(QTabWidget, "ddMonsterTabs")
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            DD_MONSTER_TAB_OVERVIEW,
            DD_MONSTER_TAB_TEXTS,
        ]
        assert (card._rating.minimum(), card._rating.maximum()) == (
            RATING_MIN,
            RATING_MAX,
        )
        assert card._load_task is None  # создавать нечего — загрузка не стартует
        # пустое имя — отказ сервиса русским, карточка жива, набросок цел
        card._name.setText("   ")
        card._save_button.click()
        await card._save_task
        assert card._notice.text() == NAME_REFUSAL
        assert card._notice.isVisible()
        assert card.monster_id is None and service.saves == []
        # первое сохранение — новое id, заголовок = имя, on_saved фасада
        card._name.setText("  Огр  ")
        card._rating.setValue(5)
        card._save_button.click()
        await card._save_task
        assert service.saves[0]["monster_id"] is None
        assert service.saves[0]["name"] == "  Огр  "  # нормализует сервис
        assert card.monster_id == 1
        assert card.windowTitle() == "Огр" and card._name.text() == "Огр"
        assert card._rating.value() == 5
        assert card._notice.text() == DD_MONSTER_SAVED_TEXT
        assert saved == [card]
    finally:
        card.close()


async def test_load_fills_fields_blocks_and_picture(qtbot, tmp_path):
    preview = _png_file(tmp_path, "gob.png")
    service = _Service(
        [_monster(1, "Гоблин", 3, {"Нрав": "Трус."}, image_id=7)],
        previews={7: preview},
    )
    card = _make_card(qtbot, service, monster_id=1)
    try:
        await _settle(card)
        assert card.windowTitle() == "Гоблин"
        assert card._name.text() == "Гоблин" and card._rating.value() == 3
        assert [(t.text(), b.toPlainText()) for t, b in _rows(card)] == [
            ("Нрав", "Трус.")
        ]
        assert not card._thumb.pixmap().isNull()
        assert card._thumb.text() == ""
    finally:
        card.close()


async def test_vanished_monster_refuses_and_bars_save(qtbot):
    service = _Service([])
    card = _make_card(qtbot, service, monster_id=42)
    try:
        await _settle(card)
        assert card._notice.text() == MONSTER_GONE_REFUSAL
        assert not card._save_button.isEnabled()
    finally:
        card.close()


async def test_block_rows_order_removal_and_titleless_drop(qtbot):
    service = _Service([_monster(1, "Огр", 1, {"Атака": "Дубина.", "Нрав": "Туп."})])
    card = _make_card(qtbot, service, monster_id=1)
    try:
        await _settle(card)
        _buttons(card, "ddMonsterBlockAdd")[0].click()
        rows = _rows(card)
        assert len(rows) == 3
        # удаление средней строки — её текст уходит из словаря
        rows[1][0].parent().findChild(
            QPushButton, "ddMonsterBlockRemove"
        ).click()
        card._save_button.click()
        await card._save_task
        # пустой заголовок добавленной не заполненной строки — вне словаря;
        # после переразки экрана rows = ровно хранимые пары
        assert service.saves[0]["blocks"] == {"Атака": "Дубина."}
        assert [(t.text(), b.toPlainText()) for t, b in _rows(card)] == [
            ("Атака", "Дубина."),
        ]
    finally:
        card.close()


async def test_pick_image_valid_pending_then_stored_preview(qtbot, tmp_path, monkeypatch):
    picked = _png_file(tmp_path, "picked.png")
    stored = _png_file(tmp_path, "stored.png")
    service = _Service([_monster(1, "Волк", 2)])
    service.previews[99] = stored
    import app.dd.presentation.monster_card_sheet as mod

    _FileDialogStub.calls = []
    _FileDialogStub.answer = (str(picked), "")
    monkeypatch.setattr(mod, "QFileDialog", _FileDialogStub)
    card = _make_card(qtbot, service, monster_id=1)
    try:
        await _settle(card)
        _buttons(card, "ddMonsterImagePick")[0].click()
        # русская панель — конвенция каждого файлового диалога
        assert (
            _FileDialogStub.calls[0]["kwargs"]["options"]
            == QFileDialog.Option.DontUseNativeDialog
        )
        assert card._pending_image == PNG
        assert card._clear_image is False
        assert not card._thumb.pixmap().isNull()
        assert card._notice.isHidden()  # удачный выбор чистит прежний отказ
        card._save_button.click()
        await card._save_task
        assert service.saves[0]["image_data"] == PNG
        # превью перенацелено на ХРАНИМЫЙ файл (витрины покажут его), bytes
        # больше не pending
        assert card._pending_image is None
        assert not card._thumb.pixmap().isNull()
        assert card._thumb.text() == ""
    finally:
        card.close()


async def test_pick_undecodable_and_unreadable_are_early_refusals(
    qtbot, tmp_path, monkeypatch
):
    import app.dd.presentation.monster_card_sheet as mod

    junk = tmp_path / "notes.txt"
    junk.write_text("не картинка", encoding="utf-8")
    service = _Service([_monster(1, "Волк")])
    card = _make_card(qtbot, service, monster_id=1)
    try:
        await _settle(card)
        _FileDialogStub.calls = []
        monkeypatch.setattr(mod, "QFileDialog", _FileDialogStub)
        _FileDialogStub.answer = (str(junk), "")
        _buttons(card, "ddMonsterImagePick")[0].click()
        assert card._notice.text() == DD_MONSTER_IMAGE_UNDECODABLE
        assert card._pending_image is None
        _FileDialogStub.answer = (str(tmp_path / "нет.png"), "")
        _buttons(card, "ddMonsterImagePick")[0].click()
        assert "не удалось прочитать файл" in card._notice.text()
        assert card._pending_image is None
        # отвод диалога (пустой путь) — вообще без строки и без pending
        _FileDialogStub.answer = ("", "")
        card._set_notice("")
        _buttons(card, "ddMonsterImagePick")[0].click()
        assert card._notice.isHidden() and card._pending_image is None
    finally:
        card.close()


async def test_remove_image_pending_clear_lands_on_save(qtbot, tmp_path):
    preview = _png_file(tmp_path, "p.png")
    service = _Service([_monster(1, "Волк", 2, image_id=7)], previews={7: preview})
    card = _make_card(qtbot, service, monster_id=1)
    try:
        await _settle(card)
        assert not card._thumb.pixmap().isNull()
        _buttons(card, "ddMonsterImageRemove")[0].click()
        assert card._clear_image is True and card._pending_image is None
        assert card._thumb.text() == "Нет изображения"
        card._save_button.click()
        await card._save_task
        assert service.saves[0]["clear_image"] is True
        assert card._thumb.text() == "Нет изображения"  # не вернулось с переразки
    finally:
        card.close()


async def test_single_save_inflight_and_close_kills_both_tasks(qtbot):
    gate = asyncio.Event()

    class _Slow(_Service):
        async def get_monster(self, monster_id):
            await gate.wait()
            return self.monsters.get(monster_id)

        async def save_monster(self, **kw):
            await gate.wait()
            return await super().save_monster(**kw)

    service = _Slow([_monster(1, "Гоблин")])
    card = _make_card(qtbot, service, monster_id=1)
    load_task = card._load_task
    gate.set()
    await load_task
    card._name.setText("Гоблин")
    card._save_button.click()
    save = card._save_task
    card._save_button.click()  # в полёте — тот же таск, второй гонки нет
    assert card._save_task is save
    card.close()  # done() снимает обе двери
    with pytest.raises(asyncio.CancelledError):
        await save


async def test_cancel_button_closes_without_write(qtbot):
    service = _Service([_monster(1, "Гоблин")])
    card = _make_card(qtbot, service, monster_id=1)
    await _settle(card)
    _buttons(card, "ddMonsterCancel")[0].click()
    assert not card.isVisible() and service.saves == []


async def test_live_canvas_generic_error_prints_the_storage_line(qtbot):
    """Хранимая ошибка живого холста — русская строка в уведомлении, карточка
    открыта, набросок цел (никогда не коробка поверх живого листа, PR-010)."""

    class _Boom(_Service):
        async def save_monster(self, **kw):
            raise RuntimeError("диск кончился")

    card = _make_card(qtbot, _Boom([]))
    try:
        card._name.setText("Огр")
        card._save_button.click()
        await card._save_task
        assert card._notice.isVisible()
        assert "не удалось сохранить монстра" in card._notice.text()
        assert "диск кончился" in card._notice.text()
        assert card.isVisible() and card.monster_id is None
    finally:
        card.close()


async def test_canvas_dying_during_warm_leaves_the_card_untouched(qtbot, monkeypatch):
    """Путь 439: холст умер между warm источника и применением результата —
    id/заголовок/уведомление не трогаем, фасад не получает on_saved."""
    import app.dd.presentation.monster_card_sheet as mod

    class _DyingSource:
        async def warm(self):
            monkeypatch.setattr(mod.shiboken6, "isValid", lambda obj: False)

    service = _Service()
    saved: list = []
    card = _make_card(qtbot, service, source=_DyingSource(), saved=saved.append)
    try:
        card._name.setText("Огр")
        card._save_button.click()
        await card._save_task
        assert service.saves and card.monster_id is None
        assert card._notice.isHidden() and saved == []
    finally:
        monkeypatch.undo()
        card.close()


async def test_load_guard_after_the_door_returns(qtbot, monkeypatch):
    """Монстр вернулся из-за двери, а холст уже умер (лист закрыли, пока
    читали): поля не заполняем, заголовок остаётся заготовочным."""
    import app.dd.presentation.monster_card_sheet as mod

    service = _Service([_monster(1, "Гоблин", 3)])
    card = _make_card(qtbot, service, monster_id=1)
    monkeypatch.setattr(mod.shiboken6, "isValid", lambda obj: False)
    try:
        await card._load_task
        assert card._name.text() == "" and card.windowTitle() == "Монстр"
    finally:
        monkeypatch.undo()
        card.close()


async def test_dead_canvas_answers_nothing_on_every_await_path(
    qtbot, tmp_path, monkeypatch
):
    """PR-037 на всех дверях выхода после await: отказ сервиса, хранимая
    ошибка и успех — каждый проверяет живость холста (patch isValid —
    честная имитация удалённого C++ при живом Python-обёртке)."""
    import app.dd.presentation.monster_card_sheet as mod

    service = _Service([_monster(1, "Гоблин")])
    card = _make_card(qtbot, service, monster_id=1)
    await _settle(card)
    monkeypatch.setattr(mod.shiboken6, "isValid", lambda obj: False)
    try:
        card._name.setText("   ")  # ValueError-путь
        card._save_button.click()
        await card._save_task
        assert card._notice.text() == ""

        class _Boom(_Service):
            async def save_monster(self, **kw):
                raise RuntimeError("диск кончился")

        card._service = _Boom([_monster(1, "Гоблин")])
        card._save_button.click()
        await card._save_task
        assert card._notice.text() == ""  # generic-путь тоже молчит на мёртвом

        card._service = service
        card._save_button.click()  # успех: поля/id/уведомление — за guard'ом
        await card._save_task
        assert card._notice.isHidden()
    finally:
        monkeypatch.undo()
        card.close()


async def test_preview_path_without_a_readable_image_stays_placeholder(
    qtbot, tmp_path
):
    junk = tmp_path / "broken.png"
    junk.write_bytes(b"not a png")
    service = _Service([_monster(1, image_id=7)], previews={7: junk})
    card = _make_card(qtbot, service, monster_id=1)
    try:
        await _settle(card)
        assert card._thumb.text() == "Нет изображения"
    finally:
        card.close()
