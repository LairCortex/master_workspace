"""Global search service across all entity types."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Dict, List

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.event_repository import EventRepository


class SearchService:
    def __init__(
        self,
        event: EventRepository,
        organization: BaseRepository,
        character: BaseRepository,
        item: BaseRepository,
        location: BaseRepository,
        external_sources: Sequence[Any] = (),
    ) -> None:
        # collection keys are the registry's plural forms (wave 3, A4), in
        # the registry's canonical order — the search scope itself
        self._repos: Dict[str, BaseRepository] = {
            entity_registry.descriptor(EntityType.EVENT).plural: event,
            entity_registry.descriptor(EntityType.ORGANIZATION).plural: organization,
            entity_registry.descriptor(EntityType.CHARACTER).plural: character,
            entity_registry.descriptor(EntityType.ITEM).plural: item,
            entity_registry.descriptor(EntityType.LOCATION).plural: location,
        }
        # add-dnd-game-face (design Д1, consulted by task 3.4): the external
        # entity sources handed out by the composition root. The application
        # layer never imports the presentation package, so the items stay an
        # opaque sequence of records conforming to presentation/modules/
        # protocol.py's ExternalEntitySource: search consults ``visible`` and
        # ``search`` and groups the hits by the registry's external order.
        # Stored whole; empty by default — the pre-change service.
        self._external_sources: tuple[Any, ...] = tuple(external_sources)

    @property
    def external_sources(self) -> tuple[Any, ...]:
        """The sources the composition handed out (empty without a module)."""
        return self._external_sources

    def set_external_sources(self, sources: Sequence[Any]) -> None:
        """Re-hand-out for a module joined to the LIVE composition (the
        «Включить D&D-модуль…» path): the connector updates the three long-
        lived collaborators in place, dialogs built afterwards read the list
        through the connector anyway."""
        self._external_sources = tuple(sources)

    async def search_all(self, query: str) -> Dict[str, List[Any]]:
        results: Dict[str, List[Any]] = {}
        for key, repo in self._repos.items():
            results[key] = list(await repo.search(query))
        results.update(await self._external_results(query))
        return results

    async def _external_results(self, query: str) -> Dict[str, List[Any]]:
        """The external half of the same pass (add-dnd-game-face task 3.4,
        spec global-search «Записи зарегистрированных внешних источников
        SHALL участвовать в том же проходе после типов ядра»): every visible
        source is consulted after the kernel repos, and its hits are grouped
        under their type key in the registry's external order — only the
        keys the registry knows and marks searchable earn a group (a source
        returning an unregistered or non-searchable key is a contract miss,
        not a second opinion; the registry is the single signature source).
        Visibility is the SOURCE's own condition (spec: «условия видимости
        внешнего источника SHALL задаваться самим источником») — the
        reference toggle lives behind ``source.visible``, never in a parallel
        search list. With no sources (kernel, module-less profile) this is an
        empty dict and ``search_all`` stays the pre-change service."""
        hits_by_key: Dict[str, List[Any]] = {}
        for source in self._external_sources:
            if not source.visible:
                continue
            for hit in await source.search(query):
                hits_by_key.setdefault(hit.key, []).append(hit)
        return {
            desc.key: hits_by_key[desc.key]
            for desc in entity_registry.external_types()
            if desc.searchable and desc.key in hits_by_key
        }

    async def search_names(self, query: str) -> List[Dict[str, Any]]:
        """The ``@``-completion candidates: name search over all kernel
        entities, then the registered external sources' mention candidates.
        Returns [{type, id, name}, ...] — plus ``origin`` on external rows.

        add-dnd-game-face (task 5.2, design Д4): external candidates ride the
        same list after the kernel half. Their id is the source's string id
        (design Д4 — never a numeric surrogate); ``origin`` signs the row with
        the record's home. A hidden source (its ``visible`` — the reference
        toggle) contributes NOTHING: its records simply never reach the
        popup. The mentionable flag is the descriptor's veto for a source
        that surfaces some types but not others (spec mentions: candidates
        come from registered sources; visibility is the source's own
        condition, never a parallel switch here)."""
        results: List[Dict[str, Any]] = []
        for key, repo in self._repos.items():
            entities = await repo.search_by_name(query)
            for e in entities:
                hit_type = entity_registry.type_for_collection(key)
                results.append({"type": hit_type.value, "id": e.id, "name": e.name})
        for source in self._external_sources:
            if not source.visible:
                continue
            for hit in await source.mention_candidates(query):
                desc = entity_registry.external_descriptor(hit.key)
                if desc is None or not desc.mentionable:
                    continue
                results.append({
                    "type": hit.key,
                    "id": hit.source_id,
                    "name": hit.name,
                    "origin": hit.origin,
                })
        return results
