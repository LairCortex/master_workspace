"""Клиент LSS-датасетов на общем ``httpx.AsyncClient`` (add-dnd-module-foundation,
task 3.2; проверка — «тесты на httpx.MockTransport: успех, 4xx/5xx, сетевая,
таймаут — без автоповтора»).

Сеть в тесте запрещена (AGENTS), поэтому единственный транспорт — MockTransport.
Каждый тест сверяет и адрес: SRD 2014/2024 и оба списка слагов живут
константами клиента, handler видит ровно эти строки.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.dd.infrastructure import lss_datasets_client as client_module
from app.dd.infrastructure.lss_datasets_client import (
    SPELLS_2014_URL,
    SPELLS_2024_URL,
    SRD_2014_URL,
    SRD_2024_URL,
    DatasetsError,
    DatasetsHttpError,
    DatasetsNetworkError,
    DatasetsTimeoutError,
    LssDatasetsClient,
)
from app.infrastructure.http import AppHttpClient


def _client(handler) -> LssDatasetsClient:
    transport = httpx.MockTransport(handler)
    return LssDatasetsClient(AppHttpClient(httpx.AsyncClient(transport=transport)))


def _app_client(handler) -> AppHttpClient:
    return AppHttpClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


# ── адреса — константы клиента ───────────────────────────────────────────────


def test_addresses_are_pinned_constants():
    """LSS меняет адреса — правится ровно это место (design Д6); тест держит
    форму таблицы артефактов из «Датасеты» доков LSS (2026-10-12: переезд
    с gdc-поддомена и переименование файлов) и ожидание сервисных спецификаций."""
    assert client_module.LSS_DATASETS_BASE_URL == "https://longstoryshort.app/datasets"
    assert SRD_2014_URL == "https://longstoryshort.app/datasets/srd-2014.json"
    assert SRD_2024_URL == "https://longstoryshort.app/datasets/srd-2024.json"
    assert SPELLS_2014_URL == "https://longstoryshort.app/datasets/srd-spell-slugs-2014.json"
    assert SPELLS_2024_URL == "https://longstoryshort.app/datasets/srd-spell-slugs-2024.json"


# ── успех ────────────────────────────────────────────────────────────────────


#: Живая форма публичных списков слагов: массив объектов (доки LSS, 2026-10-12).
_SLUGS_BODY = (
    '[{"slug": "fireball", "name": "Огненный шар", "level": 3},'
    ' {"slug": "shield", "name": "Щит", "level": 1}]'
)


async def test_each_fetch_hits_its_constant_and_returns_body():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if url in (SPELLS_2014_URL, SPELLS_2024_URL):
            return httpx.Response(200, text=_SLUGS_BODY)
        return httpx.Response(200, text='{"id": "x"}')

    client = _client(handler)
    assert await client.fetch_srd_2014() == '{"id": "x"}'
    assert await client.fetch_srd_2024() == '{"id": "x"}'
    assert await client.fetch_spell_slugs_2014() == ("fireball", "shield")
    assert await client.fetch_spell_slugs_2024() == ("fireball", "shield")
    assert seen == [SRD_2014_URL, SRD_2024_URL, SPELLS_2014_URL, SPELLS_2024_URL]


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ("это не json", "не JSON-список"),
        ('{"slug": "x"}', "не JSON-массив"),
    ],
)
async def test_slug_list_body_outside_the_contract_refuses_russian(body, needle):
    """Не JSON и не массив — отказ русской строкой (DatasetsError): вызывающий
    сервис сохраняет набор, а проверки слагов просто пропускаются (design Д5)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    with pytest.raises(DatasetsError) as caught:
        await _client(handler).fetch_spell_slugs_2014()
    assert needle in str(caught.value)


async def test_slug_parser_keeps_only_usable_slugs():
    """Массив живёт своей жизнью (доки LSS): у записей бывают поля besides
    slug; запись без пригодного слага — шум, её в словаре проверок быть не должно."""
    body = json.dumps(
        [
            {"slug": "aid", "name": "Подмога", "level": 2},
            {"name": "запись без слага"},
            {"slug": ""},
            {"slug": 7},
            "строка вместо объекта",
            {"slug": "booming-blade", "level": 3},
        ],
        ensure_ascii=False,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    assert await _client(handler).fetch_spell_slugs_2024() == ("aid", "booming-blade")


# ── ошибки: 4xx/5xx, сетевая, таймаут — ровно один запрос на каждую ─────────


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (404, "Набор не найден на сервере longstoryshort.app (404)"),
        (429, "обращаться реже"),
        (500, "временно недоступен (500)"),
        (418, "ответил ошибкой (418)"),
    ],
)
async def test_http_status_maps_to_russian_error_no_retry(status, needle):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(status)

    client = _client(handler)
    with pytest.raises(DatasetsHttpError) as caught:
        await client.fetch_srd_2014()
    assert caught.value.status == status
    assert needle in str(caught.value)
    assert len(calls) == 1, "автоповтора нет — повтор только кнопкой листа"


async def test_network_error_maps_to_russian_and_does_not_retry():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        raise httpx.ConnectError("offline", request=request)

    client = _client(handler)
    with pytest.raises(DatasetsNetworkError) as caught:
        await client.fetch_spell_slugs_2024()
    assert "недоступен" in str(caught.value)
    assert len(calls) == 1


async def test_timeout_maps_to_russian_and_does_not_retry():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        raise httpx.ReadTimeout("slow", request=request)

    client = _client(handler)
    with pytest.raises(DatasetsTimeoutError) as caught:
        await client.fetch_srd_2024()
    assert "Время ожидания" in str(caught.value)
    assert len(calls) == 1


async def test_every_error_is_displayable_russian_datasets_error():
    """``str(exc)`` любого DatasetsError — готовая пользовательская формулировка
    (поза LlmError): тексты русские, класс — из одной иерархии."""
    with pytest.raises(DatasetsError):
        raise DatasetsHttpError(503)
    for error in (
        DatasetsHttpError(503),
        DatasetsNetworkError(),
        DatasetsTimeoutError(),
    ):
        assert any("а" <= ch <= "я" for ch in str(error)), str(error)


async def test_client_uses_the_injected_shared_client_only():
    """Весь трафик — через переданный AppHttpClient (AGENTS: единственный
    httpx.AsyncClient приложения); своих транспортов клиент не строит."""
    http = _app_client(lambda request: httpx.Response(200, text="srd\n"))
    client = LssDatasetsClient(http)
    assert await client.fetch_srd_2014() == "srd\n"
    assert not http.is_closed
    await http.close()
    assert http.is_closed
