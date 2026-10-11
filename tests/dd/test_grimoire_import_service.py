"""Импорт гримуара: проверка → полка (add-dnd-game-face, task 4.2; design Д8;
spec dnd-grimoire-import «Гримуарный файл проходит проверку с отчётом и ложится
в глобальное хранилище»).

Тот же posture, что у тестов импорта датасетов: error — отказ и хранилище не
тронуто (структурно, а не уборкой), warning — импорт проходит и отчёт едет с
ним, замена только с подтверждением, а без подтверждения старые байты целы.
Идентификатор — из самого файла (в нижней раскладке полки), безымянный документ
получает адрес по содержимому: те же байты — та же полка.
"""
from __future__ import annotations

import json

from app.dd.application.grimoire_import_service import (
    ANONYMOUS_GRIMOIRES_PREFIX,
    GrimoireImportService,
    GrimoireImportStatus,
)
from app.dd.domain.grimoire import (
    CODE_GRIMOIRE_DUP_SLUG,
    CODE_GRIMOIRE_EMPTY,
    CODE_GRIMOIRE_SLUG_IN_SRD,
    CODE_GRIMOIRE_UNPARSEABLE,
)
from app.dd.infrastructure.grimoire_storage import GrimoireStorage
from tests.dd.grimoire_fixtures import (
    content_of,
    foundry_compendium_export,
    foundry_item_list_export,
    foundry_single_item_export,
)

SRD = ("fire-ball", "mage-hand")


def _storage(tmp_path) -> GrimoireStorage:
    return GrimoireStorage(tmp_path / "grimoires")


def _service(tmp_path) -> GrimoireImportService:
    return GrimoireImportService(_storage(tmp_path))


def _stored_shelves(tmp_path) -> list[str]:
    root = tmp_path / "grimoires"
    return sorted(p.name for p in root.glob("*")) if root.is_dir() else []


# ── успех: файл ложится под своим идентификатором ────────────────────────────


def test_fresh_import_stores_under_the_documents_own_id(tmp_path):
    """Foundry-``_id`` смешанного регистра — штатный ``Kn3v7dQm1xT0aBcD``:
    полка в нижней раскладке, байты сохранены как есть."""
    service = _service(tmp_path)
    content = content_of(foundry_single_item_export())

    outcome = service.import_grimoire(content)

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.grimoire_id == "kn3v7dqm1xt0abcd"
    assert outcome.title == "Лунный питомец"
    assert outcome.spell_count == 1
    assert not outcome.replaced
    assert service._storage.document_path("kn3v7dqm1xt0abcd").read_text(
        encoding="utf-8"
    ) == content


def test_compendium_wrapper_is_stored_under_its_own_id(tmp_path):
    service = _service(tmp_path)

    outcome = service.import_grimoire(content_of(foundry_compendium_export()))

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.grimoire_id == "tina-grimoire"
    assert outcome.title == "Гримуар Тины"


def test_document_without_identity_earns_a_content_addressed_shelf(tmp_path):
    """Массив предметов сам себя не называет — id по содержимому: те же байты
    второй раз приходят на ту же полку (замена с подтверждением, а не близнец)."""
    service = _service(tmp_path)
    content = content_of(foundry_item_list_export())

    outcome = service.import_grimoire(content)

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.grimoire_id is not None
    assert outcome.grimoire_id.startswith(ANONYMOUS_GRIMOIRES_PREFIX)
    assert outcome.title == outcome.grimoire_id  # заголовка нет — полка под id
    again = service.import_grimoire(content)
    assert again.grimoire_id == outcome.grimoire_id
    assert again.status is GrimoireImportStatus.NEEDS_CONFIRMATION
    # другое содержимое — другая полка, а не тихая перезапись
    edited = service.import_grimoire(
        json.dumps([{"name": "Иное", "slug": "other"}], ensure_ascii=False)
    )
    assert edited.grimoire_id != outcome.grimoire_id


# ── замена только с подтверждением ───────────────────────────────────────────


