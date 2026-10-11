"""The dataset library service (add-dnd-module-foundation, tasks 3.1/3.3;
design Д3/Д4/Д6).

The application face of the global storage: the storage list for the screens
(without network), the store rules of an incoming document (id validation,
replace-only-after-confirmation, the SRD protection — spec «Импорт
пользовательского датасета файлом»: «заменять только после подтверждения;
служебные SRD-наборы защищены»), and the idempotent official-SRD bootstrap
(spec «Автозагрузка SRD-наборов»).

The bootstrap is the answer of BOTH the first module attach (the façade
schedules it) and the sheet's repeat button (group 5 calls the very same
method): a set already lying in the storage is never re-fetched and never
overwritten — «уже лежащие в хранилище SRD-наборы НЕ SHALL перезаписываться
без явного запроса пользователя». Failures never raise: every row carries
its Russian reason, so the game open is never blocked by an offline server
(spec «Офлайн не ломает игру»).

This layer is Qt-free; the only collaborators are injected — the file
storage and the LSS client (which itself rides the ONE shared HTTP client).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Awaitable, Callable

from app.dd.domain.dataset import (
    SRD_2014_DATASET_ID,
    SRD_2024_DATASET_ID,
    DatasetMeta,
    DatasetSource,
    DownloadStatus,
    OfficialDatasetOutcome,
    OfficialDatasetsResult,
    StoreOutcome,
    StoreStatus,
    StoredDataset,
    dataset_title_from_document,
    is_valid_dataset_id,
)
from app.dd.infrastructure.dataset_storage import DatasetStorage
from app.dd.infrastructure.lss_datasets_client import DatasetsError

if TYPE_CHECKING:
    from app.dd.infrastructure.lss_datasets_client import LssDatasetsClient

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OfficialDatasetSpec:
    """One official set: its id, the caption the user reads, and the two
    fetches belonging to it (document + spell-slug list, design Д5)."""

    dataset_id: str
    caption: str
    fetch_document: Callable[[], Awaitable[str]]
    fetch_spell_slugs: Callable[[], Awaitable[tuple[str, ...]]]


class DatasetLibraryService:
    """Storage rules + official bootstrap over the injected collaborators."""

    def __init__(self, storage: DatasetStorage, client: "LssDatasetsClient") -> None:
        self._storage = storage
        self._client = client

    # ── storage face (no network) ─────────────────────────────────────────────

    def list_storage(self) -> list[StoredDataset]:
        """Everything the shelf holds — the screen's first column (spec: the
        list is available «без сети»)."""
        return self._storage.list_datasets()

    def get_spell_slugs(self, dataset_id: str) -> tuple[str, ...] | None:
        """The stored slug list of an official set, ``None`` when it never
        arrived (the validator then skips the slug check — design Д5)."""
        return self._storage.load_spell_slugs(dataset_id)

    def store_dataset(self, content: str, *, allow_replace: bool = False) -> StoreOutcome:
        """Validate-and-shelve one document (task 3.1 check: «замена с
        подтверждением на уровне сервиса, защита SRD»).

        The identifier is taken from the DOCUMENT (the file is «опознаваемый
        по идентификатору … из самого файла»), validated, and the file name is
        derived from it. The rules, in the spec's order: unreadable JSON —
        refusal with the reason; an id whose grammar cannot become a file name
        — refusal; an official SRD shelf — refusal NO confirmation can lift;
        another existing homebrew shelf — refusal until ``allow_replace``
        arrives; a fresh id — an immediate homebrew save.
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            return StoreOutcome(
                status=StoreStatus.INVALID_CONTENT,
                dataset_id=None,
                title="",
                message=f"Файл не является разобранным JSON: {exc}.",
            )
        dataset_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(dataset_id, str):
            return StoreOutcome(
                status=StoreStatus.INVALID_CONTENT,
                dataset_id=None,
                title="",
                message="В файле нет текстового поля id — набор не опознан.",
            )
        if not is_valid_dataset_id(dataset_id):
            return StoreOutcome(
                status=StoreStatus.INVALID_CONTENT,
                dataset_id=None,
                title="",
                message=f"Идентификатор «{dataset_id}» не может именем файла.",
            )
        title = dataset_title_from_document(data, dataset_id)
        existing = self._storage.load_meta(dataset_id)
        if existing is not None:
            if existing.source is DatasetSource.SRD:
                return StoreOutcome(
                    status=StoreStatus.SRD_PROTECTED,
                    dataset_id=dataset_id,
                    title=title,
                    message=(
                        f"Служебный набор SRD «{title}» защищён от замены — "
                        "импорт его не перезапишет."
                    ),
                )
            if not allow_replace:
                return StoreOutcome(
                    status=StoreStatus.NEEDS_CONFIRMATION,
                    dataset_id=dataset_id,
                    title=title,
                    message=(
                        f"Набор «{title}» уже в хранилище — заменить его можно "
                        "только с вашим подтверждением."
                    ),
                )
        self._storage.save(
            dataset_id,
            content,
            DatasetMeta(
                source=DatasetSource.HOMEBREW,
                imported_at=date.today().isoformat(),
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            ),
        )
        return StoreOutcome(
            status=StoreStatus.REPLACED if existing is not None else StoreStatus.SAVED,
            dataset_id=dataset_id,
            title=title,
        )

    # ── official bootstrap (task 3.3) ─────────────────────────────────────────

    def _official_specs(self) -> tuple[OfficialDatasetSpec, ...]:
        """The two official sets, ids paired with the client's constants."""
        return (
            OfficialDatasetSpec(
                dataset_id=SRD_2014_DATASET_ID,
                caption="SRD 5.1 (2014)",
                fetch_document=self._client.fetch_srd_2014,
                fetch_spell_slugs=self._client.fetch_spell_slugs_2014,
            ),
            OfficialDatasetSpec(
                dataset_id=SRD_2024_DATASET_ID,
                caption="SRD 5.2 (2024)",
                fetch_document=self._client.fetch_srd_2024,
                fetch_spell_slugs=self._client.fetch_spell_slugs_2024,
            ),
        )

    async def download_official_datasets(self) -> OfficialDatasetsResult:
        """The idempotent SRD bootstrap (spec «Автозагрузка SRD-наборов»).

        A set already lying in the storage is reported present WITHOUT a
        request («Повторный запуск не качает»); only the missing ones are
        fetched, each with its spell-slug list. A fetch failure reads Russian
        in the row and never reaches the caller as an exception — the attach
        that scheduled this must never fail because of the network. The
        spell-slug list is best-effort: without it the validator skips the
        slug checks (design Д5), so its absence does not sink the set itself.
        """
        items: list[OfficialDatasetOutcome] = []
        for spec in self._official_specs():
            if self._storage.load_meta(spec.dataset_id) is not None:
                items.append(
                    OfficialDatasetOutcome(
                        dataset_id=spec.dataset_id,
                        caption=spec.caption,
                        status=DownloadStatus.ALREADY_PRESENT,
                        message="уже в хранилище — сеть не обращалась к этому набору",
                    )
                )
                continue
            try:
                title = await self._fetch_and_save(spec)
                items.append(
                    OfficialDatasetOutcome(
                        dataset_id=spec.dataset_id,
                        caption=spec.caption,
                        status=DownloadStatus.DOWNLOADED,
                        message=title,
                    )
                )
            except DatasetsError as exc:
                _LOGGER.warning(
                    "SRD bootstrap failed for %s: %s", spec.dataset_id, exc
                )
                items.append(
                    OfficialDatasetOutcome(
                        dataset_id=spec.dataset_id,
                        caption=spec.caption,
                        status=DownloadStatus.FAILED,
                        message=str(exc),
                    )
                )
        return OfficialDatasetsResult(items=tuple(items))

    async def _fetch_and_save(self, spec: OfficialDatasetSpec) -> str:
        """One missing set: document first (a refusal leaves the shelf
        untouched), then its spell-slug list best-effort. Returns the title
        the document carries; the ids must match — a server answer for a
        different set is a refusal, not a new shelf."""
        raw = await spec.fetch_document()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DatasetsError(
                f"Сервер вернул не JSON-датасет для {spec.caption}: {exc}"
            ) from exc
        document_id = data.get("id") if isinstance(data, dict) else None
        if document_id != spec.dataset_id:
            raise DatasetsError(
                f"Сервер вернул для {spec.caption} набор с другим идентификатором "
                f"({document_id!r})"
            )
        title = dataset_title_from_document(data, spec.caption)
        self._storage.save(
            spec.dataset_id,
            raw,
            DatasetMeta(
                source=DatasetSource.SRD,
                imported_at=date.today().isoformat(),
                sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            ),
        )
        try:
            slugs = await spec.fetch_spell_slugs()
        except DatasetsError as exc:
            # The set itself is in; without its list the slug checks simply
            # skip (design Д5) — say so, but keep the success.
            _LOGGER.warning(
                "Spell-slug list for %s not stored: %s", spec.dataset_id, exc
            )
            title += " (список слагов не загружен)"
        else:
            self._storage.save_spell_slugs(spec.dataset_id, slugs)
        return title
