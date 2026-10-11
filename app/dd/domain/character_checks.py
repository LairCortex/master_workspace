"""Domain checks over an LSS character export (add-dnd-game-face task 9.1,
design Д7; spec dnd-character-import «Документ проверяется по схеме формата»).

The dataset half of the format gate is JSON-Schema + the LSS lint list; the
character half gets its own small domain layer over the bundled
``character.json`` shape: the ENVELOPE gates (readable JSON, ``jsonType``,
``version``, a parseable ``data``) answer as errors with an early stop — a
file that is not a character export of the supported version has nothing
left to check — while the live-export keys the wizard attaches
(``bonusesSkills``/``bonusesStats``, ``createdAt``, ``wizardStep``/``choices``)
are legal content: warnings, import allowed, the report lists them (spec
scenario «Живой экспорт проходит с предупреждениями»; the deprecated channel
stays readable through the raw snapshot, never silently dropped).

Issue codes are the stable machine contract (`CHAR_*` per Д7; ``INVALID_JSON``
and ``SCHEMA`` ride the codes shared with the datasets).
"""
from __future__ import annotations

import json
from typing import Any

from app.dd.domain.validation_report import CheckIssue, Severity

# --- issue codes (stable machine contract) ---------------------------------
CODE_CHAR_JSON_TYPE = "CHAR_JSON_TYPE"
CODE_CHAR_UNSUPPORTED_VERSION = "CHAR_UNSUPPORTED_VERSION"
CODE_CHAR_DATA = "CHAR_DATA"
CODE_CHAR_DEPRECATED_BONUSES = "CHAR_DEPRECATED_BONUSES"
CODE_CHAR_SERVICE_KEYS = "CHAR_SERVICE_KEYS"
#: The avatar travelled with the document but could not be stored (a data URI
#: that is not an image, a store that refused the bytes) — warning: the name
#: snapshot of its text form keeps the fact visible (spec: nothing is lost
#: silently, and a damaged avatar must not refuse the whole character).
CODE_CHAR_AVATAR = "CHAR_AVATAR"

#: Envelope keys the live wizard export carries that no product surface owns.
ENVELOPE_SERVICE_KEYS: tuple[str, ...] = ("createdAt",)
#: Same family inside the character document.
DOCUMENT_SERVICE_KEYS: tuple[str, ...] = ("wizardStep", "choices")
#: The retired bonus channels a live download still fills; ``bonuses`` is the
#: single current one (Д7 — their content survives in the raw snapshot).
DEPRECATED_BONUS_KEYS: tuple[str, ...] = ("bonusesSkills", "bonusesStats")


def _issue(code: str, severity: Severity, path: str, message: str) -> CheckIssue:
    return CheckIssue(code=code, severity=severity, path=path, message=message)


def envelope_gate(envelope: dict[str, Any], expected_version: str) -> list[CheckIssue]:
    """The two envelope identity errors: a foreign ``jsonType`` and a version
    this build has no schema for. Non-empty answers mean STOP — the caller
    never approaches the schema or the document checks after them."""
    issues: list[CheckIssue] = []
    json_type = envelope.get("jsonType")
    if json_type != "character":
        issues.append(
            _issue(
                CODE_CHAR_JSON_TYPE,
                Severity.ERROR,
                "jsonType",
                "файл не является экспортом персонажа: ожидался jsonType «character»",
            )
        )
    version = envelope.get("version")
    if version is None:
        issues.append(
            _issue(
                CODE_CHAR_UNSUPPORTED_VERSION,
                Severity.ERROR,
                "version",
                f"экспорт не заявил версию формата; встроенная схема описывает v{expected_version}",
            )
        )
    elif version != expected_version:
        issues.append(
            _issue(
                CODE_CHAR_UNSUPPORTED_VERSION,
                Severity.ERROR,
                "version",
                f"экспорт заявляет версию формата {version!r}, а встроенная схема описывает "
                f"v{expected_version}; обновление схем — явная поставка с релизом",
            )
        )
    return issues


def parse_data(envelope: dict[str, Any]) -> tuple[Any, CheckIssue | None]:
    """The envelope's ``data`` half: the live export carries a JSON STRING
    (it is parsed here), an inline object is accepted as it stands. Anything
    else — a missing key, a string that no longer parses, a non-object body —
    is the spec's «разрушенная структура data»: one error, ``None`` data."""
    raw = envelope.get("data")
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            return None, _issue(
                CODE_CHAR_DATA,
                Severity.ERROR,
                "data",
                f"содержимое data не является корректным JSON: {error.msg} (строка {error.lineno})",
            )
        if isinstance(parsed, dict):
            return parsed, None
        return None, _issue(
            CODE_CHAR_DATA,
            Severity.ERROR,
            "data",
            "разобранный документ персонажа обязан быть объектом",
        )
    return None, _issue(
        CODE_CHAR_DATA,
        Severity.ERROR,
        "data",
        "ключ data отсутствует или не является JSON-строкой/объектом",
    )


def document_warnings(
    envelope: dict[str, Any], data: dict[str, Any]
) -> list[CheckIssue]:
    """The live-export warnings (Д7): retired bonus channels and service
    keys. Every key is one legal citizen of the file, so each gets its own
    honest line in the report instead of a blanket sentence."""
    issues: list[CheckIssue] = []
    for key in DEPRECATED_BONUS_KEYS:
        if key in data:
            issues.append(
                _issue(
                    CODE_CHAR_DEPRECATED_BONUSES,
                    Severity.WARNING,
                    f"data.{key}",
                    f"устаревший канал бонусов {key!r}: бонусы читали бы из data.bonuses, "
                    "а содержимое этого ключа сохранено в сырой копии персонажа",
                )
            )
    for key in ENVELOPE_SERVICE_KEYS:
        if key in envelope:
            issues.append(
                _issue(
                    CODE_CHAR_SERVICE_KEYS,
                    Severity.WARNING,
                    key,
                    f"служебный ключ живого экспорта {key!r} импортом не используется "
                    "и сохранён в сырой копии",
                )
            )
    for key in DOCUMENT_SERVICE_KEYS:
        if key in data:
            issues.append(
                _issue(
                    CODE_CHAR_SERVICE_KEYS,
                    Severity.WARNING,
                    f"data.{key}",
                    f"служебный ключ живого экспорта {key!r} импортом не используется "
                    "и сохранён в сырой копии",
                )
            )
    return issues
