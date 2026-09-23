"""Frozen dialog-result contracts (audit B3, design D5).

Every save dialog used to hand the connector an untyped ``dict`` whose keys
were re-derived (and re-popped, four times over) in the wiring — a rename in
the dialog silently became a ``KeyError`` or a defaulted field at the save
site. The results are now contracts: one frozen dataclass per dialog flow
(event create / event edit, entity create / entity edit), and the connector
only reads declared attributes.

``RelatedRef`` retires the junk dict key ``_existing_id``: a desired link
captured by the event dialog is an object with a regular ``existing_id``
field. The application-layer synchronizer (``relation_sync.sync_related``)
still speaks its keyword-mapping wire format; :func:`relation_items` is the
single presentation-side translation into it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

#: The four M2M attribute names of an event, in the registry's EVENT order.
#: Part of the contract: the dialog fills exactly these, the wiring forwards
#: them under exactly these keys.
EVENT_RELATION_ATTRS = ("organizations", "characters", "items", "locations")


@dataclass(frozen=True)
class RelatedRef:
    """One desired entity link captured by the event dialog's sections."""

    existing_id: int


def relation_items(refs: Sequence[RelatedRef]) -> list[dict[str, int]]:
    """Translate contract links into the synchronizer's ``_existing_id`` items."""
    return [{"_existing_id": ref.existing_id} for ref in refs]


@dataclass(frozen=True)
class EventDialogResult:
    """The common payload of both event-dialog flows (create and edit)."""

    name: str
    start_date: date
    end_date: date | None
    start_bc: bool
    end_bc: bool
    characteristics: str
    backstory: str
    event_type_id: Any
    organizations: tuple[RelatedRef, ...]
    characters: tuple[RelatedRef, ...]
    items: tuple[RelatedRef, ...]
    locations: tuple[RelatedRef, ...]

    def as_relations_payload(self) -> dict[str, list[dict[str, int]]]:
        """The four desired lists in the service's wire format."""
        return {
            attr: relation_items(getattr(self, attr))
            for attr in EVENT_RELATION_ATTRS
        }


@dataclass(frozen=True)
class EventCreateResult(EventDialogResult):
    """The event dialog was opened to create an event."""


@dataclass(frozen=True)
class EventEditResult(EventDialogResult):
    """The event dialog was opened to edit the event of ``event_id``."""

    event_id: int


@dataclass(frozen=True)
class EntityCreateResult:
    """A freshly captured entity card (solo create or related popup).

    ``fields`` are the model keyword arguments (name, ratings, dates, eras,
    the type's extra texts and ``image_id`` when the card shows an image);
    ``related_changes`` is the section state handed to
    ``EntityService.apply_related_changes`` (empty on the solo-create flow,
    whose dialog never loads linkable sections).
    """

    fields: Mapping[str, Any]
    characteristics: str
    backstory: str
    related_changes: Mapping[str, Any]


@dataclass(frozen=True)
class EntityEditResult(EntityCreateResult):
    """The entity card was opened on a stored entity (``entity_id``)."""

    entity_id: int
