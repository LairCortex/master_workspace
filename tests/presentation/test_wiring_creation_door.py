"""The connector's creation door (dd-card-redesign, checkpoint-2 audit;
spec dnd-character-extension «Новая карточка с пустыми разделами» —
«сохранение создаёт персонажа и расширение»).

Right after the kernel row of a new entity lands, the connector knocks the
optional ``on_entity_created(key, source_id)`` door of every visible external
source — the module stands its extension up beside the kernel creation, so
the reopened card's sections are empty because nothing was stored, not
because the extension is missing. What is pinned here is the connector half:

* visible sources answering the door get the pair (the id stringified — the
  protocol codec), awaited on this task;
* a source without the door is skipped without special casing (the kernel-
  only game costs nothing), an invisible (detached) source is not knocked;
* a refusal raises — the caller's modal owns the report, a half-created
  extension is never a silence.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.presentation.wiring import ApplicationWiring


def _wiring(sources):
    return ApplicationWiring(
        SimpleNamespace(_image_store=None),
        SimpleNamespace(),
        None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
        external_sources=sources,
    )


class _DoorSource:
    def __init__(self, *, visible=True, raises=False):
        self.visible = visible
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    async def on_entity_created(self, key, source_id):
        self.calls.append((key, source_id))
        await asyncio.sleep(0)
        if self._raises:
            raise RuntimeError("расширение не создано")


async def test_doorless_sources_are_skipped_without_special_casing():
    # The kernel-only composition: no source, or sources without the door —
    # the connector answers the creation as if the module never existed.
    wiring = _wiring(())
    await wiring._external_entity_created("character", 5)

    class _NoDoor:
        visible = True

    wiring = _wiring((_NoDoor(),))
    await wiring._external_entity_created("character", 5)


async def test_a_sync_door_is_knocked_and_not_awaited():
    # The duck door admits both halves of the codec: the awaited answer
    # rides this task, a synchronous answer is taken as already done.
    class _SyncDoor:
        visible = True

        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def on_entity_created(self, key, source_id):
            self.calls.append((key, source_id))

    source = _SyncDoor()
    await _wiring((source,))._external_entity_created("character", 9)
    assert source.calls == [("character", "9")]


async def test_visible_sources_get_the_pair_and_a_refusal_raises():
    first = _DoorSource()
    hidden = _DoorSource(visible=False)
    doorless = object()
    wiring = _wiring((first, hidden, doorless))
    await wiring._external_entity_created("character", 5)
    assert first.calls == [("character", "5")]  # protocol string codec
    assert hidden.calls == []  # detached modules are not on the table

    failing = _DoorSource(raises=True)
    wiring = _wiring((failing,))
    with pytest.raises(RuntimeError, match="расширение"):
        await wiring._external_entity_created("character", 7)
    assert failing.calls == [("character", "7")]


async def test_creation_knock_reports_a_refusal_and_stays_quiet_on_success(
    monkeypatch,
):
    # The save path's half of the door: the kernel row already landed and
    # the sheet reported success, so the knock either passes in silence or
    # names the refusal in a modal — a half-created extension is never a
    # silence (spec dnd-character-extension «сохранение создаёт персонажа и
    # расширение»).
    from app.presentation import wiring as wiring_module

    boxes: list[tuple] = []

    def _critical(parent, title, text):
        boxes.append((title, text))

    monkeypatch.setattr(wiring_module.QMessageBox, "critical", staticmethod(_critical))

    ok = _DoorSource()
    await _wiring((ok,))._knock_creation_door(object(), "character", 5)
    assert ok.calls == [("character", "5")]
    assert boxes == []  # a clean creation reports nothing

    failing = _DoorSource(raises=True)
    await _wiring((failing,))._knock_creation_door(object(), "character", 7)
    assert failing.calls == [("character", "7")]
    assert len(boxes) == 1
    assert boxes[0][0] == "Ошибка"
    assert "модульный раздел" in boxes[0][1] and "расширение" in boxes[0][1]
