"""Сборщик контекстов генерации из живых индексов игры (design Д3, task 7.1).

Контексты каналов (:class:`DatasetSectionContext`, :class:`SpellbookContext`,
:class:`CharacterContext`) — Qt-free значения, но собрать их можно только из
живого состояния игры: словарь идентификаторов подключённых источников, корпус
линков для валидатора и словарь слагов заклинаний. Это единственное место,
где генерация читает индексы; сами словари строит НЕ она, а существующие
двери: корпус и словарь слагов — :class:`DatasetImportService` (тот же
рецепт, что у проверки импорта — одно знание, одно место), записи —
:class:`DatasetIndexService`, чьими снимками живут все остальные поверхности.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.dd.application.dataset_section_channel import (
    DatasetSectionContext,
)
from app.dd.application.prompt_composer import SlugVocabularyEntry
from app.dd.application.spellbook_channel import SpellbookContext
from app.dd.domain.lss_checks import SECTIONS

if TYPE_CHECKING:
    from app.dd.application.character_channel import CharacterContext
    from app.dd.application.dataset_import_service import DatasetImportService
    from app.dd.application.dataset_index_service import DatasetIndexService
    from app.dd.application.grimoire_index_service import GrimoireIndexService

__all__ = ["GenerationInputs"]


class GenerationInputs:
    """Одна дверь «состояние игры → контекст канала» для всех трёх листов."""

    def __init__(
        self,
        *,
        index: "DatasetIndexService",
        importer: "DatasetImportService",
        grimoire_index: "GrimoireIndexService | None" = None,
    ) -> None:
        self._index = index
        self._importer = importer
        # Гримуарный словарь слагов — вторая половина известных слагов;
        # без гримуарной половины (частичная композиция) ответ остаётся
        # ровно SRD-словарём импорта.
        self._grimoires = grimoire_index

    # ── словари для промптов и разрешений ────────────────────────────────────

    async def vocabulary(self) -> tuple[SlugVocabularyEntry, ...]:
        """Слой словаря Д3: каждая запись каждой подключённой полки каждой
        секции (парный ключ «источник/запись» — единственная область
        разрешения ссылок, spec «Словарь идентификаторов»)."""
        snap = await self._index.snapshot()
        entries: list[SlugVocabularyEntry] = []
        for section in SECTIONS:
            for dataset_id in snap.ids:
                for item in snap.entries(section, dataset_id):
                    entries.append(
                        SlugVocabularyEntry(
                            source=dataset_id,
                            slug=item.entry_id,
                            name=item.name,
                        )
                    )
        return tuple(entries)

    async def section_entries(
        self, section: str
    ) -> tuple[SlugVocabularyEntry, ...]:
        """Записи одной секции — источник пар для пре-выборов листа
        персонажа (вид/класс берутся отсюда же, откуда и словарь)."""
        snap = await self._index.snapshot()
        entries: list[SlugVocabularyEntry] = []
        for dataset_id in snap.ids:
            for item in snap.entries(section, dataset_id):
                entries.append(
                    SlugVocabularyEntry(
                        source=dataset_id, slug=item.entry_id, name=item.name
                    )
                )
        return tuple(entries)

    async def _spell_slugs(self) -> tuple[str, ...] | None:
        return await self._importer.slug_dictionary()

    # ── контексты каналов ────────────────────────────────────────────────────

    async def dataset_section_context(
        self,
        section: str,
        dataset_id: str,
        *,
        world: str,
        idea: str,
        count: int,
    ) -> DatasetSectionContext:
        """Контекст круга одной секции: словарь — из индекса, корпус и словарь
        слагов — из двери проверки импорта (полка самой генерируемой секции
        из корпуса исключается, как это делает повторная проверка)."""
        return DatasetSectionContext(
            world=world,
            idea=idea,
            count=count,
            vocabulary=await self.vocabulary(),
            connected=await self._importer.validation_corpus(exclude_id=dataset_id),
            spell_slugs=await self._spell_slugs(),
        )

    async def spellbook_context(
        self, *, world: str, idea: str, count: int
    ) -> SpellbookContext:
        """Контекст круга файла заклинаний: словарь — тот же индекс,
        ``srd_slugs`` — тот же словарь, что увидит семантика канала и что
        уйдёт двери принятия (предпросмотр и принятие видят один словарь)."""
        return SpellbookContext(
            world=world,
            idea=idea,
            count=count,
            vocabulary=await self.vocabulary(),
            srd_slugs=await self._spell_slugs(),
        )

    async def character_context(
        self,
        *,
        world: str,
        concept: str,
        current_document: str | None = None,
        level: int | None = None,
        race: SlugVocabularyEntry | None = None,
        char_class: SlugVocabularyEntry | None = None,
    ) -> "CharacterContext":
        """Контекст круга персонажа (с нуля или дозаполнение — решает
        ``current_document``): разрешающее поле — все id подключённых записей
        и словарь слагов; пре-выборы мастер листа выбирает из
        :meth:`section_entries`."""
        from app.dd.application.character_channel import CharacterContext

        snap = await self._index.snapshot()
        record_ids = sorted(
            {
                item.entry_id
                for section in SECTIONS
                for dataset_id in snap.ids
                for item in snap.entries(section, dataset_id)
            }
        )
        return CharacterContext(
            world=world,
            concept=concept,
            level=level,
            race=race,
            char_class=char_class,
            vocabulary=await self.vocabulary(),
            record_ids=tuple(record_ids),
            spell_slugs=await self._spell_slugs(),
            current_document=current_document,
        )
