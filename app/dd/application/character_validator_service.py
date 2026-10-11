"""The character-export validation pipeline (add-dnd-game-face task 9.1;
design Д7; spec dnd-character-import «Документ проверяется по схеме формата»).

File text in, frozen report out — the same posture as the dataset validator,
with the character's own gate order:

1. the envelope parses as a JSON object (``INVALID_JSON`` shared code);
2. the envelope identity gates (``CHAR_JSON_TYPE``, ``CHAR_UNSUPPORTED_VERSION``)
   stop the pipeline — a foreign file or a format revision this build has no
   schema for has nothing left to check (the datasets' version gate posts the
   same early stop);
3. ``data`` yields its parsed document (``CHAR_DATA`` on a destroyed half;
   the live string form is parsed here);
4. the combined envelope (with the parsed ``data`` substituted) passes the
   bundled ``character.json`` shape — ``SCHEMA`` errors with ``data.…`` paths;
5. the live-export warnings ride on top (deprecated bonus channels, service
   keys) — never blocking (spec scenario «Живой экспорт проходит с
   предупреждениями»).

Pure orchestration: no session, no disk, no network. The import service runs
this first and only then decides about writes; the second value of the answer
is the parsed document the import lays out (``None`` when nothing survived
the gates — every error branch carries it).
"""
from __future__ import annotations

import json
from typing import Any

from app.dd.domain.character_checks import (
    document_warnings,
    envelope_gate,
    parse_data,
)
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.dd.infrastructure.lss_schemas import (
    CHARACTER_FORMAT_VERSION,
    LssSchemaBundle,
    load_bundle,
    validate_character_shape,
)


class CharacterValidatorService:
    """One validator for the whole app: the import flows share this door."""

    def __init__(self, bundle: LssSchemaBundle | None = None) -> None:
        self._bundle = bundle if bundle is not None else load_bundle()

    def validate(self, content: str) -> tuple[ValidationReport, dict[str, Any] | None]:
        """Check one character-export text; deterministic for the same input."""
        try:
            envelope: Any = json.loads(content)
        except json.JSONDecodeError as error:
            return (
                ValidationReport.of(
                    [
                        CheckIssue(
                            code="INVALID_JSON",
                            severity=Severity.ERROR,
                            path="<файл>",
                            message=(
                                f"файл не является корректным JSON: {error.msg} "
                                f"(строка {error.lineno})"
                            ),
                        )
                    ]
                ),
                None,
            )
        if not isinstance(envelope, dict):
            return (
                ValidationReport.of(
                    [
                        CheckIssue(
                            code="INVALID_JSON",
                            severity=Severity.ERROR,
                            path="<файл>",
                            message="корень экспорта персонажа обязан быть JSON-объектом",
                        )
                    ]
                ),
                None,
            )
        gate = envelope_gate(envelope, CHARACTER_FORMAT_VERSION)
        if gate:
            return ValidationReport.of(gate), None
        data, data_issue = parse_data(envelope)
        if data_issue is not None:
            return ValidationReport.of([data_issue]), None
        issues = validate_character_shape(
            {**envelope, "data": data}, self._bundle
        )
        issues.extend(document_warnings(envelope, data))
        return ValidationReport.of(issues), data