def test_replacement_needs_confirmation_and_keeps_the_old_bytes(tmp_path):
    """Спека «Замена подтверждается»: без «да» старый файл цел и не тронут."""
    service = _service(tmp_path)
    storage = service._storage
    storage.save("tina-grimoire", json.dumps({"id": "tina-grimoire", "name": "Старая"}))

    content = content_of(foundry_compendium_export())
    outcome = service.import_grimoire(content)

    assert outcome.status is GrimoireImportStatus.NEEDS_CONFIRMATION
    assert outcome.grimoire_id == "tina-grimoire"
    assert "подтверждением" in outcome.message
    assert storage.load_content("tina-grimoire") == json.dumps(
        {"id": "tina-grimoire", "name": "Старая"}
    )

    confirmed = service.import_grimoire(content, confirmed=True)
    assert confirmed.status is GrimoireImportStatus.STORED
    assert confirmed.replaced
    assert storage.load_content("tina-grimoire") == content


# ── ошибки: хранилище не тронуто ────────────────────────────────────────────


def test_unreadable_file_is_refused_and_nothing_is_stored(tmp_path):
    """Спека «Кривой файл не проходит»: русская причина в отчёте, на полке
    ничего — путь к хранилищу ниже порога не ведёт."""
    service = _service(tmp_path)

    outcome = service.import_grimoire("не json вовсе")

    assert outcome.status is GrimoireImportStatus.BLOCKED
    assert [i.code for i in outcome.report.errors] == [CODE_GRIMOIRE_UNPARSEABLE]
    assert _stored_shelves(tmp_path) == []


def test_empty_document_is_refused(tmp_path):
    service = _service(tmp_path)

    outcome = service.import_grimoire(json.dumps([{"type": "feat", "name": "Подвиг"}]))

    assert outcome.status is GrimoireImportStatus.BLOCKED
    assert [i.code for i in outcome.report.errors] == [CODE_GRIMOIRE_EMPTY]
    assert _stored_shelves(tmp_path) == []


def test_identifier_that_cannot_be_a_file_name_is_refused(tmp_path):
    """Идентификатор вне грамматики полки — отказ с русской подсказкой: имя
    документа чинит мастер, а не модуль тихо-хэшем."""
    service = _service(tmp_path)

    outcome = service.import_grimoire(
        json.dumps(
            {"id": "Гримуар Тины", "name": "Гримуар Тины", "items": [{"name": "Тихий знак"}]},
            ensure_ascii=False,
        )
    )

    assert outcome.status is GrimoireImportStatus.BLOCKED
    assert outcome.grimoire_id == "Гримуар Тины"
    assert "не может именем файла" in outcome.message
    assert _stored_shelves(tmp_path) == []


# ── предупреждения едут с импортом ──────────────────────────────────────────


def test_warnings_do_not_stop_the_import_and_travel_with_it(tmp_path):
    """Тот же порог, что у датасетов: дубль слага не мешает импорту, отчёт —
    при ответе (экран его печатает)."""
    service = _service(tmp_path)

    outcome = service.import_grimoire(content_of(foundry_item_list_export()))

    assert outcome.status is GrimoireImportStatus.STORED
    assert outcome.report is not None and outcome.report.import_allowed
    assert [i.code for i in outcome.report.issues] == [CODE_GRIMOIRE_DUP_SLUG]
    assert outcome.spell_count == 4


def test_srd_crossing_is_reported_only_when_the_lists_are_handed_in(tmp_path):
    """Пересечение с публичным SRD помечается, когда вызывающий принёс списки
    (та же доза tolerance, что у валидатора датасетов); без них — молчит."""
    service = _service(tmp_path)
    content = content_of(foundry_item_list_export())

    with_lists = service.import_grimoire(content, srd_slugs=SRD)
    plain = service.import_grimoire(content)

    assert CODE_GRIMOIRE_SLUG_IN_SRD in {
        i.code for i in with_lists.report.issues
    }
    assert [i.code for i in plain.report.issues] == [CODE_GRIMOIRE_DUP_SLUG]
