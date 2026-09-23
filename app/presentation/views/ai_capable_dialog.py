"""Shared AI-capability base for dialogs hosting AI-assist buttons.

The entity card and the event dialog exposed the identical proxy surface
to the AI wiring (audit finding B1/B6 duplicate, design D5): the same
five methods were written twice. The controller addresses dialogs through
the :class:`app.presentation.ai_generation_controller.AiCapableDialog`
contract; this base is its single concrete satisfaction, so a dialog
declaring conformance is a dialog inheriting this class.

(Inheriting the ``Protocol`` itself from a QObject-derived class is
impossible — ``_ProtocolMeta`` and the Shiboken metaclass conflict — so
the explicit declaration of conformance is the base itself, guarded at
runtime by the controller's ``isinstance(dialog, AiCapableDialog)`` gate.)

Inheritors must set in their constructors:
* ``_ai_buttons`` — the field-level AI button proxies;
* ``_entity_button`` — the wave start/cancel proxy;
* ``vm`` — the island view model exposing ``set_save_locked(bool)``;
* ``_close_guard`` — ``None`` until the generation controller installs it.
"""
from __future__ import annotations

from typing import Any, Callable


class AiCapableDialogBase:
    """The controller-facing proxy package shared by all AI-capable dialogs."""

    # Declared here for readability; every dialog initializes them itself.
    _ai_buttons: list[Any]
    _entity_button: Any
    _close_guard: Callable[[], None] | None

    def get_ai_buttons(self) -> list[Any]:
        return list(self._ai_buttons)

    def get_entity_button(self) -> Any:
        return self._entity_button

    def set_save_locked(self, locked: bool) -> None:
        self.vm.set_save_locked(locked)

    def set_close_guard(self, fn: Callable[[], None]) -> None:
        self._close_guard = fn

    def _is_generation_active(self) -> bool:
        return any(button.is_generating for button in self._ai_buttons) or (
            self._entity_button.is_cancelling
        )
