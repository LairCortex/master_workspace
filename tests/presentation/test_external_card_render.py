"""Рендер внешней карточки в общей слот-машине колонки (add-dnd-game-face,
task 6.1; spec entity-preview «Карточка внешней сущности — приборная отделка
только для чтения», dnd-reference-records).

``EntityCardViewModel`` принимает протокольную ``ExternalCardSource`` — и
строит из неё ровно приборную панель: заголовок «Карточка: <тип>» по реестру
(имя — поле карточки, не заголовок), строка «Источник: …», текстовые блоки
поставщика через тот же mention-генератор, связи-переходы секциями по типу
(капча — множественное имя реестра, порядок — первое появление), картинка
общим пайплайном (нет файла/битый — плейсхолдер-строка). Ни рейтинга, ни дат,
ни возраста, ни музыки у записи не выдумывается; контролов правки здесь нет
ни одного — их нет и у read-only острова.
"""
from __future__ import annotations

import contextlib

from PySide6.QtGui import QPixmap

from app.domain import entity_registry as reg
from app.presentation.modules.protocol import (
    ExternalCardSource,
    ExternalRelation,
    ExternalTextBlock,
)
from app.presentation.viewmodels.entity_card_view_model import (
    EntityCardViewModel,
    content_fingerprint,
    external_content_fingerprint,
)


@contextlib.contextmanager
def _external_types(*specs: tuple[str, str, str]):
    """Регистрация внешних типов на тест (реестр — состояние процесса)."""
    saved = dict(reg._EXTERNAL)
    reg.register_external(
        tuple(
            reg.ExternalTypeDescriptor(
                key=key, label=label, plural_label=plural, icon_key="crosshair"
            )
            for key, label, plural in specs
        )
    )
    try:
        yield
    finally:
        reg._EXTERNAL.clear()
        reg._EXTERNAL.update(saved)


def _vm(card: ExternalCardSource, entity_type: str = "dd_feat", **flags):
    from app.presentation.viewmodels.entity_preview_view_model import (
        PIN_STATE_UNPIN,
    )

    flags.setdefault("pin_state", PIN_STATE_UNPIN)
    return EntityCardViewModel(entity_type, card, pinned=False, slot_index=0, **flags)


def _pane(card: ExternalCardSource, entity_type: str = "dd_feat", **flags) -> dict:
    # pane-слова разворота — лицо колонки; для внешней карточки они ничего
    # не меняют, панель строится штатным вызовом с двумя флагами
    return _vm(card, entity_type, **flags).pane(
        can_fullsize=False, fullsize=False
    )


def test_read_only_band_and_blocks():
    """Заголовок — тип из реестра, не имя; строка источника; пустой origin —
    пустая строка (остров её не рисует); блоки — поштучно, пустой текст
    блока не рисует секцию; рейтинг/даты/возраст/музыка — пусто."""
    with _external_types(("dd_feat", "Черта", "Черты")):
        card = ExternalCardSource(
            name="Везучесть",
            origin="SRD 5.1 (2014)",
            blocks=(
                ExternalTextBlock("Текст", "Один раз спасает"),
                ExternalTextBlock("Пусто", "   "),
            ),
            source_id="srd51/lucky",
        )
        pane = _pane(card)
        assert pane["title"] == "Карточка: Черта"
        assert pane["nameText"] == "Везучесть"
        assert pane["originText"] == "Источник: SRD 5.1 (2014)"
        assert pane["ratingText"] == pane["dateText"] == pane["ageText"] == ""
        assert pane["musicUrl"] == ""
        assert pane["imageSource"] == ""  # файла нет — плейсхолдер
        assert [s["label"] for s in pane["sections"]] == ["Текст"]
        assert "Один раз спасает" in pane["sections"][0]["html"]
        assert pane["relatedSections"] == []
        # идентичность пары едет на самой записи (штамп коннектора, protocol)
        assert pane["entityId"] == "srd51/lucky"
        assert pane["slotKey"] == "dd_feat/srd51/lucky#live"

        bare = _pane(ExternalCardSource(name="Клейрик", origin=""))
        assert bare["originText"] == ""


