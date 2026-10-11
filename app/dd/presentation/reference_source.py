"""The dataset-backed reference source (add-dnd-game-face, task 3.2).

The module's one :class:`ExternalEntitySource`: it declares the six dataset
record types and the spell type, answers the kernel's generic questions
(search rows, read-only cards, mention candidates) from the index, and hides
all of them behind the game's reference toggle (protocol ``visible`` — the
kernel never learns that a toggle exists, spec «условия видимости внешнего
источника SHALL задаваться самим источником»).

Identity is the design's pair everywhere (Д4): a record answers its string
``source_id`` as ``dataset/entry``, a spell as ``set/slug`` — same-slug
records from two connected sets are two entities, each row signed with its
set's storage title (spec «Одноимённые слаги из разных наборов не
сливаются»). SRD spells honest-answer their design Д7 half only: the name is
the mechanical humanization of the slug, the text block says the full text
lives in Long Story Short — no invented prose, no empty stub card.

Nothing registers here: the module merely *declares* these descriptors, the
composition root performs the one ``register_external`` call (guards
tests/test_dd_module_isolation.py rule 3).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TYPE_CHECKING

from app.dd.application.dataset_index_service import DatasetIndexService, IndexSnapshot
from app.domain.entity_registry import ExternalTypeDescriptor
from app.presentation.modules.protocol import (
    CardTabSpec,
    CardTabTarget,
    ExternalCardSource,
    ExternalHit,
    ExternalRelation,
    ExternalTextBlock,
)

if TYPE_CHECKING:
    from app.dd.application.grimoire_index_service import GrimoireIndexService
    from app.dd.application.reference_visibility_service import (
        ReferenceVisibilityService,
    )

#: The section → type table, in the order the groups appear (design Д5's six
#: record sections; the labels are the reference sheet's future tab captions
#: too — spec dnd-reference-records). Keys carry the module's ``dd_`` prefix:
#: unique against the closed kernel literals, stable forever (a pin and an
#: inserted mention quote them).
RECORD_TYPES: tuple[tuple[str, ExternalTypeDescriptor], ...] = (
    (
        "classes",
        ExternalTypeDescriptor(
            # «list», not the kernel's character glyph: the second type→icon
            # dictionary guard (tests/presentation/test_entity_icons.py)
            # scans app/ for the kernel's characteristic glyph strings — a
            # module borrowing one is exactly the parallel-dictionary smell.
            "dd_class", "Класс", "Классы", "list", reference=True
        ),
    ),
    (
        "subclasses",
        ExternalTypeDescriptor(
            "dd_subclass", "Подкласс", "Подклассы", "chevron-down", reference=True
        ),
    ),
    (
        "races",
        ExternalTypeDescriptor(
            "dd_race", "Вид", "Виды", "user-plus", reference=True
        ),
    ),
    (
        "subraces",
        ExternalTypeDescriptor(
            "dd_subrace", "Подвид", "Подвиды", "arrow-down", reference=True
        ),
    ),
    (
        "backgrounds",
        ExternalTypeDescriptor(
            "dd_background", "Предыстория", "Предыстории", "scroll-text",
            reference=True,
        ),
    ),
    (
        "feats",
        ExternalTypeDescriptor(
            "dd_feat", "Черта", "Черты", "crosshair", reference=True
        ),
    ),
)

#: The spell type lives beside the six but has no dataset section: its
#: records are the public spell-slug lists the library downloaded with the
#: SRD sets (task 3.2) plus the spells of the game's connected grimoires
#: (task 6.1, coordinator ruling on the group-4 gap: the grimoire record
#: reader joins HERE — one ``dd_spell`` group covers both doors, every row
#: signed with its own source).
SPELL_TYPE = ExternalTypeDescriptor(
    "dd_spell", "Заклинание", "Заклинания", "sparkles", reference=True
)

#: The honest line of an SRD spell card (design Д7): the slug is public, the
#: text is not ours to print — the reader is sent where the text lives.
SRD_SPELL_TEXT_LINE = "Полный текст доступен в Long Story Short"

_SOURCE_ID_SEPARATOR = "/"


def humanize_spell_slug(slug: str) -> str:
    """The mechanical name of a spell slug (design Д7): dashes become spaces,
    the first letter capitals — nothing is invented, the slug is the name."""
    spaced = slug.replace("-", " ")
    return spaced[:1].upper() + spaced[1:]


def make_source_id(dataset_id: str, entry_id: str) -> str:
    """The pair's one string form (design Д4 «источник/запись»); the storage
    grammar bars ``/`` from dataset ids, so splitting is unambiguous even if
    a record id ever carries one."""
    return f"{dataset_id}{_SOURCE_ID_SEPARATOR}{entry_id}"


def split_source_id(source_id: str) -> tuple[str, str] | None:
    """The pair behind a source id; ``None`` for anything that is not one
    (foreign text, empty halves) — the tolerant reader of a stored string."""
    dataset_id, separator, entry_id = source_id.partition(_SOURCE_ID_SEPARATOR)
    if not separator or not dataset_id or not entry_id:
        return None
    return dataset_id, entry_id


#: The parent-link fields of the record format (schemas dataset-subclass /
#: dataset-subrace): a child record quotes its parent by id, resolved within
#: the same dataset. The card surfaces such a link as a transition relation
#: (spec entity-preview «связи с другими записями, переход по которым кликом
#: открывает ту же колонку»; scenario «Переход по связи записи» names the
#: subclass→class pair). Resolution stays inside the record's own dataset —
#: spec dnd-reference-records bars merging same-named records across sets,
#: so a classId is never answered by a homonym of another connected set; an
#: unresolvable id simply prints no relation (the honest-absence posture).
_PARENT_LINKS: tuple[tuple[str, str, str, str], ...] = (
    # (child type key, link field, parent section, parent type key)
    ("dd_subclass", "classId", "classes", "dd_class"),
    ("dd_subrace", "raceId", "races", "dd_race"),
)


class DndReferenceSource:
    """The six record types and spells, surfaced from the connected sets."""

    def __init__(
        self,
        index: DatasetIndexService,
        visibility: "ReferenceVisibilityService",
        grimoire_index: "GrimoireIndexService | None" = None,
    ) -> None:
        self._index = index
        self._visibility = visibility
        # The grimoire shelf's read door (task 6.1): the spells of the game's
        # connected spell files join the SAME ``dd_spell`` group, each row
        # and card signed with its grimoire. Optional by composition, not by
        # contract — a source built without the shelf honestly surfaces no
        # grimoire rows instead of crashing on a half-composed game.
        self._grimoire = grimoire_index

    @property
    def type_descriptors(self) -> tuple[ExternalTypeDescriptor, ...]:
        """The seven declared types — records first, spells last."""
        return tuple(descriptor for _, descriptor in RECORD_TYPES) + (SPELL_TYPE,)

    @property
    def visible(self) -> bool:
        """The game's reference toggle (task 3.3): one switch hides and shows
        every one of the seven groups, the kernel entities aside untouched."""
        return self._visibility.visible

    async def warm(self) -> None:
        """Reconcile both read caches (protocol task 6.2): the pin restore
        calls the SYNC ``card_source`` before any surface has performed an
        async read, so the datasets and the grimoire shelf are brought
        current here — digest-guarded, therefore a warm after a real search
        reparses nothing."""
        await self._index.snapshot()
        if self._grimoire is not None:
            await self._grimoire.snapshot()

    async def search(self, query: str) -> tuple[ExternalHit, ...]:
        """Substring match over every indexed record and slug, the toggle
        consulted at the door (a surface forgetting the ``visible`` check
        still gets the honest empty answer)."""
        if not self.visible:
            return ()
        needle = query.strip().lower()
        snap = await self._index.snapshot()
        hits: list[ExternalHit] = []
        for section, descriptor in RECORD_TYPES:
            for dataset_id in snap.ids:
                for entry in snap.entries(section, dataset_id):
                    if needle in entry.name.lower() or needle in entry.entry_id.lower():
                        hits.append(
                            ExternalHit(
                                key=descriptor.key,
                                source_id=make_source_id(dataset_id, entry.entry_id),
                                name=entry.name,
                                origin=snap.titles.get(dataset_id, dataset_id),
                            )
                        )
        for dataset_id in snap.ids:
            for slug in snap.slugs.get(dataset_id, ()):
                name = humanize_spell_slug(slug)
                if needle in name.lower() or needle in slug.lower():
                    hits.append(
                        ExternalHit(
                            key=SPELL_TYPE.key,
                            source_id=make_source_id(dataset_id, slug),
                            name=name,
                            origin=snap.titles.get(dataset_id, dataset_id),
                        )
                    )
        # Grimoire spells (task 6.1): the same ``dd_spell`` group, the file's
        # own name (no humanization — the author named it), signed with the
        # grimoire title. Slug-less entries are unaddressable and stay out.
        if self._grimoire is not None:
            gsnap = await self._grimoire.snapshot()
            for grimoire_id in gsnap.ids:
                for slug, spell in gsnap.spells.get(grimoire_id, {}).items():
                    if needle in spell.name.lower() or needle in slug.lower():
                        hits.append(
                            ExternalHit(
                                key=SPELL_TYPE.key,
                                source_id=make_source_id(grimoire_id, slug),
                                name=spell.name,
                                origin=gsnap.titles.get(grimoire_id, grimoire_id),
                            )
                        )
        return tuple(hits)

    def card_source(self, key: str, source_id: str) -> ExternalCardSource | None:
        """The read-only card of one record, assembled from the last
        snapshot (the protocol's sync door — see the index class docstring).
        A toggle-hidden source, a foreign key, an unpairable id and a record
        the index does not currently hold all answer ``None`` — the same
        unavailable posture the kernel keeps for a vanished row."""
        if not self.visible:
            return None
        pair = split_source_id(source_id)
        if pair is None:
            return None
        dataset_id, entry_id = pair
        snap = self._index.snapshot_now()
        title = snap.titles.get(dataset_id, dataset_id)
        if key == SPELL_TYPE.key:
            if entry_id in snap.slugs.get(dataset_id, ()):
                return ExternalCardSource(
                    name=humanize_spell_slug(entry_id),
                    origin=title,
                    blocks=(ExternalTextBlock("Текст", SRD_SPELL_TEXT_LINE),),
                )
            # Grimoire half of the spell group (task 6.1, spec «Хоумбрю-
            # заклинание читается полностью»): the file's name and plain-
            # text description, no honest-line stub needed — the text IS
            # here. The sync door reads the last reconciled snapshot, the
            # warm-at-open (protocol ``warm``) is what makes it honest for
            # the pin restore; a spell-less namespace answers None as
            # before. Should a dataset and a grimoire ever share a storage
            # id, the dataset door answers first — both are the module's
            # own namespaces and neither id is user-chosen.
            grimoire_spell = self._grimoire_spell(dataset_id, entry_id)
            if grimoire_spell is None:
                return None
            spell, grimoire_title = grimoire_spell
            blocks = (
                (ExternalTextBlock("Описание", spell.description),)
                if spell.description.strip()
                else ()
            )
            return ExternalCardSource(
                name=spell.name, origin=grimoire_title, blocks=blocks
            )
        for section, descriptor in RECORD_TYPES:
            if descriptor.key != key:
                continue
            entry = snap.entry(section, dataset_id, entry_id)
            if entry is None:
                return None
            return ExternalCardSource(
                name=entry.name,
                origin=title,
                blocks=self._record_blocks(entry.record),
                relations=self._parent_relations(snap, dataset_id, key, entry.record),
            )
        return None

    @staticmethod
    def _parent_relations(
        snap: IndexSnapshot, dataset_id: str, key: str, record: Mapping[str, Any]
    ) -> tuple[ExternalRelation, ...]:
        """The transition rows of a child record: a format link (classId /
        raceId) that names a record of the same dataset becomes a clickable
        relation to that parent (name snapshot included); every other card —
        and a child whose parent field is absent or names a record the set
        does not currently hold — carries none."""
        rows: list[ExternalRelation] = []
        for child_key, field, parent_section, parent_key in _PARENT_LINKS:
            if child_key != key:
                continue
            parent_id = record.get(field)
            if not isinstance(parent_id, str) or not parent_id:
                continue
            parent = snap.entry(parent_section, dataset_id, parent_id)
            if parent is None:
                continue
            rows.append(
                ExternalRelation(
                    key=parent_key,
                    source_id=make_source_id(dataset_id, parent.entry_id),
                    name=parent.name,
                )
            )
        return tuple(rows)

    async def mention_candidates(self, query: str) -> tuple[ExternalHit, ...]:
        """The @-popup candidates (the mention grammar slice wires the host;
        the source's answer is the search's, the toggle included)."""
        return await self.search(query)

    def resolve_mention(self, key: str, source_id: str) -> ExternalCardSource | None:
        """An activated mention's card — the very card ``card_source``
        assembles; unavailability (the chip outliving its dataset) answers
        ``None`` for the existing «Упоминание не найдено» channel."""
        return self.card_source(key, source_id)

    def card_tabs(self, target: CardTabTarget) -> tuple[CardTabSpec, ...]:
        """No additional tabs (the card-tab slice, group 7, decides whether
        the reference source ever declares any)."""
        return ()

    def event_marks(self, event_ids: Sequence[int]) -> dict[int, str]:
        """No ladder marks (encounters live in the module tables, group 8 —
        the reference records know no events)."""
        return {}

    def _grimoire_spell(
        self, grimoire_id: str, slug: str
    ) -> "tuple[object, str] | None":
        """One spell of the connected shelf through the sync door, paired
        with its grimoire's display title (the card's origin line); ``None``
        without a composed shelf, for a vanished grimoire and for a slug the
        file does not declare — all the same unavailable posture as a dead
        dataset record."""
        if self._grimoire is None:
            return None
        gsnap = self._grimoire.snapshot_now()
        spell = gsnap.spell(grimoire_id, slug)
        if spell is None:
            return None
        return spell, gsnap.titles.get(grimoire_id, grimoire_id)

    @staticmethod
    def _record_blocks(record: object) -> tuple[ExternalTextBlock, ...]:
        """The record's text as it is: an LSS record may carry a ``desc``
        string — it prints as the card's text block; a record without one
        shows its identity fields only (name, type, source — the honest
        minimum the spec allows; the decorative assembly is task 6.1)."""
        if isinstance(record, dict):
            desc = record.get("desc")
            if isinstance(desc, str) and desc.strip():
                return (ExternalTextBlock("Текст", desc.strip()),)
        return ()
