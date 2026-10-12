"""The module's character-tab source (add-dnd-game-face tasks 8.2/8.3).

A second :class:`ExternalEntitySource` beside the reference source, this one
declaring NO types of its own — its whole contribution is the two additional
tabs the character card grows while the module is attached: «D&D» (the five
reference pickers, level, LSS sheet id) and «Заклинания» (spell bindings).
Splitting it from the reference source keeps the two visibility rules apart,
which is exactly what the protocol means by «visible is the source's own
condition»: the reference records hide behind the game's toggle, the
character tabs live with the MODULE (spec entity-card-tabs «Таб модуля живёт
с модулем»; spec dnd-character-extension «выключение модуля SHALL гасить
табы»). The façade propagates attach/detach through the duck door
``set_attached`` (:meth:`app.dd.module.DndModule._set_sources_attached`);
before the first attach a composed-but-unattached source is honestly dark.

The character is a KERNEL entity — its id is the numeric row id projected to
the protocol's string. That projection is this source's whole use of the
pair grammar: ``card_tabs`` answers only for ``target.key == "character"``,
and an id that is not a whole gets the honest ``()`` (a foreign target could
only be a composition bug; guessing an id is not on the table).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Callable

from app.domain.entity_registry import EntityType

if TYPE_CHECKING:
    from app.dd.application.character_document_builder import CharacterDocumentBuilder
    from app.dd.application.character_import_service import CharacterImportService
    from app.dd.application.dataset_index_service import DatasetIndexService
    from app.dd.application.dnd_character_extension_service import (
        DndCharacterExtensionService,
    )
    from app.dd.application.grimoire_index_service import GrimoireIndexService
    from app.domain.entity_registry import ExternalTypeDescriptor
    from app.presentation.modules.protocol import CardTabSpec, CardTabTarget

#: The two tab keys are FOREVER literals (the host keys its widget dict by
#: them); the captions are the spec's («D&D», «Заклинания»).
CHARACTER_TAB_KEY = "dnd.sheet"
CHARACTER_TAB_TITLE = "D&D"
SPELLS_TAB_KEY = "dnd.spells"
SPELLS_TAB_TITLE = "Заклинания"


class DndCharacterTabSource:
    """The «D&D» and «Заклинания» tabs of every character card."""

    def __init__(
        self,
        *,
        character_service: "DndCharacterExtensionService",
        dataset_index: "DatasetIndexService",
        grimoire_index: "GrimoireIndexService | None" = None,
        record_labels: Mapping[str, str] | None = None,
        character_import: "CharacterImportService | None" = None,
        character_document: "CharacterDocumentBuilder | None" = None,
    ) -> None:
        self._service = character_service
        self._index = dataset_index
        self._grimoire = grimoire_index
        # The LSS file doors of the «D&D» tab (task 9.4, export half —
        # add-dnd-lss-generation task 5.3): the overwrite/save-raw buttons
        # print only with the import service, the «Экспорт для LSS…» button
        # only with the document builder (the module's no-dead-action
        # posture).
        self._character_import = character_import
        self._character_document = character_document
        if record_labels is None:
            # The captions ride the declared descriptors (one knowledge, one
            # place); importing the table is intra-module and downward-safe.
            # Keyed by the TYPE key — the frame looks its slot captions up by
            # LINK_SLOTS' third field, the same key the registry carries.
            from app.dd.presentation.reference_source import RECORD_TYPES

            record_labels = {
                descriptor.key: descriptor.label for _section, descriptor in RECORD_TYPES
            }
        self._record_labels = record_labels
        # Dark until the façade attaches it (spec «Таб модуля живёт с
        # модулем»); the composition wires the door once at startup and on
        # every live enable/disable through DndModule.
        self._attached = False
        # Вход ИИ-дозаполнения (add-dnd-lss-generation task 7.3): façade
        # передаёт его после attach тем же утиным порядком, что и attach-state
        # (источник собирается до façade — только façade умеет поднимать
        # листы на стеке коннектора). Без дверей кнопка не печатается.
        self._generation_open = None
        self._generation_deps = None

    # ── the module-lifecycle door ────────────────────────────────────────────

    def set_attached(self, attached: bool) -> None:
        """The façade's propagation of attach/detach (duck protocol among
        the module's own classes — see
        :meth:`app.dd.module.DndModule._set_sources_attached`)."""
        self._attached = bool(attached)

    def set_generation(self, opener, deps) -> None:
        """The façade's door of the AI top-up entry (duck protocol, same
        posture as :meth:`set_attached`): ``opener(character_id, document)``
        raises the generation task sheet, ``deps`` carries the shared AI gate
        and its one hint. ``None``/``None`` (module composed without the
        generation stack, or detach) prints no button."""
        self._generation_open = opener if callable(opener) else None
        self._generation_deps = deps if deps is not None else None

    # ── the kernel protocol ──────────────────────────────────────────────────

    @property
    def type_descriptors(self) -> tuple["ExternalTypeDescriptor", ...]:
        """No types: the character is the kernel's, the records belong to
        the reference source — this source contributes tabs, nothing to the
        registry."""
        return ()

    @property
    def visible(self) -> bool:
        """The module's attach state (the host gates tab collection on it;
        the tolerant surfaces that forgot the check still get honest empties
        from every door below)."""
        return self._attached

    async def warm(self) -> None:
        """Nothing to warm: the tab frames read through the index, whose
        warm the reference source already performs (protocol task 6.2)."""

    async def search(self, query: str) -> tuple:
        return ()

    def card_source(self, key: str, source_id: str):
        return None

    async def mention_candidates(self, query: str) -> tuple:
        return ()

    def resolve_mention(self, key: str, source_id: str):
        return None

    def event_marks(self, event_ids: Sequence[int]) -> dict[int, str]:
        return {}

    def card_tabs(self, target: "CardTabTarget") -> "tuple[CardTabSpec, ...]":
        """The two tabs, for a character only, and only while the module
        lives (spec: «после выключения модуля карточка того же объекта
        открывается без него»)."""
        from app.presentation.modules.protocol import CardTabSpec

        if not self._attached or target.key != EntityType.CHARACTER.value:
            return ()
        return (
            CardTabSpec(CHARACTER_TAB_KEY, CHARACTER_TAB_TITLE, self._build_character_tab),
            CardTabSpec(SPELLS_TAB_KEY, SPELLS_TAB_TITLE, self._build_spells_tab),
        )

    # ── the tab factories (protocol CardTabSpec.factory: (wiring, id)) ───────

    def _character_id(self, source_id: str) -> int:
        """The kernel row id behind the protocol string; a non-whole id
        raises — the host catches, journals and skips the tab (its tolerant
        door), which is the right verdict for a target this source cannot
        address."""
        return int(source_id)

    def _build_character_tab(self, wiring: object, source_id: str):
        from app.dd.presentation.character_tab_frames import DndCharacterTabFrame

        return DndCharacterTabFrame(
            character_id=self._character_id(source_id),
            service=self._service,
            dataset_index=self._index,
            record_labels=self._record_labels,
            run_locked=_require_run_locked(wiring),
            import_service=self._character_import,
            document_builder=self._character_document,
            generation_open=self._generation_open,
            generation_deps=self._generation_deps,
        )

    def _build_spells_tab(self, wiring: object, source_id: str):
        from app.dd.presentation.character_tab_frames import DndSpellsTabFrame

        return DndSpellsTabFrame(
            character_id=self._character_id(source_id),
            service=self._service,
            dataset_index=self._index,
            grimoire_index=self._grimoire,
            run_locked=_require_run_locked(wiring),
        )


def _require_run_locked(wiring: object) -> Callable:
    """The connector door the frames write through; a card built without a
    connector cannot host a writing tab — the raise reaches the host's
    journal-and-skip (a read-only half-tab would be the worse lie)."""
    run_locked = getattr(wiring, "run_locked", None)
    if not callable(run_locked):
        raise TypeError("карточка собрана без коннектора — модульный таб не пишется")
    return run_locked
