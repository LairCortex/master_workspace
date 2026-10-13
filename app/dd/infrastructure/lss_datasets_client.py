"""The Long Story Short dataset client (add-dnd-module-foundation, task 3.2;
design Д6).

Downloads the two official SRD exports (the 2014 SRD 5.1 and the 2024 SRD 5.2
editions) and their public spell-slug lists. ALL traffic rides the ONE
application-wide ``httpx.AsyncClient`` (``AppHttpClient`` is injected — this
client never builds a transport of its own), and there is deliberately NO
automatic retry: a failed fetch is the user's decision to repeat (the sheet's
button, task 3.3/5.2), so every ``fetch_*`` issues exactly one request.

Every failure leaves as a :class:`DatasetsError` whose ``str(exc)`` is the
Russian sentence the user reads — the ``LlmError`` posture of the kernel
(``app/infrastructure/llm/errors.py``), phrased for the dataset download.

The addresses are module constants — the one edit an LSS address change makes
(design Д6; the release checklist re-reads the LSS integration changelog).
"""
from __future__ import annotations

import json

import httpx

from app.infrastructure.http import AppHttpClient

# ── the fixed addresses of the official exports (design Д6) ──────────────────

#: Static dataset artefacts of the Long Story Short game-design compendium
#: (the artefact table of «Датасеты» in the LSS developer docs).
LSS_DATASETS_BASE_URL = "https://longstoryshort.app/datasets"

#: The 2014 SRD 5.1 export (dataset id ``srd-2014``).
SRD_2014_URL = f"{LSS_DATASETS_BASE_URL}/srd-2014.json"
#: The 2024 SRD 5.2 export (dataset id ``srd-2024``).
SRD_2024_URL = f"{LSS_DATASETS_BASE_URL}/srd-2024.json"
#: The public spell-slug lists the spell checks validate against (JSON arrays
#: of ``{"slug", "name", "level"}`` objects); absence of a list just skips
#: those checks (design Д5).
SPELLS_2014_URL = f"{LSS_DATASETS_BASE_URL}/srd-spell-slugs-2014.json"
SPELLS_2024_URL = f"{LSS_DATASETS_BASE_URL}/srd-spell-slugs-2024.json"


class DatasetsError(Exception):
    """Base dataset-download error; ``str(exc)`` is user-displayable Russian."""


class DatasetsTimeoutError(DatasetsError):
    """The server stayed silent past the shared client's timeout."""

    def __init__(self, message: str = "Время ожидания ответа от longstoryshort.app истекло") -> None:
        super().__init__(message)


class DatasetsNetworkError(DatasetsError):
    """The server could not be reached at all (offline, DNS, refused)."""

    def __init__(self, message: str = "longstoryshort.app недоступен — проверьте подключение к сети") -> None:
        super().__init__(message)


class DatasetsHttpError(DatasetsError):
    """The server answered with an error status; the status rides along for
    logs, the message reads Russian."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(self._friendly_message(status))

    @staticmethod
    def _friendly_message(status: int) -> str:
        if status == 404:
            return "Набор не найден на сервере longstoryshort.app (404)"
        if status == 429:
            return "Сервер датасетов просит обращаться реже — попробуйте позже (429)"
        if 500 <= status <= 599:
            return f"Сервер longstoryshort.app временно недоступен ({status})"
        return f"Сервер датасетов ответил ошибкой ({status})"


class LssDatasetsClient:
    """Fetches the official LSS artefacts over the shared app client."""

    def __init__(self, http: AppHttpClient) -> None:
        self._http = http

    async def fetch_srd_2014(self) -> str:
        """The SRD 5.1 (2014) dataset document as raw JSON text."""
        return await self._get(SRD_2014_URL)

    async def fetch_srd_2024(self) -> str:
        """The SRD 5.2 (2024) dataset document as raw JSON text."""
        return await self._get(SRD_2024_URL)

    async def fetch_spell_slugs_2014(self) -> tuple[str, ...]:
        """The 2014 SRD spell-slug list (a JSON array of spell objects)."""
        return self._parse_slugs(await self._get(SPELLS_2014_URL))

    async def fetch_spell_slugs_2024(self) -> tuple[str, ...]:
        """The 2024 SRD spell-slug list (a JSON array of spell objects)."""
        return self._parse_slugs(await self._get(SPELLS_2024_URL))

    async def _get(self, url: str) -> str:
        """ONE GET against ``url`` — exceptions map to the Russian hierarchy,
        statuses included; no auto-retry by design (Д6)."""
        try:
            response = await self._http.client.get(url)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise DatasetsTimeoutError from exc
        except httpx.HTTPStatusError as exc:
            raise DatasetsHttpError(exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise DatasetsNetworkError from exc
        return response.text

    @staticmethod
    def _parse_slugs(text: str) -> tuple[str, ...]:
        """The public lists are JSON arrays of ``{"slug", "name", "level"}``
        objects — the checks only ever need the slugs, so entry order is
        kept and everything else in an entry is ignored. A body that is not
        that shape refuses as ``DatasetsError`` — the best-effort caller
        keeps the set on the shelf and lets the slug checks skip (design Д5)."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DatasetsError(f"Сервер вернул не JSON-список слагов: {exc}") from exc
        if not isinstance(data, list):
            raise DatasetsError("Список слагов пришёл не JSON-массивом")
        return tuple(
            entry["slug"]
            for entry in data
            if isinstance(entry, dict) and isinstance(entry.get("slug"), str) and entry["slug"]
        )
