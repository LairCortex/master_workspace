"""Tests for the app-wide httpx client (no network)."""
from __future__ import annotations

import httpx
import pytest

from app.infrastructure.http import AppHttpClient, CONNECT_TIMEOUT, READ_TIMEOUT


def test_timeouts_are_documented_constants():
    assert CONNECT_TIMEOUT == 10.0
    assert READ_TIMEOUT == 120.0


@pytest.mark.asyncio
async def test_create_and_close_lifecycle():
    holder = AppHttpClient()
    try:
        assert not holder.is_closed
        assert isinstance(holder.client, httpx.AsyncClient)
        assert holder.client.timeout.connect == CONNECT_TIMEOUT
        assert holder.client.timeout.read == READ_TIMEOUT
    finally:
        await holder.close()
    assert holder.is_closed


@pytest.mark.asyncio
async def test_close_is_idempotent():
    holder = AppHttpClient()
    await holder.close()
    await holder.close()
    assert holder.is_closed


@pytest.mark.asyncio
async def test_wraps_existing_client():
    inner = httpx.AsyncClient()
    holder = AppHttpClient(client=inner)
    assert holder.client is inner
    await holder.close()
    assert inner.is_closed
