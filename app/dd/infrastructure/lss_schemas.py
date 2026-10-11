"""Bundled Long Story Short JSON-Schemas (change add-dnd-module-foundation, task 4.1).

The schemas are shipped with the application (design Д5: determinism offline —
updating them is an explicit release edit after reviewing the LSS changelog).
``FORMAT_VERSION`` is the format revision these bundled artifacts describe; a
dataset declares its own revision through the ``$schema`` URL
(``…/schema/v<N>/wizard-dataset.json``) and a declared ``N`` without a bundled
schema is an explicit error, never a silent pass (spec scenario «Неизвестная
редакция схем»). The same files also are the single source of the closed
vocabularies (bonus targets, skill/stat/armor/weapon keys) the cross-field
checks consume.

Path resolution follows the ``preset_catalog.py`` pattern: files next to the
package on disk and under ``sys._MEIPASS`` in the frozen build.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from app.dd.domain.lss_checks import LssVocabulary
from app.dd.domain.validation_report import CheckIssue, Severity

# Revision of the LSS format the bundled artifacts describe.
FORMAT_VERSION = 1

# ``$schema`` URL of the dataset root for a given revision.
SCHEMA_URL_TEMPLATE = "https://longstoryshort.app/schema/v{version}/wizard-dataset.json"

_SCHEMA_URL_RE = re.compile(r"/schema/v(\d+)/wizard-dataset\.json$")

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "resources" / "schemas"

DATASET_SCHEMA_FILE = "wizard-dataset.json"

# add-dnd-game-face task 9.1 (design Д7): the character export rides its own
# artifact next to the eight dataset ones. Kept OUT of ``BUNDLED_SCHEMA_FILES``
# on purpose: that tuple is the dataset-artifact set (pinned by group 4's
# tests, version-gated by the ``$schema`` URL), while the character document
# is version-gated by its own envelope field (``CHARACTER_FORMAT_VERSION``).
CHARACTER_SCHEMA_FILE = "character.json"

#: The envelope ``jsonType`` a character export must carry.
CHARACTER_JSON_TYPE = "character"

#: The character-format revision this bundled artifact describes (the version
#: gate of task 9.1, the FORMAT_VERSION sibling for character exports).
CHARACTER_FORMAT_VERSION = "2"

# All artifacts of the fixed bundled set (grant + per-entity schemas ship for
# the single-entity validation of future phases and to complete the ``$id``
# schema store).
BUNDLED_SCHEMA_FILES: tuple[str, ...] = (
    "wizard-dataset.json",
    "grant.json",
    "dataset-class.json",
    "dataset-subclass.json",
    "dataset-race.json",
    "dataset-subrace.json",
    "dataset-background.json",
    "dataset-feat.json",
)

# ``$schema`` is a format declaration consumed by the version gate; the draft-07
# WizardDataset root forbids it (additionalProperties: false), so it is stripped
# from the copy handed to the shape validator.
SCHEMA_DECLARATION_KEY = "$schema"

# RU renderings for the jsonschema failure kinds the app can surface; anything
# unlisted falls back to the raw validator message.
_MESSAGE_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("Additional properties are not allowed", "поле с неизвестным именем: {detail}"),
    ("is a required property", "обязательное поле отсутствует: {detail}"),
    ("is not of type", "неверный тип значения: {detail}"),
    ("is not valid under any of the given schemas", "значение не подходит ни под один допустимый вариант: {detail}"),
    ("is not one of", "значение вне допустимого перечня: {detail}"),
    ("must be non-empty", "значение не может быть пустым: {detail}"),
    ("should be non-empty", "значение не может быть пустым: {detail}"),
)


def schema_resource_dir() -> Path:
    """Directory with the bundled schema JSONs in both dev and frozen builds."""
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        return Path(base) / "app" / "dd" / "resources" / "schemas"
    return SCHEMA_DIR


@dataclass(frozen=True)
class LssSchemaBundle:
    """Parsed schema artifacts plus the vocabulary extracted from them."""

    dataset_schema: dict[str, Any]
    schema_store: dict[str, dict[str, Any]]
    vocabulary: LssVocabulary
    # add-dnd-game-face task 9.1: the character-export artifact of the same
    # bundle (loaded by ``load_bundle``, validated by ``validate_character_shape``).
    character_schema: dict[str, Any] = field(default_factory=dict)


def _extract_vocabulary(definitions: dict[str, Any]) -> LssVocabulary:
    """Read the closed vocabularies out of the dataset schema definitions."""
    skill_branch = definitions["SkillChoiceGrant"]["properties"]["options"]["anyOf"][0]
    skill_keys = frozenset(skill_branch["items"]["enum"])
    stat_keys = frozenset(definitions["StatKey"]["enum"])
    armor_keys = frozenset(definitions["ArmorProfKey"]["enum"])
    weapon_keys = frozenset(definitions["WeaponProfKey"]["enum"])
    bonus_targets: set[str] = set()
    bonus_patterns: list[re.Pattern[str]] = []
    for branch in definitions["BonusTarget"]["anyOf"]:
        if "enum" in branch:
            bonus_targets.update(branch["enum"])
        elif "pattern" in branch:
            bonus_patterns.append(re.compile(branch["pattern"]))
    return LssVocabulary(
        skill_keys=skill_keys,
        stat_keys=stat_keys,
        armor_keys=armor_keys,
        weapon_keys=weapon_keys,
        bonus_targets=frozenset(bonus_targets),
        bonus_target_patterns=tuple(bonus_patterns),
    )


def load_bundle(schema_dir: Path | None = None) -> LssSchemaBundle:
    """Load every bundled schema file and derive the check vocabulary."""
    directory = schema_dir if schema_dir is not None else schema_resource_dir()
    documents: dict[str, dict[str, Any]] = {}
    store: dict[str, dict[str, Any]] = {}
    for name in BUNDLED_SCHEMA_FILES:
        document = json.loads((directory / name).read_text(encoding="utf-8"))
        documents[name] = document
        schema_id = document.get("$id")
        if isinstance(schema_id, str):
            store[schema_id] = document
    dataset_schema = documents[DATASET_SCHEMA_FILE]
    # The character artifact joins the store under its own $id (its internal
    # ``$ref``s stay local, but registering costs nothing and keeps the one
    # registry complete for every bundled document — task 9.1).
    character_schema = json.loads(
        (directory / CHARACTER_SCHEMA_FILE).read_text(encoding="utf-8")
    )
    character_id = character_schema.get("$id")
    if isinstance(character_id, str):
        store[character_id] = character_schema
    return LssSchemaBundle(
        dataset_schema=dataset_schema,
        schema_store=store,
        vocabulary=_extract_vocabulary(dataset_schema["definitions"]),
        character_schema=character_schema,
    )


def extract_format_version(document: dict[str, Any]) -> int | None:
    """The revision declared by a dataset's ``$schema`` URL, if any.

    Returns ``None`` when the document declares no revision (real SRD files do
    not) — callers then assume ``FORMAT_VERSION``. A declaration that names a
    revision number is returned as that number; a malformed declaration reads
    as the unsupported ``-1`` sentinel so the caller reports the version error
    instead of silently ignoring it.
    """
    declaration = document.get(SCHEMA_DECLARATION_KEY)
    if declaration is None:
        return None
    if not isinstance(declaration, str):
        return -1
    match = _SCHEMA_URL_RE.search(declaration)
    if match is None:
        return -1
    return int(match.group(1))


def format_version_error(declared: int) -> CheckIssue:
    if declared < 0:
        message = (
            "датасет заявил версию формата, которую не удалось разобрать; "
            f"встроенная схема описывает v{FORMAT_VERSION}"
        )
    else:
        message = (
            f"датасет заявляет версию формата v{declared}, а встроенная схема описывает "
            f"v{FORMAT_VERSION}; обновление схем — явная поставка с релизом"
        )
    return CheckIssue(
        code="UNSUPPORTED_FORMAT",
        severity=Severity.ERROR,
        path="$schema",
        message=message,
    )


def _render_path(error: ValidationError) -> str:
    parts: list[str] = []
    for element in error.absolute_path:
        if isinstance(element, int):
            parts.append(f"[{element}]")
        else:
            parts.append(f".{element}" if parts else str(element))
    return "".join(parts) or "<корень>"


def _render_message(error: ValidationError) -> str:
    detail = error.message
    for needle, template in _MESSAGE_TEMPLATES:
        if needle in detail:
            return template.format(detail=detail)
    return f"ошибка схемы: {detail}"


def validate_shape(document: dict[str, Any], bundle: LssSchemaBundle) -> list[CheckIssue]:
    """Validate a dataset document against the bundled wizard-dataset schema."""
    # The version gate has already consumed the declaration; the strict root
    # forbids the property, so validate a copy without it.
    payload = {key: value for key, value in document.items() if key != SCHEMA_DECLARATION_KEY}
    # The modern ``referencing`` registry replaces the resolver API deprecated
    # since jsonschema 4.18: every bundled artifact is registered under its
    # own ``$id``, so cross-file ``$ref``s resolve offline from the store alone.
    registry = Registry().with_resources(
        (uri, Resource(contents=schema, specification=DRAFT7)) for uri, schema in bundle.schema_store.items()
    )
    validator = Draft7Validator(bundle.dataset_schema, registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda error: (str(_render_path(error)), error.message))
    return [
        CheckIssue(
            code="SCHEMA",
            severity=Severity.ERROR,
            path=_render_path(error),
            message=_render_message(error),
        )
        for error in errors
    ]


def validate_character_shape(
    document: dict[str, Any], bundle: LssSchemaBundle
) -> list[CheckIssue]:
    """Validate a character-export envelope against the bundled character schema
    (add-dnd-game-face task 9.1, design Д7).

    The caller hands the envelope with ``data`` ALREADY PARSED: the string form
    of the live export is the envelope-checker's business (``CHAR_DATA``), and
    the schema speaks only about the parsed document — paths therefore read
    ``data.…`` all the way down. Same store, same RU renderings, same stable
    ``SCHEMA`` code as the dataset half.
    """
    registry = Registry().with_resources(
        (uri, Resource(contents=schema, specification=DRAFT7))
        for uri, schema in bundle.schema_store.items()
    )
    validator = Draft7Validator(bundle.character_schema, registry=registry)
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (str(_render_path(error)), error.message),
    )
    return [
        CheckIssue(
            code="SCHEMA",
            severity=Severity.ERROR,
            path=_render_path(error),
            message=_render_message(error),
        )
        for error in errors
    ]
