"""Unified validation report contract (change add-dnd-module-foundation, NRI-00xx task 4.5).

The report is the single output shape of the dataset validator: import screen
(phase 5) and future generation phases consume the same frozen issues. Each
issue carries a stable ``code`` (machine contract — never reword codes), a
``severity`` category, a human path to the place in the document
(section, entity id, grant type) and a Russian user-facing text.

Importability is decided by exactly one category: errors block the import,
warnings never do (spec dnd-dataset-validator «Порог импорта»).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    """Issue category; mirrors the LSS lint error/warning split."""

    ERROR = "error"
    WARNING = "warning"


# Deterministic issue ordering: errors first, then by path, then code, then text.
_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1}


def issue_sort_key(issue: "CheckIssue") -> tuple[int, str, str, str]:
    return (
        _SEVERITY_ORDER[issue.severity],
        issue.path,
        issue.code,
        issue.message,
    )


@dataclass(frozen=True)
class CheckIssue:
    """One validator finding: stable code + category + document path + RU text."""

    code: str
    severity: Severity
    path: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Frozen, ordered list of issues — deterministic for the same input file."""

    issues: tuple[CheckIssue, ...] = ()

    @staticmethod
    def of(issues: "list[CheckIssue]") -> "ValidationReport":
        """Build a report with issues normalized into the canonical order."""
        return ValidationReport(issues=tuple(sorted(issues, key=issue_sort_key)))

    @property
    def errors(self) -> tuple[CheckIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[CheckIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    @property
    def import_allowed(self) -> bool:
        """Only errors block the import (spec scenario «Порог импорта»)."""
        return not self.errors
