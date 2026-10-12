"""Unified validation report contract (change add-dnd-module-foundation, NRI-00xx task 4.5;
path notation fixed by fix-dnd-followups).

The report is the single output shape of the dataset validator: import screen
(phase 5) and future generation phases consume the same frozen issues. Each
issue carries a stable ``code`` (machine contract — never reword codes), a
``severity`` category, a human path to the place in the document
(section, entity id, index) and a Russian user-facing text.

Report paths print in ONE notation — ``поле.поле[индекс].поле`` from the
document root, identical across every check and every channel (spec
dnd-dataset-validator «Путь ведёт к месту в одной нотации», design Д3). The
checks keep building their own path strings; :meth:`ValidationReport.of`
formats each path through :func:`format_issue_path` on its way into the
frozen report — one formatting point at report assembly, not a per-check
rewrite. Bracketed placeholders («<файл>», «<корень>», …) name findings
without a location inside the document and print through unchanged.

Importability is decided by exactly one category: errors block the import,
warnings never do (spec dnd-dataset-validator «Порог импорта»).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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


def format_issue_path(path: str) -> str:
    """Print one check path in the single report notation (design Д3).

    Pure formatting — every check keeps emitting its own path string: the
    colon joins of the grant traversal read as dots, the ``(grant type)``
    stamps of the ladder print away (the list index already names the
    grant), and the «блок · относительный путь» re-anchor of the import
    re-joins with a dot. Everything inside ``[…]`` (entity id, slug, spell
    name) survives verbatim; placeholder paths («<файл>», «<корень>»,
    «<ответ модели>», …) are not document locations and pass through. The
    function is idempotent: a path already in the notation is untouched.
    """
    out: list[str] = []
    depth = 0  # bracket nesting: inside […] every character prints as it stands
    index = 0
    while index < len(path):
        char = path[index]
        if char == "[":
            depth += 1
            out.append(char)
        elif char == "]" and depth:
            depth -= 1
            out.append(char)
        elif depth:
            out.append(char)
        elif char == "(":
            close = path.find(")", index)
            if close == -1:
                out.append(char)
            else:
                index = close  # print the annotation stamp away entirely
        elif char == ":":
            out.append(".")
        elif path.startswith(" · ", index):
            out.append(".")
            index += 2
        else:
            out.append(char)
        index += 1
    return "".join(out)


@dataclass(frozen=True)
class ValidationReport:
    """Frozen, ordered list of issues — deterministic for the same input file."""

    issues: tuple[CheckIssue, ...] = ()

    @staticmethod
    def of(issues: "list[CheckIssue]") -> "ValidationReport":
        """Build a report: every path printed in the one notation, every
        issue normalized into the canonical order."""
        return ValidationReport(
            issues=tuple(
                sorted(
                    (
                        replace(issue, path=format_issue_path(issue.path))
                        for issue in issues
                    ),
                    key=issue_sort_key,
                )
            )
        )

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
