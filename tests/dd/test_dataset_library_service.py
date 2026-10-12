"""Сервис библиотеки датасетов (add-dnd-module-foundation, tasks 3.1/3.3).

Юнит-контур на ``tmp_path``-хранилище и ФЕЙКОВОМ клиенте (сеть клиентских
тестов — MockTransport в соседнем файле): здесь проверяются сервисные
правила замены («замена с подтверждением на уровне сервиса, защита SRD») и
идемпотентность автозагрузки SRD.
"""
from __future__ import annotations

import json
import logging

import pytest

from app.dd.application.dataset_library_service import DatasetLibraryService
from app.dd.domain.dataset import (
    DatasetMeta,
    DatasetSource,
    DownloadStatus,
    StoreStatus,
)
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.lss_datasets_client import (
    SRD_2014_URL,
    SRD_2024_URL,
    DatasetsNetworkError,
)


class FakeClient:
    """Клиент-заглушка: считает обращения, отвечает чем настроено."""

    def __init__(self, bodies=None, errors=None):
        self.calls: list[str] = []
        self.bodies = bodies or {}
        self.errors = errors or {}

    def _fetch(self, name: str, fallback: str) -> str:
        self.calls.append(name)
        error = self.errors.get(name)
        if error is not None:
            raise error
        return self.bodies.get(name, fallback)

    async def fetch_srd_2014(self):
        return self._fetch("srd_2014", json.dumps({"id": "srd51", "title": "SRD 5.1"}))

    async def fetch_srd_2024(self):
        return self._fetch("srd_2024", json.dumps({"id": "srd52", "title": "SRD 5.2"}))

    async def fetch_spell_slugs_2014(self):
        return self._slugs(self._fetch("slugs_2014", "fireball\nshield\n"))

    async def fetch_spell_slugs_2024(self):
        return self._slugs(self._fetch("slugs_2024", "fire-bolt\n"))

    @staticmethod
    def _slugs(text: str) -> tuple[str, ...]:
        return tuple(line for line in text.splitlines() if line)


def _service(tmp_path, client=None):
    storage = DatasetStorage(tmp_path / "datasets")
    fake = client if client is not None else FakeClient()
    return storage, DatasetLibraryService(storage, fake), fake


def _doc(dataset_id: str, title: str = "Хоумбрю") -> str:
    return json.dumps({"id": dataset_id, "title": title})


def _srd_shelf(storage: DatasetStorage, dataset_id: str, title: str) -> None:
    storage.save(
        dataset_id,
        _doc(dataset_id, title),
        DatasetMeta(source=DatasetSource.SRD, imported_at="2026-01-01", sha256="0" * 64),
    )


# ── store: подтверждение и защита SRD (проверка 3.1) ─────────────────────────


def test_list_storage_is_the_shelf_without_network(tmp_path):
    """Экранная витрина библиотеки — список хранилища без единого обращения
    (спека «Список хранилища … доступен экрану модуля без сети»)."""
    storage, service, client = _service(tmp_path)
    service.store_dataset(_doc("my-pack"))
    entries = service.list_storage()
    assert [(e.dataset_id, e.title) for e in entries] == [("my-pack", "Хоумбрю")]
    assert client.calls == []


def test_store_fresh_id_saves_homebrew(tmp_path):
    storage, service, _ = _service(tmp_path)
    outcome = service.store_dataset(_doc("my-pack"))
    assert outcome.status is StoreStatus.SAVED
    assert outcome.stored and outcome.dataset_id == "my-pack"
    assert outcome.title == "Хоумбрю" and outcome.message == ""
    assert storage.load_content("my-pack") == _doc("my-pack")
    meta = storage.load_meta("my-pack")
    assert meta.sha256 and meta.imported_at and meta.check_errors is None


def test_store_existing_homebrew_needs_confirmation_then_replaces(tmp_path):
    storage, service, _ = _service(tmp_path)
    service.store_dataset(_doc("pack", "Первый"))
    outcome = service.store_dataset(_doc("pack", "Второй"))
    assert outcome.status is StoreStatus.NEEDS_CONFIRMATION
    assert "подтверждением" in outcome.message and outcome.dataset_id == "pack"
    # без подтверждения файл не тронут
    assert json.loads(storage.load_content("pack"))["title"] == "Первый"
    replaced = service.store_dataset(_doc("pack", "Второй"), allow_replace=True)
    assert replaced.status is StoreStatus.REPLACED and replaced.stored
    assert json.loads(storage.load_content("pack"))["title"] == "Второй"


