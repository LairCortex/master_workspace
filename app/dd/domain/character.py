"""The D&D face of a character — domain values (add-dnd-game-face task 8.1,
design Д6; spec dnd-character-extension).

Qt-free, storage-free values only. The reference-link triple is the spec's
pair «источник + id» with the name snapshot taken at the moment of the
choice; the service persists triples verbatim, so a link whose source was
disconnected or whose record vanished keeps its snapshot and the tab merely
annotates it (spec «Снятый датасет не калечит карточку»).

``LINK_SLOTS`` is the ONE table of the character's reference slots (spec:
вид/подвид/класс/подкласс/предыстория). The human captions are NOT here —
the frame reads them off the declared descriptors
(:data:`app.dd.presentation.reference_source.RECORD_TYPES`), one knowledge,
one place.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The character's level is a whole of 1…20 or unset (spec «уровень (целое
#: 1…20)»); there is no multiclass (spec «Мультикласса SHALL NOT быть»).
LEVEL_MIN = 1
LEVEL_MAX = 20

#: Russian refusal of an out-of-range level (the module's message posture:
#: the reader reads what is wrong, not a code).
LEVEL_REFUSAL = "уровень D&D-персонажа — целое от 1 до 20"

#: (slot, dataset section, external type key) for the five reference links
#: the spec names (вид/подвид/класс/подкласс/предыстория — spec
#: «D&D-набор полей персонажа»), in the order the tab prints them. Черты are
#: deliberately absent: the spec's field set stops at предыстория, and the
#: feature column stays free for a later slice instead of growing a second,
#: spec-quiet link.
LINK_SLOTS: tuple[tuple[str, str, str], ...] = (
    ("race", "races", "dd_race"),
    ("subrace", "subraces", "dd_subrace"),
    ("class", "classes", "dd_class"),
    ("subclass", "subclasses", "dd_subclass"),
    ("background", "backgrounds", "dd_background"),
)


@dataclass(frozen=True)
class ReferenceLink:
    """One stored reference link: the pair plus the name snapshot. An empty
    pair (no source, no record) is «link unset»; a filled pair whose source
    answers nothing is «источник не подключён» — the same value either way,
    nothing silently drops it (spec scenario «Снял чекбокс — карточка не
    немеет»)."""

    source_key: str
    ref_id: str
    snapshot_name: str

    @property
    def is_set(self) -> bool:
        return bool(self.ref_id)


@dataclass(frozen=True)
class DdCharacterExt:
    """The module's face of one character. Absent row reads as this empty
    value — the card of an ordinary (never-edited) character opens with
    nothing but empty fields (spec: the ordinary card changed not at all)."""

    links: dict[str, ReferenceLink]
    level: int | None = None
    lss_sheet_id: str = ""


@dataclass(frozen=True)
class DdSpellLink:
    """One spell binding (Д6): «slug + source» + name snapshot — a REFERENCE
    into the reference dictionaries (SRD sets or a grimoire), never a copy
    of the spell's text (spec «Привязка SHALL быть ссылкой на справочную
    сущность»)."""

    source_key: str
    slug: str
    snapshot_name: str


def validate_level(level: int | None) -> int | None:
    """The domain gate of the level column: ``None`` passes (unset), a whole
    outside 1…20 is refused with the Russian sentence the reader sees."""
    if level is None:
        return None
    if not isinstance(level, int) or isinstance(level, bool):
        raise ValueError(LEVEL_REFUSAL)
    if not LEVEL_MIN <= level <= LEVEL_MAX:
        raise ValueError(LEVEL_REFUSAL)
    return level


def empty_ext() -> DdCharacterExt:
    """The value an absent row reads as: no links, no level, no sheet."""
    return DdCharacterExt(links={slot: ReferenceLink("", "", "") for slot, _, _ in LINK_SLOTS})
