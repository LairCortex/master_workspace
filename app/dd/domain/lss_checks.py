"""Cross-field checks of the LSS dataset (change add-dnd-module-foundation, tasks 4.3/4.4).

JSON-Schema validates the *shape*; the checks here cover what schemas cannot
express, following the list fixed in the LSS dataset documentation with the
same error/warning categories. The module is pure: the document under
validation, the vocabulary extracted from the bundled schemas, the other
datasets connected to the game (link resolution runs over ALL of them — spec
scenario «Ссылка через подключённый набор») and, optionally, the downloaded
SRD spell-slug lists. Same input — same issue list (ordering is normalized by
``ValidationReport.of``).

Check codes are the stable machine contract of the report (task 4.5):
never reword a code, only its Russian text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.dd.domain.dataset import DatasetSource
from app.dd.domain.lss_formula import formula_is_valid
from app.dd.domain.validation_report import CheckIssue, Severity

# Sections of a wizard dataset, in the deterministic traversal order.
SECTIONS: tuple[str, ...] = (
    "classes",
    "subclasses",
    "races",
    "subraces",
    "backgrounds",
    "feats",
)

# --- issue codes (stable machine contract) ---------------------------------
CODE_INVALID_JSON = "INVALID_JSON"
CODE_UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
CODE_SCHEMA = "SCHEMA"
CODE_LICENSE = "LICENSE"
CODE_DUP_ID = "DUP_ID"
CODE_LINK_CLASS = "LINK_CLASS"
CODE_LINK_RACE = "LINK_RACE"
CODE_LINK_FEAT = "LINK_FEAT"
CODE_BONUS_SOURCE_XOR = "BONUS_SOURCE_XOR"
CODE_BONUS_TARGET = "BONUS_TARGET"
CODE_FORMULA = "FORMULA"
CODE_KEY = "KEY"
CODE_CHOICE_EMPTY = "CHOICE_EMPTY"
CODE_PICK_ONE_OPTION_ID = "PICK_ONE_OPTION_ID"
CODE_PICK_ONE_OPTION_DUP = "PICK_ONE_OPTION_DUP"
CODE_RESOURCE_SOURCE_XOR = "RESOURCE_SOURCE_XOR"
CODE_SPELL_CHOICE_EMPTY = "SPELL_CHOICE_EMPTY"
CODE_SPELL_CHOICE_CIRCLE = "SPELL_CHOICE_CIRCLE"
CODE_SPELL_LIST = "SPELL_LIST"
CODE_SPELL_CASTER_LIST = "SPELL_CASTER_LIST"
CODE_SPELL_CHOICE_DUP_CIRCLE = "SPELL_CHOICE_DUP_CIRCLE"
CODE_SPELL_USES_XOR = "SPELL_USES_XOR"
CODE_SLOTS_TABLE = "SLOTS_TABLE"
CODE_TRAIT_PARAMS_PROSE = "TRAIT_PARAMS_PROSE"
CODE_ROLL_FORMULA = "ROLL_FORMULA"
CODE_COUNTER_PAIR = "COUNTER_PAIR"
CODE_CONSUMER_CHANNEL = "CONSUMER_CHANNEL"
CODE_FEAT_SLOT_NO_CANDIDATES = "FEAT_SLOT_NO_CANDIDATES"
CODE_SPELL_SLUG_NOT_SRD = "SPELL_SLUG_NOT_SRD"
CODE_SLOTS_TABLE_EMPTY = "SLOTS_TABLE_EMPTY"
CODE_SLOTS_TABLE_ROW_LEN = "SLOTS_TABLE_ROW_LEN"
CODE_REST_REGAIN_LONG_REST = "REST_REGAIN_LONG_REST"

# License whitelist (LSS hard rules): CC0, CC-BY with version, CC-BY-SA with
# version — a bare "CC-BY" without version is rejected on purpose.
LICENSE_RE = re.compile(r"^(?:CC0(?:-1\.0)?|CC-BY-\d+\.\d+|CC-BY-SA-\d+\.\d+)$")

# Choice grants whose `count` must be positive.
_COUNTED_CHOICE_TYPES = frozenset(
    {"skill-choice", "tool-choice", "language-choice", "expertise-choice"}
)

# The 21 entries of slotsByLevel: index 0 is a stub, levels 1..20 follow.
_SLOTS_TABLE_LENGTH = 21
_SLOTS_MAX_CIRCLE = 9

# `featId` sentinel meaning an open feat slot ("any feat").
FEAT_ID_ANY = "any"


@dataclass(frozen=True)
class LssVocabulary:
    """Closed lists extracted from the bundled schemas (one knowledge, one place)."""

    skill_keys: frozenset[str]
    stat_keys: frozenset[str]
    armor_keys: frozenset[str]
    weapon_keys: frozenset[str]
    bonus_targets: frozenset[str]
    bonus_target_patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class ConnectedDataset:
    """Another stored dataset connected to the game, parsed and ready for links."""

    dataset_id: str
    source: DatasetSource
    document: Mapping[str, Any]


def _issue(
    issues: list[CheckIssue],
    code: str,
    severity: Severity,
    path: str,
    message: str,
) -> None:
    issues.append(CheckIssue(code=code, severity=severity, path=path, message=message))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# grant traversal (recursive through pick-one options — half of the content
# of real datasets lives inside them)
# ---------------------------------------------------------------------------
def _collect_grants(items: object, base: str, out: list[tuple[dict, str]]) -> None:
    if not isinstance(items, list):
        return
    for index, grant in enumerate(items):
        if not isinstance(grant, dict):
            continue
        path = f"{base}[{index}]"
        grant_type = grant.get("type")
        if isinstance(grant_type, str):
            path = f"{path}({grant_type})"
        out.append((grant, path))
        if grant_type == "pick-one":
            options = grant.get("options")
            if isinstance(options, list):
                for option_index, option in enumerate(options):
                    if isinstance(option, dict):
                        _collect_grants(
                            option.get("grants"),
                            f"{path}.options[{option_index}].grants",
                            out,
                        )


def _entity_grants(entity: Mapping[str, Any], entity_path: str) -> list[tuple[dict, str]]:
    out: list[tuple[dict, str]] = []
    _collect_grants(entity.get("grants"), f"{entity_path}:grants", out)
    leveled = entity.get("leveledGrants")
    if isinstance(leveled, list):
        for index, block in enumerate(leveled):
            if isinstance(block, dict):
                _collect_grants(
                    block.get("grants"),
                    f"{entity_path}:leveledGrants[{index}].grants",
                    out,
                )
    return out


# ---------------------------------------------------------------------------
# corpus: ids of all connected sets, link resolution domain
# ---------------------------------------------------------------------------
@dataclass
class _Corpus:
    class_ids: set[str] = field(default_factory=set)
    race_ids: set[str] = field(default_factory=set)
    feat_ids: set[str] = field(default_factory=set)
    trait_ids: set[str] = field(default_factory=set)
    srd_class_ids: set[str] = field(default_factory=set)
    class_ids_with_list: set[str] = field(default_factory=set)
    feat_total: int = 0

    def feed(self, document: Mapping[str, Any], *, official: bool) -> None:
        for section in SECTIONS:
            entities = document.get(section)
            if not isinstance(entities, list):
                continue
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                entity_id = entity.get("id")
                if not isinstance(entity_id, str):
                    continue
                if section == "classes":
                    self.class_ids.add(entity_id)
                    if official:
                        self.srd_class_ids.add(entity_id)
                elif section == "races":
                    self.race_ids.add(entity_id)
                elif section == "feats":
                    self.feat_ids.add(entity_id)
                    self.feat_total += 1
                for grant, _path in _entity_grants(entity, ""):
                    grant_type = grant.get("type")
                    if grant_type == "trait":
                        trait_id = grant.get("id")
                        if isinstance(trait_id, str):
                            self.trait_ids.add(trait_id)
                    elif grant_type == "spellcasting" and section == "classes":
                        spell_list = grant.get("spellList")
                        if isinstance(spell_list, str) and spell_list:
                            self.class_ids_with_list.add(entity_id)


def _build_corpus(
    document: Mapping[str, Any],
    connected: Sequence[ConnectedDataset],
    own_is_official: bool,
) -> _Corpus:
    corpus = _Corpus()
    corpus.feed(document, official=own_is_official)
    for dataset in connected:
        if isinstance(dataset.document, dict):
            corpus.feed(dataset.document, official=dataset.source is DatasetSource.SRD)
    return corpus


# ---------------------------------------------------------------------------
# dataset-level checks
# ---------------------------------------------------------------------------
def _check_license(document: Mapping[str, Any], issues: list[CheckIssue]) -> None:
    if "license" not in document:
        _issue(
            issues,
            CODE_LICENSE,
            Severity.ERROR,
            "license",
            "датасет не указал лицензию; разрешены CC0, CC-BY и CC-BY-SA с версией",
        )
        return
    license_value = document.get("license")
    if not isinstance(license_value, str) or not LICENSE_RE.match(license_value):
        shown = license_value if isinstance(license_value, str) else "<не строка>"
        _issue(
            issues,
            CODE_LICENSE,
            Severity.ERROR,
            "license",
            f"лицензия {shown!r} вне белого списка: нужны CC0, CC-BY-<версия> "
            f"или CC-BY-SA-<версия> (например CC-BY-4.0, не CC-BY)",
        )


# ---------------------------------------------------------------------------
# grant-level checks
# ---------------------------------------------------------------------------
def _check_bonus(
    grant: dict, path: str, vocabulary: LssVocabulary, issues: list[CheckIssue]
) -> None:
    has_value = "value" in grant
    has_expr = "expr" in grant
    if has_value == has_expr:
        _issue(
            issues,
            CODE_BONUS_SOURCE_XOR,
            Severity.ERROR,
            path,
            "bonus несёт ровно одно из двух: значение value или формулу expr",
        )
    elif has_expr:
        expr = grant.get("expr")
        if isinstance(expr, str) and not formula_is_valid(expr):
            _issue(
                issues,
                CODE_FORMULA,
                Severity.ERROR,
                path,
                f"формула бонуса {expr!r} не вычисляется",
            )
    target = grant.get("target")
    if isinstance(target, str) and not _target_known(target, vocabulary):
        _issue(
            issues,
            CODE_BONUS_TARGET,
            Severity.ERROR,
            path,
            f"таргет бонуса {target!r} не из известного перечня схем",
        )


def _target_known(target: str, vocabulary: LssVocabulary) -> bool:
    if target in vocabulary.bonus_targets:
        return True
    return any(pattern.fullmatch(target) for pattern in vocabulary.bonus_target_patterns)


def _check_keys(
    grant: dict,
    path: str,
    grant_type: str,
    vocabulary: LssVocabulary,
    issues: list[CheckIssue],
) -> None:
    if grant_type in ("skill-fixed", "skill-choice", "expertise-choice"):
        keys: object = grant.get("skills") if grant_type == "skill-fixed" else grant.get("options")
        if isinstance(keys, list):
            for key in keys:
                if isinstance(key, str) and key not in vocabulary.skill_keys:
                    _issue(
                        issues,
                        CODE_KEY,
                        Severity.ERROR,
                        path,
                        f"ключ навыка {key!r} не из известного перечня схем",
                    )
    elif grant_type == "saving-throw":
        stats = grant.get("stats")
        if isinstance(stats, list):
            for key in stats:
                if isinstance(key, str) and key not in vocabulary.stat_keys:
                    _issue(
                        issues,
                        CODE_KEY,
                        Severity.ERROR,
                        path,
                        f"ключ характеристики {key!r} не из известного перечня схем",
                    )
    elif grant_type in ("asi-fixed", "asi-pool", "asi-flexible"):
        for key in _asi_stat_keys(grant):
            if key not in vocabulary.stat_keys:
                _issue(
                    issues,
                    CODE_KEY,
                    Severity.ERROR,
                    path,
                    f"ключ характеристики {key!r} не из известного перечня схем",
                )
    elif grant_type == "armor-prof":
        armors = grant.get("armors")
        if isinstance(armors, list):
            for key in armors:
                if isinstance(key, str) and key not in vocabulary.armor_keys:
                    _issue(
                        issues,
                        CODE_KEY,
                        Severity.ERROR,
                        path,
                        f"ключ брони {key!r} не из известного перечня схем",
                    )
    elif grant_type == "weapon-prof":
        weapons = grant.get("weapons")
        if isinstance(weapons, list):
            for key in weapons:
                if isinstance(key, str) and key not in vocabulary.weapon_keys:
                    _issue(
                        issues,
                        CODE_KEY,
                        Severity.ERROR,
                        path,
                        f"ключ оружия {key!r} не из известного перечня схем",
                    )


def _asi_stat_keys(grant: dict) -> list[str]:
    keys: list[str] = []
    values = grant.get("values")
    if isinstance(values, dict):
        keys.extend(str(name) for name in values)
    options = grant.get("options")
    if isinstance(options, list):
        keys.extend(str(option) for option in options)
    sets = grant.get("sets")
    if isinstance(sets, list):
        for entry in sets:
            if isinstance(entry, dict) and isinstance(entry.get("options"), list):
                keys.extend(str(option) for option in entry["options"])
    return keys


def _check_choice_slots(grant: dict, path: str, grant_type: str, issues: list[CheckIssue]) -> None:
    if grant_type in _COUNTED_CHOICE_TYPES:
        count = grant.get("count")
        if _is_number(count) and count <= 0:
            _issue(
                issues,
                CODE_CHOICE_EMPTY,
                Severity.ERROR,
                path,
                "грант выбора предлагает ноль слотов: count должен быть больше нуля",
            )
    elif grant_type == "asi-pool":
        total = grant.get("total")
        if _is_number(total) and total <= 0:
            _issue(
                issues,
                CODE_CHOICE_EMPTY,
                Severity.ERROR,
                path,
                "грант выбора предлагает ноль очков: total должен быть больше нуля",
            )
    elif grant_type in ("equipment-choice", "pick-one"):
        options = grant.get("options")
        if isinstance(options, list) and not options:
            _issue(
                issues,
                CODE_CHOICE_EMPTY,
                Severity.ERROR,
                path,
                "грант выбора предлагает ноль вариантов",
            )


def _check_pick_one_named(grant: dict, path: str, issues: list[CheckIssue]) -> None:
    grant_id = grant.get("id")
    if not isinstance(grant_id, str) or not grant_id:
        return
    options = grant.get("options")
    if not isinstance(options, list):
        return
    seen: dict[str, int] = {}
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            continue
        option_id = option.get("id")
        option_path = f"{path}.options[{index}]"
        if not isinstance(option_id, str) or not option_id:
            _issue(
                issues,
                CODE_PICK_ONE_OPTION_ID,
                Severity.ERROR,
                option_path,
                "у именованного pick-one каждая опция обязана нести стабильный id",
            )
            continue
        if option_id in seen:
            _issue(
                issues,
                CODE_PICK_ONE_OPTION_DUP,
                Severity.ERROR,
                option_path,
                f"повторяющийся id опции {option_id!r} в pick-one: "
                f"первый — options[{seen[option_id]}]",
            )
        else:
            seen[option_id] = index


def _check_resource(grant: dict, path: str, corpus: _Corpus, issues: list[CheckIssue]) -> None:
    has_max = "max" in grant
    has_expr = "maxExpr" in grant
    if has_max == has_expr:
        _issue(
            issues,
            CODE_RESOURCE_SOURCE_XOR,
            Severity.ERROR,
            path,
            "счётчик несёт ровно одно из двух: предельное значение max или формулу maxExpr",
        )
    elif has_expr:
        expr = grant.get("maxExpr")
        if isinstance(expr, str) and not formula_is_valid(expr):
            _issue(
                issues,
                CODE_FORMULA,
                Severity.ERROR,
                path,
                f"формула предела счётчика {expr!r} не вычисляется",
            )
    # `shortRestRegain` is meaningful only together with `isShortRest` (LSS
    # resource contract): without the short-rest flag nobody reads it back.
    _check_regain(grant, path, issues, long_rest=not grant.get("isShortRest"))
    if "pairId" in grant:
        pair = grant.get("pairId")
    else:
        pair = grant.get("id")
    if isinstance(pair, str) and pair and pair not in corpus.trait_ids:
        _issue(
            issues,
            CODE_COUNTER_PAIR,
            Severity.WARNING,
            path,
            f"счётчик прикреплён к черте {pair!r}, которой нет ни в одном подключённом наборе",
        )


def _check_regain(grant: dict, path: str, issues: list[CheckIssue], *, long_rest: bool) -> None:
    regain = grant.get("shortRestRegain")
    if not isinstance(regain, str):
        return
    if not formula_is_valid(regain):
        _issue(
            issues,
            CODE_FORMULA,
            Severity.ERROR,
            path,
            f"формула короткого восстановления {regain!r} не вычисляется",
        )
    if long_rest:
        # Category error, not warning: the spec's check list
        # (`dnd-dataset-validator`, task 4.3 «все проверки заклинаний»)
        # counts this placement among errors, only the formula checks and
        # the orphan-trait pairing are warnings.
        _issue(
            issues,
            CODE_REST_REGAIN_LONG_REST,
            Severity.ERROR,
            path,
            "shortRestRegain стоит при длинном отдыхе: его никто не прочитает",
        )


def _check_uses(grant: dict, path: str, issues: list[CheckIssue]) -> None:
    uses = grant.get("uses")
    if not isinstance(uses, dict):
        return
    has_count = "count" in uses
    has_expr = "countExpr" in uses
    if has_count == has_expr:
        _issue(
            issues,
            CODE_SPELL_USES_XOR,
            Severity.ERROR,
            path,
            "uses несёт ровно одно из двух: count или countExpr",
        )
    elif has_expr:
        expr = uses.get("countExpr")
        if isinstance(expr, str) and not formula_is_valid(expr):
            _issue(
                issues,
                CODE_FORMULA,
                Severity.ERROR,
                path,
                f"формула {expr!r} не вычисляется",
            )
    # shortRestRegain must compute whatever the rest model is; the long-rest
    # placement additionally earns the error of the same check.
    _check_regain(uses, path, issues, long_rest=uses.get("per") == "long-rest")


def _check_spell_list_field(
    grant: dict, path: str, corpus: _Corpus, issues: list[CheckIssue]
) -> bool:
    """Validate an explicit `spellList`; True when the grant carried one."""
    if "spellList" not in grant:
        return False
    spell_list = grant.get("spellList")
    if not isinstance(spell_list, str) or not spell_list:
        _issue(
            issues,
            CODE_SPELL_LIST,
            Severity.ERROR,
            path,
            "spellList пуст: укажите, чей список заклинаний использует грант",
        )
    elif spell_list not in corpus.class_ids:
        _issue(
            issues,
            CODE_SPELL_LIST,
            Severity.ERROR,
            path,
            f"spellList {spell_list!r} не ссылается на класс ни одного подключённого набора",
        )
    return True


def _check_spellcasting(
    grant: dict,
    path: str,
    section: str,
    entity: Mapping[str, Any],
    corpus: _Corpus,
    issues: list[CheckIssue],
) -> None:
    if "slotsByLevel" in grant:
        _check_slots_table(grant.get("slotsByLevel"), path, issues)
    if _check_spell_list_field(grant, path, corpus, issues):
        return
    # spellList absent: the list resolves by class id (own id for a class,
    # parent class for a subclass) — fine only if that id is covered by a
    # spell list: an official set or a class that declares its own spellList.
    default_id: object = None
    if section == "classes":
        default_id = entity.get("id")
    elif section == "subclasses":
        default_id = entity.get("classId")
    if isinstance(default_id, str) and default_id:
        if default_id in corpus.srd_class_ids:
            return
        if default_id in corpus.class_ids_with_list:
            return
    _issue(
        issues,
        CODE_SPELL_CASTER_LIST,
        Severity.ERROR,
        path,
        "собственный класс-заклинатель обязан объявить spellList: "
        "без него игрок получит ячейки и пустой список, из которого нечего выбрать",
    )


def _check_slots_table(slots: object, path: str, issues: list[CheckIssue]) -> None:
    if not isinstance(slots, list):
        _issue(
            issues,
            CODE_SLOTS_TABLE,
            Severity.ERROR,
            path,
            "slotsByLevel обязан быть массивом строк по уровням",
        )
        return
    if not slots:
        _issue(
            issues,
            CODE_SLOTS_TABLE_EMPTY,
            Severity.WARNING,
            path,
            "таблица ячеек пуста",
        )
        return
    for row_index, row in enumerate(slots):
        if not isinstance(row, list):
            _issue(
                issues,
                CODE_SLOTS_TABLE,
                Severity.ERROR,
                f"{path}.slotsByLevel[{row_index}]",
                f"строка {row_index} таблицы ячеек обязана быть массивом чисел",
            )
            continue
        if len(row) > _SLOTS_MAX_CIRCLE:
            _issue(
                issues,
                CODE_SLOTS_TABLE_ROW_LEN,
                Severity.WARNING,
                f"{path}.slotsByLevel[{row_index}]",
                f"строка {row_index} таблицы ячеек длиннее девяти кругов",
            )
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, (int, float)) or cell < 0 or (
                isinstance(cell, float) and not cell.is_integer()
            ):
                _issue(
                    issues,
                    CODE_SLOTS_TABLE,
                    Severity.ERROR,
                    f"{path}.slotsByLevel[{row_index}]",
                    "в строке таблицы ячеек встретилось не целое неотрицательное число",
                )
                break
    if len(slots) < _SLOTS_TABLE_LENGTH:
        _issue(
            issues,
            CODE_SLOTS_TABLE,
            Severity.ERROR,
            path,
            f"таблица ячеек короче {_SLOTS_TABLE_LENGTH} записей (нулевой элемент + уровни 1..20)",
        )


def _check_spell_choice(
    grant: dict,
    path: str,
    circles: dict[int, str],
    corpus: _Corpus,
    issues: list[CheckIssue],
) -> None:
    count = grant.get("count")
    if not _is_number(count) or count <= 0:
        _issue(
            issues,
            CODE_SPELL_CHOICE_EMPTY,
            Severity.ERROR,
            path,
            "грант выбора заклинаний должен предлагать хотя бы одно заклинание: count > 0",
        )
    circle = grant.get("circle")
    if isinstance(circle, bool) or not isinstance(circle, int) or not 0 <= circle <= _SLOTS_MAX_CIRCLE:
        _issue(
            issues,
            CODE_SPELL_CHOICE_CIRCLE,
            Severity.ERROR,
            path,
            "грант выбора заклинаний обязан задать круг от 0 (заговоры) до 9",
        )
    elif circle in circles:
        _issue(
            issues,
            CODE_SPELL_CHOICE_DUP_CIRCLE,
            Severity.ERROR,
            path,
            f"на сущности два выбора заклинаний одного круга {circle}: "
            f"первый — {circles[circle]}",
        )
    else:
        circles[circle] = path
    _check_spell_list_field(grant, path, corpus, issues)
    _check_uses(grant, path, issues)


def _check_spell_fixed(
    grant: dict,
    path: str,
    spell_slugs: frozenset[str] | None,
    issues: list[CheckIssue],
) -> None:
    if spell_slugs is not None:
        slug = grant.get("slug")
        if isinstance(slug, str) and slug and slug not in spell_slugs:
            _issue(
                issues,
                CODE_SPELL_SLUG_NOT_SRD,
                Severity.WARNING,
                path,
                f"слагов spell-fixed {slug!r} нет в публичных SRD-списках заклинаний",
            )
    _check_uses(grant, path, issues)


def _check_channel_placement(
    grant: dict, path: str, grant_type: str, section: str, issues: list[CheckIssue]
) -> None:
    if grant_type == "hp-die" and section != "classes":
        _issue(
            issues,
            CODE_CONSUMER_CHANNEL,
            Severity.WARNING,
            path,
            "gran hp-die вне класса: у носителя нет канала, который его прочитает",
        )
    elif grant_type == "size" and section not in ("races", "subraces"):
        _issue(
            issues,
            CODE_CONSUMER_CHANNEL,
            Severity.WARNING,
            path,
            "gran size вне расы/подрасы: у носителя нет канала, который его прочитает",
        )


def _check_trait(grant: dict, path: str, issues: list[CheckIssue]) -> None:
    params = grant.get("params")
    description = grant.get("description")
    if isinstance(params, dict) and params and isinstance(description, str) and description.strip():
        _issue(
            issues,
            CODE_TRAIT_PARAMS_PROSE,
            Severity.WARNING,
            path,
            "trait несёт и params, и прозу: текст потеряется, канал не тот",
        )


def _check_feat(
    grant: dict, path: str, corpus: _Corpus, issues: list[CheckIssue]
) -> None:
    feat_id = grant.get("featId")
    if not isinstance(feat_id, str) or not feat_id:
        return
    if feat_id == FEAT_ID_ANY:
        if corpus.feat_total == 0:
            _issue(
                issues,
                CODE_FEAT_SLOT_NO_CANDIDATES,
                Severity.WARNING,
                path,
                "открытый фит-слот, под который нет ни одного кандидата: "
                "в подключённых наборах нет ни одного фита",
            )
    elif feat_id not in corpus.feat_ids:
        _issue(
            issues,
            CODE_LINK_FEAT,
            Severity.ERROR,
            path,
            f"featId {feat_id!r} не ссылается на фит ни одного подключённого набора",
        )


# ---------------------------------------------------------------------------
# entity-level entry points
# ---------------------------------------------------------------------------
def _check_entity_links(
    section: str, entity: Mapping[str, Any], entity_id: str, path: str, corpus: _Corpus, issues: list[CheckIssue]
) -> None:
    if section == "subclasses":
        class_id = entity.get("classId")
        if isinstance(class_id, str) and class_id not in corpus.class_ids:
            _issue(
                issues,
                CODE_LINK_CLASS,
                Severity.ERROR,
                f"{path}.classId",
                f"classId {class_id!r} не ссылается на класс ни одного подключённого набора",
            )
    elif section == "subraces":
        race_id = entity.get("raceId")
        if isinstance(race_id, str) and race_id not in corpus.race_ids:
            _issue(
                issues,
                CODE_LINK_RACE,
                Severity.ERROR,
                f"{path}.raceId",
                f"raceId {race_id!r} не ссылается на расу ни одного подключённого набора",
            )


def _check_entity(
    section: str,
    entity: Mapping[str, Any],
    entity_path: str,
    vocabulary: LssVocabulary,
    corpus: _Corpus,
    spell_slugs: frozenset[str] | None,
    issues: list[CheckIssue],
) -> None:
    grants = _entity_grants(entity, entity_path)
    spell_choice_circles: dict[int, str] = {}
    for grant, path in grants:
        grant_type = grant.get("type")
        if not isinstance(grant_type, str):
            continue
        if grant_type == "bonus":
            _check_bonus(grant, path, vocabulary, issues)
        _check_keys(grant, path, grant_type, vocabulary, issues)
        _check_choice_slots(grant, path, grant_type, issues)
        if grant_type == "pick-one":
            _check_pick_one_named(grant, path, issues)
        if grant_type == "resource":
            _check_resource(grant, path, corpus, issues)
        if grant_type == "spellcasting":
            _check_spellcasting(grant, path, section, entity, corpus, issues)
        if grant_type == "spell-choice":
            _check_spell_choice(grant, path, spell_choice_circles, corpus, issues)
        if grant_type == "spell-fixed":
            _check_spell_fixed(grant, path, spell_slugs, issues)
        if grant_type == "feat":
            _check_feat(grant, path, corpus, issues)
        if grant_type == "trait":
            _check_trait(grant, path, issues)
        if grant_type == "gold-dice":
            dice = grant.get("dice")
            if isinstance(dice, str) and not formula_is_valid(dice):
                _issue(
                    issues,
                    CODE_ROLL_FORMULA,
                    Severity.WARNING,
                    path,
                    f"формула броска {dice!r} не парсится",
                )
        _check_channel_placement(grant, path, grant_type, section, issues)


def _entity_path(section: str, entity: Mapping[str, Any], index: int) -> str:
    entity_id = entity.get("id")
    shown = entity_id if isinstance(entity_id, str) and entity_id else f"#{index}"
    return f"{section}[{shown}]"


def run_cross_checks(
    document: Mapping[str, Any],
    vocabulary: LssVocabulary,
    connected: Sequence[ConnectedDataset] = (),
    spell_slugs: Sequence[str] | None = None,
    own_is_official: bool = False,
) -> list[CheckIssue]:
    """Run the full LSS cross-field check list over one parsed dataset."""
    if not isinstance(document, dict):
        return []
    issues: list[CheckIssue] = []
    corpus = _build_corpus(document, connected, own_is_official)
    slug_set = frozenset(spell_slugs) if spell_slugs is not None else None
    _check_license(document, issues)
    for section in SECTIONS:
        entities = document.get(section)
        if not isinstance(entities, list):
            continue
        seen_ids: dict[str, str] = {}
        for index, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            path = _entity_path(section, entity, index)
            entity_id = entity.get("id")
            if isinstance(entity_id, str):
                if entity_id in seen_ids:
                    _issue(
                        issues,
                        CODE_DUP_ID,
                        Severity.ERROR,
                        path,
                        f"идентификатор {entity_id!r} уже занят: {seen_ids[entity_id]} и {path}",
                    )
                else:
                    seen_ids[entity_id] = path
                _check_entity_links(section, entity, entity_id, path, corpus, issues)
            _check_entity(section, entity, path, vocabulary, corpus, slug_set, issues)
    return issues
