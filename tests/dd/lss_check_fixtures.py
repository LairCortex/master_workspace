"""Shared builders for the cross-field check tests (add-dnd-module-foundation, tasks 4.3/4.4)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.dd.domain.lss_checks import ConnectedDataset, LssVocabulary, run_cross_checks
from app.dd.domain.validation_report import CheckIssue
from app.dd.infrastructure.lss_schemas import load_bundle


@lru_cache(maxsize=1)
def shared_vocabulary() -> LssVocabulary:
    return load_bundle().vocabulary


def base_dataset(**overrides: Any) -> dict[str, Any]:
    dataset: dict[str, Any] = {
        "id": "hb-set",
        "name": "Хоумбрю",
        "system": "dnd",
        "edition": "2024",
        "author": "тест",
        "license": "CC-BY-4.0",
    }
    dataset.update(overrides)
    return dataset


def check_document(
    document: dict[str, Any],
    *,
    connected: tuple[ConnectedDataset, ...] = (),
    spell_slugs: list[str] | None = None,
    own_is_official: bool = False,
) -> list[CheckIssue]:
    return run_cross_checks(
        document,
        shared_vocabulary(),
        connected=connected,
        spell_slugs=spell_slugs,
        own_is_official=own_is_official,
    )


def codes(issues: list[CheckIssue]) -> list[str]:
    return [issue.code for issue in issues]


def class_with(*grants: dict[str, Any], entity_id: str = "wizard", **extra: Any) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "id": entity_id,
        "label": entity_id,
        # schema-valid minimal info block (DatasetClass.info requires both fields)
        "info": {"primaryStats": [["int"]], "complexity": 1},
        "grants": list(grants),
    }
    entity.update(extra)
    return entity


def srd_like_connected(dataset_id: str = "srd-2024") -> ConnectedDataset:
    """A connected official set: its wizard/cleric classes and alert feat cover links."""
    from app.dd.domain.dataset import DatasetSource

    return ConnectedDataset(
        dataset_id=dataset_id,
        source=DatasetSource.SRD,
        document={
            "classes": [{"id": "wizard", "label": "Wizard", "info": {}, "grants": []}],
            "races": [{"id": "elf", "label": "Elf", "size": "medium", "grants": []}],
            "feats": [{"id": "alert", "label": "Alert", "grants": []}],
        },
    )
