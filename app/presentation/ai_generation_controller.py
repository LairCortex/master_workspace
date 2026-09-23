"""AI generation controller — batch/single field generation orchestration.

Extracted verbatim from ``Application._wire_ai_buttons`` (audit finding B1,
design D6): the whole wave state machine that used to live as ~230 lines of
closures inside the composition root now belongs to the presentation layer.
``Application._wire_ai_buttons`` is a one-line delegation here; per-dialog
wave state is created per :meth:`AiGenerationController.wire` call exactly
like the former closures captured it.

Generation requests are described by :class:`GenerationTarget` (design D6
replaces the former 6-positional ``_launch``/``request_generation`` pair).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Protocol, runtime_checkable

from PySide6.QtWidgets import QMessageBox

from app.application.services.llm_service import LlmService
from app.presentation.viewmodels.llm_viewmodel import GenerationTarget, LlmViewModel


@runtime_checkable
class AiCapableDialog(Protocol):
    """Contract of a dialog hosting AI-assist buttons (audit B1, design D5).

    The real surface both AI-capable dialogs (the entity card and the event
    dialog) had was checked by scattered ``hasattr``/``getattr`` probes; the
    dialogs now implement it through ``AiCapableDialogBase`` (the shared
    conformance base), and the controller is the single place that asks the
    question "is this dialog AI-capable?" — answered against this contract.
    """

    def get_ai_buttons(self) -> list[Any]:
        """Field-level AI buttons hosted by the dialog."""

    def get_entity_button(self) -> Any:
        """Top-right «сгенерировать всё» button (wave start/cancel)."""

    def set_save_locked(self, locked: bool) -> None:
        """Block/unblock the dialog's save while a generation runs."""

    def set_close_guard(self, fn: Callable[[], None]) -> None:
        """Install the close-time guard invoked by X/«Отмена» paths."""


