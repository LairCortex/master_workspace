"""Dataset validation service (change add-dnd-module-foundation, tasks 4.1–4.5).

Pure orchestration without network: file content in, frozen report out. The
pipeline is: JSON parse → format-version gate → JSON-Schema shape validation
against the bundled LSS schemas → the full cross-field check list over ALL
datasets connected to the game (spec: link resolution is corpus-wide). The
service never writes anything; the import screen (phase 5) decides visibility
of the outcome, the report's ``import_allowed`` decides the threshold.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from app.dd.domain.dataset import DatasetSource
from app.dd.domain.lss_checks import CODE_INVALID_JSON, ConnectedDataset, run_cross_checks
from app.dd.domain.validation_report import CheckIssue, Severity, ValidationReport
from app.dd.infrastructure.lss_schemas import (
    FORMAT_VERSION,
    LssSchemaBundle,
    extract_format_version,
    format_version_error,
    load_bundle,
    validate_shape,
)


class DatasetValidatorService:
    """One validator for the whole app: import screen and future phases alike."""

    def __init__(self, bundle: LssSchemaBundle | None = None) -> None:
        self._bundle = bundle if bundle is not None else load_bundle()

    def validate(
        self,
        content: str,
        connected: Sequence[ConnectedDataset] = (),
        spell_slugs: Sequence[str] | None = None,
        source: DatasetSource = DatasetSource.HOMEBREW,
    ) -> ValidationReport:
        """Check one dataset file; the report is deterministic for the same input.

        ``connected`` are the other datasets connected to the game (link
        resolution domain); ``spell_slugs`` — the downloaded SRD spell-slug
        lists, ``None`` skips exactly the slug check (LSS prescription);
        ``source`` marks an official file (its own class ids cover spell lists
        the way the LSS built-in database does for the SRD classes).
        """
        try:
            document: Any = json.loads(content)
        except json.JSONDecodeError as error:
            return ValidationReport.of(
                [
                    CheckIssue(
                        code=CODE_INVALID_JSON,
                        severity=Severity.ERROR,
                        path="<файл>",
                        message=f"файл не является корректным JSON: {error.msg} (строка {error.lineno})",
                    )
                ]
            )
        if not isinstance(document, dict):
            return ValidationReport.of(
                [
                    CheckIssue(
                        code=CODE_INVALID_JSON,
                        severity=Severity.ERROR,
                        path="<файл>",
                        message="корень датасета обязан быть JSON-объектом",
                    )
                ]
            )
        declared = extract_format_version(document)
        if declared is not None and declared != FORMAT_VERSION:
            return ValidationReport.of([format_version_error(declared)])
        issues = validate_shape(document, self._bundle)
        issues.extend(
            run_cross_checks(
                document,
                self._bundle.vocabulary,
                connected=connected,
                spell_slugs=spell_slugs,
                own_is_official=source is DatasetSource.SRD,
            )
        )
        return ValidationReport.of(issues)