def test_store_srd_protected_even_with_confirmation(tmp_path):
    """Спека «SRD защищён от перезаписи»: подтверждение не покупает замену
    служебного файла — отказ с объяснением, файл не изменён."""
    storage, service, _ = _service(tmp_path)
    _srd_shelf(storage, "srd51", "SRD 5.1")
    for allow in (False, True):
        outcome = service.store_dataset(_doc("srd51", "Подмена"), allow_replace=allow)
        assert outcome.status is StoreStatus.SRD_PROTECTED
        assert not outcome.stored
        assert "защищён" in outcome.message
    assert json.loads(storage.load_content("srd51"))["title"] == "SRD 5.1"


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{это не json", "не является разобранным JSON"),
        (json.dumps({"title": "без id"}), "нет текстового поля id"),
        (json.dumps({"id": ".."}), "не может именем файла"),
        (json.dumps({"id": 7}), "нет текстового поля id"),
    ],
)
def test_store_refuses_bad_documents_without_touching_shelf(tmp_path, content, reason):
    storage, service, _ = _service(tmp_path)
    outcome = service.store_dataset(content)
    assert outcome.status is StoreStatus.INVALID_CONTENT
    assert reason in outcome.message
    assert storage.list_datasets() == []


# ── автозагрузка SRD: идемпотентность и офлайн (проверка 3.3) ───────────────


async def test_download_missing_fetches_both_sets_with_slugs(tmp_path):
    storage, service, client = _service(tmp_path)
    result = await service.download_official_datasets()
    assert result.ok and not result.all_present
    assert [i.status for i in result.items] == [
        DownloadStatus.DOWNLOADED,
        DownloadStatus.DOWNLOADED,
    ]
    assert "загружены" in result.summary
    # лексикографически slugs_* идут раньше srd_* (l < r)
    assert sorted(client.calls) == ["slugs_2014", "slugs_2024", "srd_2014", "srd_2024"]
    assert storage.load_content("srd51") is not None
    assert storage.load_meta("srd51").source.value == "srd"
    assert storage.load_spell_slugs("srd51") == ("fireball", "shield")
    assert service.get_spell_slugs("srd52") == ("fire-bolt",)


async def test_download_present_set_never_contacts_network(tmp_path):
    """Спека «Повторный запуск не качает»: уже лежащий в хранилище SRD —
    ни одного обращения к его адресам, файл не перезаписан."""
    storage, service, client = _service(tmp_path)
    await service.download_official_datasets()
    first_bytes = storage.load_content("srd51")
    client.calls.clear()
    client.bodies["srd_2014"] = "ИНОЙ, СВЕРХНОВЫЙ"
    result = await service.download_official_datasets()
    assert client.calls == []
    assert result.all_present and result.ok
    assert "уже в хранилище" in result.summary
    assert storage.load_content("srd51") == first_bytes


async def test_download_partial_missing_touches_only_missing(tmp_path):
    storage, service, client = _service(tmp_path)
    _srd_shelf(storage, "srd51", "SRD 5.1")
    result = await service.download_official_datasets()
    assert client.calls == ["srd_2024", "slugs_2024"]
    assert [i.status for i in result.items] == [
        DownloadStatus.ALREADY_PRESENT,
        DownloadStatus.DOWNLOADED,
    ]
    assert result.ok and not result.all_present


async def test_download_offline_reports_failure_and_leaves_shelf(tmp_path):
    """Спека «Офлайн не ломает игру»: исключение наружу не выходит, хранилище
    пустое по служебным, русская причина — в строках и в summary."""
    storage, service, _ = _service(
        tmp_path,
        FakeClient(errors={"srd_2014": DatasetsNetworkError(), "srd_2024": DatasetsNetworkError()}),
    )
    result = await service.download_official_datasets()
    assert not result.ok
    assert all(i.status is DownloadStatus.FAILED for i in result.items)
    assert "недоступен" in result.summary and "Не удалось" in result.summary
    assert storage.list_datasets() == []
    # повтор (уже с сетью) — догружает то, чего нет
    _, service_ok, _ = _service(tmp_path)
    assert (await service_ok.download_official_datasets()).ok


