"""Application-wide async HTTP client."""
from __future__ import annotations

import httpx

#: TCP/TLS connection establishment timeout, seconds.
CONNECT_TIMEOUT = 10.0
#: Time to wait for the server (LLM) response, seconds.
READ_TIMEOUT = 120.0


def create_default_client() -> httpx.AsyncClient:
    """Create an ``httpx.AsyncClient`` with the application's default timeouts."""
    timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True)


class AppHttpClient:
    """Lifecycle holder for the single application-wide ``httpx.AsyncClient``.

    Created at application start, closed on ``shutdown()``. Features obtain
    the client via dependency injection instead of creating their own.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client if client is not None else create_default_client()

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()