class AiGenerationController:
    """Connects a dialog's AI-assist buttons to the LLM ViewModel.

    Field buttons trigger single-field generation; the entity button
    (top-right of the form) starts a parallel wave over all fields and
    becomes its cancel while the wave runs. At most one wave per
    dialog at a time; "Save" is locked for the whole generation.
    """

    def __init__(self, llm_vm: LlmViewModel, service: LlmService) -> None:
        self._llm_vm = llm_vm
        self._service = service

    # ── public seam ─────────────────────────────────────────────────────────

    def wire(self, dialog) -> None:
        """Connect one dialog's AI buttons; dialogs without them are a no-op.

        The wave state below mirrors the behavior the former
        ``Application._wire_ai_buttons`` closures had: it is per-dialog
        (fresh on every ``wire`` call) and is kept alive by the signal
        connections themselves.
        """
        if not isinstance(dialog, AiCapableDialog):
            return  # not an AI-capable dialog: nothing to wire
        llm_vm = self._llm_vm
        service = self._service
        log = logging.getLogger("llm.wire")

        # Per-dialog wave state shared by the field and entity-button handlers.
        # ``batch`` is None outside a wave, otherwise:
        #   {"fields": {field_id: (button, field_name, field_label)},
        #    "pending": set[field_id], "errors": {field_id: reason}}
        # ``single_field`` — field_id of the in-flight single generation (or None).
        # ``cancelled_fields`` — fields of a stopped wave: ALL late results/
        # errors for them are dropped (cancellation is not an error). The
        # marker stays until a new generation of the same field is started.
        state: dict = {"batch": None, "single_field": None, "cancelled_fields": set()}

        def _entity_button():
            return dialog.get_entity_button()

        def _any_generating() -> bool:
            return (
                any(b.is_generating for b in dialog.get_ai_buttons())
                or state["batch"] is not None
                or state["single_field"] is not None
            )

        def _sync_controls() -> None:
            dialog.set_save_locked(_any_generating())
            ebtn = _entity_button()
            if ebtn is not None:
                ebtn.set_wave_running(state["batch"] is not None)
                ebtn.set_single_in_flight(
                    state["batch"] is None and state["single_field"] is not None
                )

        buttons_by_id = {
            f"{b.entity_type}.{b.field_name}": b for b in dialog.get_ai_buttons()
        }

        def _fail_field(field_id: str, err: str) -> None:
            """Terminal failure of a dialog field (provider error or an
            unexpected break of request_generation): the single completion
            path for failures, so the dialog can never be left stuck (no
            leaked single_field / batch pending); D6: visible warning."""
            if field_id in state["cancelled_fields"]:
                return  # late signal for a cancelled field
            btn = buttons_by_id[field_id]
            btn.set_generating(False)
            batch = state["batch"]
            if batch is not None and field_id in batch["fields"]:
                batch["errors"][field_id] = err
                batch["pending"].discard(field_id)
                if not batch["pending"]:
                    _finish_wave()
            else:
                if state["single_field"] == field_id:
                    state["single_field"] = None
                QMessageBox.warning(
                    dialog,
                    "AI-ассистент",
                    f"Не удалось сгенерировать поле «{btn.field_label}»: {err}",
                )
                _sync_controls()

        def _launch(target: GenerationTarget) -> None:
            async def _do():
                try:
                    await llm_vm.request_generation(target)
                except Exception as exc:
                    # request_generation converts provider errors into
                    # generation_error; this only catches unexpected breaks —
                    # routed through _fail_field so the dialog never sticks.
                    log.error("Generation failed: %s — %s", target.field_id, exc)
                    _fail_field(target.field_id, str(exc))

            asyncio.ensure_future(_do())

        def _target(btn, field_id: str, field_name: str, field_label: str,
                    current_text: str) -> GenerationTarget:
            return GenerationTarget(
                field_id=field_id,
                entity_type=btn.entity_type,
                field_name=field_name,
                field_label=field_label,
                current_text=current_text,
                owner=dialog,
            )

        def _show_batch_errors(errors: dict, fields: dict) -> None:
            """One aggregated dialog for the failed fields of a finished wave.

            A shared reason is stated once for the whole list; different
            reasons are listed per field.
            """
            items = [(fields[fid][2], reason) for fid, reason in errors.items()]
            reasons = {reason for _label, reason in items}
            if len(reasons) == 1:
                lines = "\n".join(f"- «{label}»" for label, _reason in items)
                text = f"Не удалось сгенерировать поля:\n{lines}\n\nПричина: {next(iter(reasons))}"
            else:
                lines = "\n".join(f"- «{label}»: {reason}" for label, reason in items)
                text = f"Не удалось сгенерировать поля:\n{lines}"
            QMessageBox.warning(dialog, "AI-ассистент", text)

        def _finish_wave() -> None:
            # Every field resets its own button in the finishing handler
            # before dropping out of ``pending``, so by the time the counter
            # reaches zero the whole wave is already unblocked.
            batch = state["batch"]
            state["batch"] = None
            _sync_controls()
            if batch["errors"]:
                _show_batch_errors(batch["errors"], batch["fields"])

        def _stop_all_no_error() -> None:
            """End the wave/single generation without an error dialog: cancel
            the requests and synchronously reset the buttons; results already
            written into fields stay there."""
            batch = state["batch"]
            stopping: set[str] = set(batch["fields"]) if batch is not None else set()
            if state["single_field"] is not None:
                stopping.add(state["single_field"])
            state["cancelled_fields"] |= stopping
            state["batch"] = None
            state["single_field"] = None
            service.cancel_all(dialog)
            for btn in dialog.get_ai_buttons():
                btn.set_generating(False)
            _sync_controls()

        def _start_wave() -> None:
            # Reaches here only from the entity button, which emits
            # batch_requested only when ready and no generation is running.
            fields: dict[str, tuple] = {}
            for btn in dialog.get_ai_buttons():
                field_id = f"{btn.entity_type}.{btn.field_name}"
                fields[field_id] = (btn, btn.field_name, btn.field_label)
                # A new wave invalidates the cancellation markers of a previous one.
                state["cancelled_fields"].discard(field_id)
                btn.set_generating(True)
            state["batch"] = {"fields": fields, "pending": set(fields), "errors": {}}
            _sync_controls()
            for field_id, (btn, fn, fl) in fields.items():
                # Existing field text is part of the prompt; the result
                # overrides it (safe override per spec).
                _launch(_target(btn, field_id, fn, fl, btn.current_text))

        for btn in dialog.get_ai_buttons():
            btn.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            llm_vm.model_status_changed.connect(
                lambda _s, _b=btn: _b.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            )

            def _on_generate(et, fn, fl, ct, _btn=btn):
                field_id = f"{et}.{fn}"
                if _any_generating():
                    return  # at most one wave per dialog
                log.info("AI button clicked: %s, label=%s, text=%r", field_id, fl, ct[:50] if ct else "")
                # A new run invalidates the cancellation marker of a previous wave.
                state["cancelled_fields"].discard(field_id)
                _btn.set_generating(True)
                state["single_field"] = field_id
                _sync_controls()
                _launch(_target(_btn, field_id, fn, fl, ct))

            btn.generate_requested.connect(_on_generate)

            def _on_field_finished(owner, fid, text, _btn=btn, _et=btn.entity_type, _fn=btn.field_name):
                field_id = f"{_et}.{_fn}"
                # owner is not dialog → the signal belongs to another (nested)
                # dialog of the same entity type: its results must not land here.
                if owner is not dialog or fid != field_id:
                    return
                if field_id in state["cancelled_fields"]:
                    return  # late signal for a cancelled field
                _btn.set_result_text(text)
                batch = state["batch"]
                if batch is not None and field_id in batch["fields"]:
                    batch["pending"].discard(field_id)
                    if not batch["pending"]:
                        _finish_wave()
                else:
                    if state["single_field"] == field_id:
                        state["single_field"] = None
                    _sync_controls()

            def _on_field_error(owner, fid, err, _et=btn.entity_type, _fn=btn.field_name):
                field_id = f"{_et}.{_fn}"
                if owner is not dialog or fid != field_id:
                    return
                _fail_field(fid, err)

            llm_vm.generation_finished.connect(_on_field_finished)
            llm_vm.generation_error.connect(_on_field_error)

        def _close_guard() -> None:
            """Close path (X / «Отмена») while a generation may be in flight.

            In-flight requests → confirmation with a warning; requests only
            waiting between retries → silent cancel. Either way the wave is
            cancelled after the decision (cancellation is not an error).
            """
            if not _any_generating():
                dialog.reject()
                return
            in_flight = service.count_in_flight(dialog)
            if in_flight > 0:
                answer = QMessageBox.question(
                    dialog,
                    "Генерация",
                    f"Идёт запрос к LLM ({in_flight} полей). Если закрыть, запрос "
                    f"будет прерван и результат не появится.",
                    buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    defaultButton=QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            _stop_all_no_error()
            dialog.reject()

        dialog.set_close_guard(_close_guard)

        ebtn = _entity_button()
        if ebtn is not None:
            ebtn.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            llm_vm.model_status_changed.connect(
                lambda _s, _e=ebtn: _e.update_llm_state(llm_vm.status, llm_vm.has_world_prompt)
            )
            ebtn.batch_requested.connect(_start_wave)
            ebtn.batch_cancel_requested.connect(_stop_all_no_error)