async def test_download_foreign_or_broken_body_refused(tmp_path):
    """Сервер ответил 200, но прислал не тот набор / не JSON — это отказ
    строки, полка не создаётся (защита от мусора вместо датасета)."""
    storage, service, _ = _service(
        tmp_path,
        FakeClient(bodies={
            "srd_2014": json.dumps({"id": "someone-else", "title": "чужой"}),
            "srd_2024": "<html>502 gateway</html>",
        }),
    )
    result = await service.download_official_datasets()
    assert not result.ok
    assert "другим идентификатором" in result.items[0].message
    assert "не JSON-датасет" in result.items[1].message
    assert storage.list_datasets() == []


async def test_download_spell_list_failure_keeps_the_set(tmp_path):
    """Design Д5: без списка слагов проверка слагов просто пропускается —
    осечка списка не топит сам набор, но помечена в заголовке строки."""
    client = FakeClient()
    client.errors["slugs_2014"] = DatasetsNetworkError()
    storage, service, _ = _service(tmp_path, client)
    result = await service.download_official_datasets()
    assert result.ok
    assert "список слагов не загружен" in result.items[0].message
    assert storage.load_content("srd51") is not None
    assert storage.load_spell_slugs("srd51") is None
    assert storage.load_spell_slugs("srd52") == ("fire-bolt",)


# ── журнал выпусков SRD-запросов (fix-dnd-followups, задача 2.3; Д2) ─────────
#
# Журнал — штатный живой наблюдатель сетевых выходов (spec «Автозагрузка
# SRD-наборов»: «Каждый выпуск запроса к адресам наборов и его исход SHALL
# фиксироваться записью журнала приложения»; сценарий «Повторный запуск не
# качает»: «журнал запуска не содержит записей о выпуске этих запросов»).
# Канал — семейство `app.dd` (логгер сервиса лежит в нём и через propagate
# попадает в штатный файл-журнал).


def _dd_records(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name.startswith("app.dd")
    ]


async def test_idempotent_answer_leaves_no_journal_records(tmp_path, caplog):
    """Ветка «уже в хранилище» не выпускает запрос и не оставляет НИ ОДНОЙ
    записи канала app.dd: отсутствие записей и есть проверяемый оффскрин
    факт «сеть не обращалась к адресам наборов»."""
    caplog.set_level(logging.INFO)
    storage, service, client = _service(tmp_path)
    await service.download_official_datasets()  # первая волна засеивает полки
    client.calls.clear()
    caplog.clear()
    result = await service.download_official_datasets()
    assert result.all_present
    assert client.calls == []
    assert _dd_records(caplog) == []


async def test_download_branch_journals_one_issuance_per_set(tmp_path, caplog):
    """Ветка загрузки: ровно по одной записи о выпуске на набор, в записи —
    адрес, к которому ушёл запрос (url есть имя набора, Д2), плюс исход
    загрузки той же веткой журнала."""
    caplog.set_level(logging.INFO)
    _storage, service, _client = _service(tmp_path)
    result = await service.download_official_datasets()
    assert result.ok and not result.all_present
    messages = _dd_records(caplog)
    issued = [m for m in messages if "выпуск запроса" in m]
    assert len(issued) == 2
    assert [m for m in issued if SRD_2014_URL in m] == [issued[0]]
    assert [m for m in issued if SRD_2024_URL in m] == [issued[1]]
    outcomes = [m for m in messages if "загружен:" in m]
    assert len(outcomes) == 2


async def test_failed_request_is_issued_and_journalled_as_failure(tmp_path, caplog):
    """Исход «офлайн» тоже записан: выпуск зафиксирован до провала, а
    провал — записью WARNING (принцип 3: сетевые ошибки не молчат)."""
    caplog.set_level(logging.INFO)
    _storage, service, _client = _service(
        tmp_path,
        FakeClient(
            errors={
                "srd_2014": DatasetsNetworkError(),
                "srd_2024": DatasetsNetworkError(),
            }
        ),
    )
    result = await service.download_official_datasets()
    assert not result.ok
    messages = _dd_records(caplog)
    assert sum("выпуск запроса" in m for m in messages) == 2
    failures = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name.startswith("app.dd")
    ]
    assert len(failures) == 2
    assert all("недоступен" in r.getMessage() for r in failures)
