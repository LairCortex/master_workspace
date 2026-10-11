"""Клиент LSS-датасетов на общем ``httpx.AsyncClient`` (add-dnd-module-foundation,
task 3.2; проверка — «тесты на httpx.MockTransport: успех, 4xx/5xx, сетевая,
таймаут — без автоповтора»).

Сеть в тесте запрещена (AGENTS), поэтому единственный транспорт — MockTransport.
Каждый тест сверяет и адрес: SRD 2014/2024 и оба списка слагов живут
константами клиента, handler видит ровно эти строки.
"""
from __future__ import annotations

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
    форму: база gdc.longstoryshort.app и ожидание сервисных спецификаций."""
    assert client_module.LSS_DATASETS_BASE_URL == "https://gdc.longstoryshort.app/datasets"
    assert SRD_2014_URL == "https://gdc.longstoryshort.app/datasets/srd51.json"
    assert SRD_2024_URL == "https://gdc.longstoryshort.app/datasets/srd52.json"
    assert SPELLS_2014_URL == "https://gdc.longstoryshort.app/datasets/spells-srd51.txt"
    assert SPELLS_2024_URL == "https://gdc.longstoryshort.app/datasets/spells-srd52.txt"


# ── успех ────────────────────────────────────────────────────────────────────


async def test_each_fetch_hits_its_constant_and_returns_body():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith(".json"):
            return httpx.Response(200, text='{"id": "x"}')
        return httpx.Response(200, text="fireball\n\nshield\n")

    client = _client(handler)
    assert await client.fetch_srd_2014() == '{"id": "x"}'
    assert await client.fetch_srd_2024() == '{"id": "x"}'
    assert await client.fetch_spell_slugs_2014() == ("fireball", "shield")
    assert await client.fetch_spell_slugs_2024() == ("fireball", "shield")
    assert seen == [SRD_2014_URL, SRD_2024_URL, SPELLS_2014_URL, SPELLS_2024_URL]


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
