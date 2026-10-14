"""The module's character-tab source (add-dnd-game-face tasks 8.2/8.3; tabs
and their lineup reworked by dd-card-redesign task 5.5).

A second :class:`ExternalEntitySource` beside the reference source, this one
declaring NO types of its own — its whole contribution to the character card
are the three additional tabs the card grows while the module is attached
(«Способности», «Личность», «Заклинания») and the declarative «Основное»
content (:meth:`module_blocks`, task 4.3 — the reference lists, level, the
mechanics table and the LSS doors ride the kernel's own scroll). Splitting
it from the reference source keeps the two visibility rules apart, which is
exactly what the protocol means by «visible is the source's own condition»:
the reference records hide behind the game's toggle, the character tabs live
with the MODULE (spec entity-card-tabs «Таб модуля живёт с модулем»; spec
dnd-character-extension «выключение модуля SHALL гасить табы»). The façade
propagates attach/detach through the duck door ``set_attached``
(:meth:`app.dd.module.DndModule._set_sources_attached`); before the first
attach a composed-but-unattached source is honestly dark.

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
    from app.presentation.modules.protocol import (
        CardTabSpec,
        CardTabTarget,
        ModuleBlockFrame,
    )

#: The three module tab keys are FOREVER literals (the host keys its widget
#: dict by them); the captions are the spec's («Способности», «Личность»,
#: «Заклинания» — dd-card-redesign task 5.5, spec dnd-character-extension
#: «Вкладки модуля на карточке персонажа»). The old «D&D» tab key retired
#: with the tab: its lists and doors live on the kernel «Основное» screen
#: (the module_blocks door above), its previous-history picker on
#: «Личность».
FEATS_TAB_KEY = "dnd.feats"
FEATS_TAB_TITLE = "Способности"
PERSONALITY_TAB_KEY = "dnd.personality"
PERSONALITY_TAB_TITLE = "Личность"
SPELLS_TAB_KEY = "dnd.spells"
SPELLS_TAB_TITLE = "Заклинания"


class DndCharacterTabSource:
    """The «Способности», «Личность» and «Заклинания» tabs of every
    character card, plus the module's declarative «Основное» content."""

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
        """The three module tabs, for a character only, and only while the
        module lives (spec: «после выключения модуля карточка того же объекта
        открывается без него»). With the kernel's own «Основное» head this
        is the spec's four-tab lineup (spec dnd-character-extension «Вкладки
        модуля на карточке персонажа»).

        A FRESH character (the empty id) gets the same lineup: the tabs open
        with their sections empty and every write refuses until the card is
        saved once (spec «Новая карточка с пустыми разделами»); the frames
        read ``None`` as exactly that state."""
        from app.presentation.modules.protocol import CardTabSpec

        if not self._attached or target.key != EntityType.CHARACTER.value:
            return ()
        return (
            CardTabSpec(FEATS_TAB_KEY, FEATS_TAB_TITLE, self._build_feats_tab),
            CardTabSpec(
                PERSONALITY_TAB_KEY, PERSONALITY_TAB_TITLE, self._build_personality_tab
            ),
            CardTabSpec(SPELLS_TAB_KEY, SPELLS_TAB_TITLE, self._build_spells_tab),
        )

    async def on_entity_created(self, key: str, source_id: str) -> None:
        """The connector's creation door (dd-card-redesign, checkpoint-2
        audit; spec dnd-character-extension «Новая карточка с пустыми
        разделами» — «сохранение создаёт персонажа и расширение»): the new
        character row gains its extension alongside the kernel creation,
        through the service's idempotent upsert. Foreign keys and a detached
        module answer nothing; a refused write raises — the connector puts
        it in front of the user, the half-done save is never a silence."""
        if not self._attached or key != EntityType.CHARACTER.value:
            return
        await self._service.ensure_ext(int(source_id))

    def module_blocks(self, target: "CardTabTarget") -> "ModuleBlockFrame":
        """The declarative «Основное» content of a character card
        (dd-card-redesign task 4.3, design Д2; spec dnd-character-mechanics
        «Ядреные тексты персонажа при модуле скрыты»).

        * not attached, or not a character card → the honest empty frame
          (spec «при выключении модуля скрытые поля SHALL снова появиться» —
          detaching re-opens the card through the same door);
        * a FRESH character (empty id) → hidden-fields only: the kernel
          texts are the module's to hide even before the row exists, while
          no block can address a record that has no id yet;
        * a stored character → the hidden-fields frame plus the factory the
          host turns into the controller; the load and every painted value
          arrive through the controller's first republish (the door itself
          is sync and reads nothing)."""
        from app.presentation.modules.protocol import ModuleBlockFrame

        hidden = ("characteristics", "backstory")
        if not self._attached or target.key != EntityType.CHARACTER.value:
            return ModuleBlockFrame()
        if target.source_id == "":
            return ModuleBlockFrame(hidden_fields=hidden)
        character_id = self._character_id(target.source_id)

        def factory(wiring: object, dialog: object, republish):
            from app.dd.presentation.character_main_blocks import (
                CharacterMainBlockController,
            )

            return CharacterMainBlockController(
                character_id=character_id,
                service=self._service,
                dataset_index=self._index,
                record_labels=self._record_labels,
                run_locked=_require_run_locked(wiring),
                dialog=dialog,
                republish=republish,
                import_service=self._character_import,
                document_builder=self._character_document,
                generation_open=self._generation_open,
                generation_deps=self._generation_deps,
            )

        return ModuleBlockFrame(hidden_fields=hidden, handler_factory=factory)

    async def module_sections(self, key: str, source_id: str) -> tuple:
        """The character's read-only mirror for the preview column
        (dd-card-redesign task 7.1, design Д5; spec entity-preview «Секции
        модуля зеркалят карточку в предпросмотре»).

        Unlike the card's sync doors this one READS — the mirror is the same
        stored face the card's blocks print, so the kernel bridge accepts an
        awaitable here (the protocol docstring's task-7.1 posture) and awaits
        it inside its session-locked preview task. Dark source, foreign
        target or a non-whole id answer the empty tuple (the kernel paints
        kernel fields only); the load itself rides the bridge's tolerance —
        a raising read is the source's silence there, journalled there.
        The hidden kernel texts stay the sync ``module_blocks`` answer; this
        door only adds sections."""
        if not self._attached or key != EntityType.CHARACTER.value:
            return ()
        character_id = int(source_id)  # non-whole raises → the bridge skips
        # Sequential reads, one session at a time (the frames' posture: the
        # shared AsyncSession processes a single operation; the dataset
        # snapshot is last so every row read already rode the same frame).
        ext = await self._service.get_ext(character_id)
        mech = await self._service.get_mechanics(character_id)
        feats = await self._service.get_feat_links(character_id)
        spells = await self._service.get_spell_links(character_id)
        blocks = await self._service.get_text_blocks(character_id)
        snap = await self._index.snapshot()
        from app.dd.presentation.character_preview_sections import (
            build_character_sections,
        )

        return build_character_sections(
            ext=ext,
            mech=mech,
            feats=feats,
            spells=spells,
            blocks=blocks,
            snap=snap,
            record_labels=self._record_labels,
        )

    # ── the tab factories (protocol CardTabSpec.factory: (wiring, id)) ───────

    def _character_id(self, source_id: str) -> int | None:
        """The kernel row id behind the protocol string; the empty id (a
        fresh card) reads ``None`` — the frames' unsaved state (empty
        sections, refusal on write). A non-whole id raises — the host
        catches, journals and skips the tab (its tolerant door), which is
        the right verdict for a target this source cannot address."""
        if source_id == "":
            return None
        return int(source_id)

    def _build_feats_tab(self, wiring: object, source_id: str):
        from app.dd.presentation.character_feats_frame import DndFeatsTabFrame

        return DndFeatsTabFrame(
            character_id=self._character_id(source_id),
            service=self._service,
            dataset_index=self._index,
            run_locked=_require_run_locked(wiring),
        )

    def _build_personality_tab(self, wiring: object, source_id: str):
        from app.dd.presentation.character_personality_frame import (
            DndPersonalityTabFrame,
        )

        return DndPersonalityTabFrame(
            character_id=self._character_id(source_id),
            service=self._service,
            dataset_index=self._index,
            record_labels=self._record_labels,
            run_locked=_require_run_locked(wiring),
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