def test_relations_group_by_type_first_appearance():
    """Связи-переходы — секциями по целевому типу: порядок секций по первому
    появлению, капча — множественное имя реестра, строка несёт пару
    (тип, source_id) для перехода кликом в колонку."""
    with _external_types(
        ("dd_feat", "Черта", "Черты"),
        ("dd_subclass", "Подкласс", "Подклассы"),
    ):
        card = ExternalCardSource(
            name="Жизнь",
            origin="SRD",
            relations=(
                ExternalRelation("dd_subclass", "srd/life", "Жизнь"),
                ExternalRelation("dd_feat", "srd/lucky", "Везучесть"),
                ExternalRelation("dd_subclass", "srd/tempest", "Шторм"),
            ),
            source_id="srd51/cleric",
        )
        sections = _pane(card, entity_type="dd_subclass")["relatedSections"]
        assert [(s["key"], s["label"]) for s in sections] == [
            ("dd_subclass", "Подклассы"),
            ("dd_feat", "Черты"),
        ]
        assert sections[0]["rows"] == [
            {"name": "Жизнь", "type": "dd_subclass", "id": "srd/life"},
            {"name": "Шторм", "type": "dd_subclass", "id": "srd/tempest"},
        ]
        assert sections[1]["rows"] == [
            {"name": "Везучесть", "type": "dd_feat", "id": "srd/lucky"}
        ]


def test_picture_through_the_shared_pipeline(tmp_path):
    """Картинка записи — тем же плейслотом, что и у ядра: живой файл даёт
    file:// URL, пропавший и битый — пустую строку-плейсхолдер."""
    good = tmp_path / "picture.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill("red")
    assert pixmap.save(str(good))
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"definitely not a png")
    with _external_types(("dd_feat", "Черта", "Черты")):
        assert _pane(ExternalCardSource(name="а", origin="", picture_path=str(good)))[
            "imageSource"
        ].startswith("file://")
        gone = _pane(
            ExternalCardSource(name="а", origin="", picture_path=str(tmp_path / "x.png"))
        )
        assert gone["imageSource"] == ""
        rotten = _pane(ExternalCardSource(name="а", origin="", picture_path=str(broken)))
        assert rotten["imageSource"] == ""


def test_fingerprint_follows_the_assembled_value():
    """Штамп переиспользования слота — по собранному значению записи (name,
    origin, блоки, связи, файл), не по объекту: та же запись → тот же
    отпечаток, новое Assembly — новый; общий content_fingerprint роутит
    внешнюю карточку в external-ветку сам."""
    card = ExternalCardSource(
        name="Везучесть",
        origin="SRD",
        blocks=(ExternalTextBlock("Текст", "спасает"),),
        source_id="srd/lucky",
    )
    clone = ExternalCardSource(
        name="Везучесть",
        origin="SRD",
        blocks=(ExternalTextBlock("Текст", "спасает"),),
        source_id="srd/lucky",
    )
    with _external_types(("dd_feat", "Черта", "Черты")):
        assert _vm(card).content_fingerprint == external_content_fingerprint(clone)
        assert content_fingerprint("dd_feat", card) == (
            external_content_fingerprint(card)
        )
        moved = ExternalCardSource(
            name="Везучесть", origin="Другой набор", source_id="srd/lucky"
        )
        assert content_fingerprint("dd_feat", moved) != content_fingerprint(
            "dd_feat", card
        )


def test_now_broadcast_leaves_the_age_line_empty():
    """Внешняя карточка подписана на «сейчас» общей машиной, но пересчёт
    возраста не из чего брать: линия остаётся честной пустой."""
    from tests.presentation.test_entity_preview_view_model import _NowStub

    with _external_types(("dd_feat", "Черта", "Черты")):
        vm = _vm(ExternalCardSource(name="Везучесть", origin="SRD"))
        vm._now_vm = _NowStub(coord=object(), is_bc=False)
        vm.recount_age()
        assert vm.age_text == ""
