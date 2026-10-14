"""The D&D character's declarative «Основное» content (dd-card-redesign task
4.3, design Д2/Д8; spec dnd-character-mechanics «Шесть характеристик»,
«Владение спасбросками», «Навыки…», «Скорость…», «Ядреные тексты…»).

The source's ``module_blocks`` door hands the kernel a frame of descriptor
blocks plus this handler; the kernel paints the descriptors with its штатные
Theme controls at the two anchors and relays every committed write back here.
The handler owns the whole module semantics:

* **load** — the stored face (links, level), the mechanics block and the
  dataset snapshot arrive through the connector's session lock at
  construction; the frame is republished when they land (the door itself is
  sync, so the initial frame carries only the hidden-fields answer);
* **writes** — one locked operation each (write + re-read in ONE coroutine:
  a second ``run_locked`` from inside a locked task would deadlock, the
  frames' discipline); every derivative number is recomputed from the fresh
  read through :mod:`app.dd.domain.character_mechanics`, never stored;
* **gates** — the six ability values ride the all-or-nothing service gate
  (a partial edit answers the Russian refusal in a modeless box, the stored
  set untouched); saving-throw switches are owned by the class record while
  it names its saves (design Д8 — the switches print the state but cannot
  fight the class), the manual set wins when no class does;
* **doors** — the LSS file row (overwrite with the confirmation dance,
  save-raw, export) and «Дозаполнить ИИ» are the old «D&D» tab's flows,
  restated against the block channel: same services, same captions, same
  modeless boxes (never a nested loop), the no-dead-action posture (a door
  whose service is absent prints no button).

Teardown: :meth:`release` (the host's island teardown) cancels the in-flight
tasks — a released card answers nothing.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.dd.application.character_channel import (
    TOP_UP_NOTHING_REFUSAL,
    top_up_missing_fields,
)
from app.dd.application.character_import_service import CharacterImportStatus
from app.dd.domain.character import LEVEL_MAX, LINK_SLOTS, ReferenceLink
from app.dd.domain.character_mechanics import (
    ABILITY_KEYS,
    ABILITY_MAX,
    ABILITY_MIN,
    LSS_STAT_TO_ABILITY,
    PASSIVE_SENSE_SKILLS,
    SKILL_ABILITIES,
    check_value,
    class_record_saving_throws,
    jumps_and_carry,
    passive_sense_value,
    saving_throw_value,
    proficiency_bonus,
    skill_value,
    validate_ability_scores,
)
from app.dd.domain.character_render import SKILL_LABELS, STAT_LABELS
from app.dd.presentation.character_tab_frames import (
    CHARACTER_FILE_FILTER,
    EXPORT_FOR_LSS_TEXT,
    IMPORT_OVERWRITE_TEXT,
    OPEN_IN_BROWSER_TEXT,
    SAVE_RAW_TEXT,
    SOURCE_UNAVAILABLE_NOTE,
    TOP_UP_AI_TEXT,
    UNSET_ITEM,
    lss_sheet_url,
)

if TYPE_CHECKING:
    from app.dd.application.character_document_builder import CharacterDocumentBuilder
    from app.dd.application.character_import_service import (
        CharacterImportOutcome,
        CharacterImportService,
    )
    from app.dd.application.dataset_index_service import DatasetIndexService
    from app.dd.application.dnd_character_extension_service import (
        DndCharacterExtensionService,
    )
    from app.dd.application.generation_deps import GenerationDeps
    from app.dd.domain.character import DdCharacterExt
    from app.dd.domain.character_mechanics import CharacterMechanics

#: The kernel text fields the module owns (spec «Ядреные тексты персонажа
#: при модуле скрыты»): the channel hides them by name, the storage keeps
#: their contents untouched (hiding is a render fact, not a write).
HIDDEN_KERNEL_FIELDS: tuple[str, ...] = ("characteristics", "backstory")

#: The mechanics keys' Russian captions, derived from the domain's LSS-key
#: table so the two spellings can never drift apart (coding principle 2 —
#: :data:`app.dd.domain.character_mechanics.LSS_STAT_TO_ABILITY` is the one
#: knowledge, moved out of this module in dd-card-redesign task 6.2 because
#: the document builder reads the very same answer).
ABILITY_LABELS: dict[str, str] = {
    ability: STAT_LABELS[stat] for stat, ability in LSS_STAT_TO_ABILITY.items()
}

#: The four link slots the «Основное» screen carries (spec 4.3 «списки
#: вид/подвид/класс/подкласс»); «предыстория» belongs to «Личность» (task
#: 5.3) and stays on the old «D&D» tab until then.
MAIN_LINK_SLOTS: tuple[tuple[str, str, str], ...] = tuple(
    entry for entry in LINK_SLOTS if entry[0] != "background"
)

#: Block ids of the frame (the write channel addresses them verbatim).
LEVEL_BLOCK_ID = "level"
ABILITIES_BLOCK_ID = "abilities"
SKILLS_BLOCK_ID = "skills"
PASSIVE_BLOCK_ID = "passives"
SPEED_BLOCK_ID = "speed"
#: The editable LSS sheet id (dd-card-redesign spec dnd-character-extension
#: «адрес листа, пустой идентификатор скрывает кнопку браузера»): the old
#: «D&D» tab's QLineEdit, now a ``textline`` block committed on
#: editingFinished. Its placeholder is the old field's wording.
SHEET_BLOCK_ID = "sheet"
SHEET_PLACEHOLDER = "id цифрового листа Long Story Short"
DOORS_BLOCK_ID = "lss_doors"

_UNSET = "unset"
_TASK_FAILED = object()
_MAIN_LOGGER = "app.dd.character_main"


def link_block_id(slot: str) -> str:
    """The block id of one link combo (``link_race`` …)."""
    return f"link_{slot}"


class CharacterMainBlockController:
    """The write handler and frame builder of one character's «Основное»
    blocks (the protocol's handler duck: ``handle_write`` + ``release``).

    ``republish(blocks, hidden_fields)`` is the host's door — every state
    change re-sends the whole frame through it (the kernel merges and paints;
    the controller never touches a widget)."""

    def __init__(
        self,
        *,
        character_id: int,
        service: "DndCharacterExtensionService",
        dataset_index: "DatasetIndexService",
        record_labels: Mapping[str, str],
        run_locked: Callable[[Coroutine], asyncio.Task],
        dialog: Any,
        republish: Callable[[list, tuple], None],
        import_service: "CharacterImportService | None" = None,
        document_builder: "CharacterDocumentBuilder | None" = None,
        generation_open: "Callable[[int, str], None] | None" = None,
        generation_deps: "GenerationDeps | None" = None,
    ) -> None:
        self._character_id = character_id
        self._service = service
        self._index = dataset_index
        self._run_locked = run_locked
        self._dialog = dialog
        self._republish = republish
        self._importer = import_service
        self._document_builder = document_builder
        self._generation_open = generation_open
        self._generation_deps = generation_deps
        self._slot_labels = {
            slot: record_labels[type_key] for slot, _s, type_key in MAIN_LINK_SLOTS
        }
        self._tasks: set[asyncio.Task] = set()
        self._released = False
        # The loaded face (None until the first load lands — until then the
        # frame is only the hidden-fields answer, the kernel hides its texts
        # and paints no blocks).
        self._ext: "DdCharacterExt | None" = None
        self._mech: "CharacterMechanics | None" = None
        self._snap: Any = None
        #: option id → (dataset_id, entry_id, name) | None for «снять»;
        #: rebuilt with every frame the controller publishes.
        self._option_targets: dict[str, tuple[str, str, str] | None] = {}
        #: saved dead triples per slot (re-savable verbatim, the old tab's
        #: «источник не подключён» posture).
        self._dead_links: dict[str, tuple[str, str, str]] = {}
        # Modeless boxes stay referenced until ``finished`` (PR-010 posture).
        self._notice_box: QMessageBox | None = None
        self._confirm_box: QMessageBox | None = None
        self._start(self._load(), self._on_loaded)

    # ── task plumbing (the frames' discipline, off the QWidget) ──────────────

    def _start(self, coro: Coroutine, on_done: Callable) -> None:
        task = self._run_locked(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(on_done)

    @staticmethod
    def _outcome(task: asyncio.Task, what: str):
        if task.cancelled():
            return _TASK_FAILED
        try:
            return task.result()
        except Exception as exc:  # noqa: BLE001 — the reader sees the reason
            logging.getLogger(_MAIN_LOGGER).error(
                "D&D «Основное»: %s не удалось: %s", what, exc, exc_info=True
            )
            return _TASK_FAILED

    def release(self) -> None:
        """The host's teardown door: no callback of a released card speaks."""
        self._released = True
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    # ── the load (one locked read of everything the frame shows) ─────────────

    async def _load(self):
        return await self._read_all()

    async def _read_all(self):
        ext = await self._service.get_ext(self._character_id)
        mech = await self._service.get_mechanics(self._character_id)
        snap = await self._index.snapshot()
        return ext, mech, snap

    def _on_loaded(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "загрузка «Основного» персонажа")
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    "Не удалось загрузить D&D-поля персонажа. Подробности — в "
                    "журнале приложения; повторите, закрыв и открыв карточку."
                )
            return
        self._ext, self._mech, self._snap = outcome
        self._publish()

    def _publish(self) -> None:
        if self._released or self._ext is None:
            return
        self._republish(list(self._build_blocks()), HIDDEN_KERNEL_FIELDS)

    # ── the frame ─────────────────────────────────────────────────────────────

    def _build_blocks(self) -> tuple:
        from app.presentation.modules.protocol import (
            ModuleBlock,
            ModuleBlockCell,
            ModuleBlockOption,
            ModuleBlockRow,
        )

        ext, mech, snap = self._ext, self._mech, self._snap
        blocks: list = []
        self._option_targets = {}
        self._dead_links = {}

        for slot, section, _type_key in MAIN_LINK_SLOTS:
            options: list[ModuleBlockOption] = [
                ModuleBlockOption(_UNSET, UNSET_ITEM)
            ]
            # option id → target for THIS slot (the whole-frame map below is
            # the write address; the combo's value must name its option id).
            slot_targets: dict[str, tuple[str, str, str] | None] = {_UNSET: None}
            self._option_targets[f"{link_block_id(slot)}:{_UNSET}"] = None
            for dataset_id in snap.ids:
                title = snap.titles.get(dataset_id, dataset_id)
                for entry in snap.entries(section, dataset_id):
                    option_id = f"o{len(options)}"
                    options.append(
                        ModuleBlockOption(option_id, f"{entry.name} · {title}")
                    )
                    slot_targets[option_id] = (
                        dataset_id,
                        entry.entry_id,
                        entry.name,
                    )
                    self._option_targets[f"{link_block_id(slot)}:{option_id}"] = (
                        dataset_id,
                        entry.entry_id,
                        entry.name,
                    )
            value = _UNSET
            link = ext.links[slot]
            if link.is_set:
                wanted = (link.source_key, link.ref_id, link.snapshot_name)
                hit = next(
                    (oid for oid, target in slot_targets.items() if target == wanted),
                    None,
                )
                if hit is None:
                    # The stored triple whose source went away: appended as
                    # the annotated option, visible AND re-savable verbatim.
                    hit = "dead"
                    options.append(
                        ModuleBlockOption(
                            hit,
                            f"{link.snapshot_name} — {SOURCE_UNAVAILABLE_NOTE}",
                        )
                    )
                    self._option_targets[f"{link_block_id(slot)}:{hit}"] = wanted
                    self._dead_links[slot] = wanted
                value = hit
            blocks.append(
                ModuleBlock(
                    kind="combo",
                    id=link_block_id(slot),
                    label=self._slot_labels[slot],
                    anchor="after_short_fields",
                    value=value,
                    options=tuple(options),
                )
            )

        level_options = [ModuleBlockOption("", UNSET_ITEM)] + [
            ModuleBlockOption(str(value), str(value))
            for value in range(1, LEVEL_MAX + 1)
        ]
        blocks.append(
            ModuleBlock(
                kind="combo",
                id=LEVEL_BLOCK_ID,
                label="Уровень",
                anchor="after_short_fields",
                value="" if ext.level is None else str(ext.level),
                options=tuple(level_options),
            )
        )

        scores = mech.scores
        bonus = proficiency_bonus(ext.level)
        class_saves = class_record_saving_throws(ext, snap)
        saves = frozenset(
            class_saves if class_saves else mech.manual_saving_throws
        )
        ability_rows = []
        for ability in ABILITY_KEYS:
            label = ABILITY_LABELS[ability]
            if scores is None:
                value_text = check_text = save_text = ""
            else:
                score = scores[ability]
                value_text = str(score)
                check_text = f"{check_value(score):+d}"
                save_text = (
                    f"{saving_throw_value(score, bonus, ability in saves):+d}"
                )
            ability_rows.append(
                ModuleBlockRow(
                    id=ability,
                    cells=(
                        ModuleBlockCell(field="name", kind="text", label=label),
                        ModuleBlockCell(
                            field="score",
                            kind="number",
                            label=label,
                            value=value_text,
                            min_value=ABILITY_MIN,
                            max_value=ABILITY_MAX,
                        ),
                        ModuleBlockCell(field="check", kind="text", value=check_text),
                        ModuleBlockCell(field="save", kind="text", value=save_text),
                        ModuleBlockCell(
                            field="save",
                            kind="switch",
                            name=f"Владение спасброском: {label}",
                            checked=ability in saves,
                            enabled=class_saves is None,
                        ),
                    ),
                )
            )
        blocks.append(
            ModuleBlock(
                kind="table",
                id=ABILITIES_BLOCK_ID,
                label="Характеристики",
                anchor="after_short_fields",
                columns=("Характеристика", "Значение", "Проверка", "Спасбросок",
                         "Владение"),
                rows=tuple(ability_rows),
            )
        )

        skill_rows = []
        for skill, ability in SKILL_ABILITIES.items():
            skill_label = SKILL_LABELS[skill]
            if scores is None:
                value_text = ""
            else:
                value_text = (
                    f"{skill_value(scores[ability], bonus, skill in mech.skill_proficiencies):+d}"
                )
            skill_rows.append(
                ModuleBlockRow(
                    id=skill,
                    cells=(
                        ModuleBlockCell(
                            field="name", kind="text", label=skill_label
                        ),
                        ModuleBlockCell(
                            field="ability", kind="text",
                            value=ABILITY_LABELS[ability],
                        ),
                        ModuleBlockCell(field="value", kind="text", value=value_text),
                        ModuleBlockCell(
                            field="prof",
                            kind="switch",
                            name=f"Владение навыком: {skill_label}",
                            checked=skill in mech.skill_proficiencies,
                        ),
                    ),
                )
            )
        blocks.append(
            ModuleBlock(
                kind="table",
                id=SKILLS_BLOCK_ID,
                label="Навыки",
                anchor="after_short_fields",
                columns=("Навык", "Характеристика", "Значение", "Владение"),
                rows=tuple(skill_rows),
            )
        )

        if scores is None:
            passive_text = UNSET_ITEM
        else:
            passive_text = " · ".join(
                f"{SKILL_LABELS[skill]} "
                f"{passive_sense_value(scores[SKILL_ABILITIES[skill]], bonus, skill in mech.skill_proficiencies)}"
                for skill in PASSIVE_SENSE_SKILLS
            )
        blocks.append(
            ModuleBlock(
                kind="text",
                id=PASSIVE_BLOCK_ID,
                label="Пассивные чувства",
                anchor="after_short_fields",
                value=passive_text,
            )
        )

        if scores is None:
            derived = ""
            jumps = None
        else:
            jumps = jumps_and_carry(scores["strength"])
            derived = f"{jumps.carry_limit_pounds} фн"
        blocks.append(
            ModuleBlock(
                kind="text",
                id="carry",
                label="Переносимый максимум",
                anchor="after_short_fields",
                value=derived,
            )
        )
        blocks.append(
            ModuleBlock(
                kind="text",
                id="jumps",
                label="Прыжки",
                anchor="after_short_fields",
                value=(
                    ""
                    if jumps is None
                    else f"с разбега {jumps.long_jump_feet} фт · "
                    f"с места {jumps.standing_long_jump_feet} фт · "
                    f"в высоту {jumps.high_jump_feet} фт"
                ),
            )
        )
        blocks.append(
            ModuleBlock(
                kind="number",
                id=SPEED_BLOCK_ID,
                label="Скорость (фт)",
                anchor="after_short_fields",
                value="" if mech.speed is None else str(mech.speed),
                min_value=0,
                max_value=999,
            )
        )

        sheet_id = (ext.lss_sheet_id or "").strip()
        blocks.append(
            ModuleBlock(
                kind="textline",
                id=SHEET_BLOCK_ID,
                label="Лист LSS",
                anchor="after_music",
                value=sheet_id,
                placeholder=SHEET_PLACEHOLDER,
            )
        )

        actions: list[ModuleBlockOption] = []
        if sheet_id:
            # «Открыть в браузере» rides the door row and shows only while
            # the stored id says one (spec: the empty identifier hides the
            # button — here the button is simply absent from the frame until
            # a committed id republishes it in).
            actions.append(ModuleBlockOption("open", OPEN_IN_BROWSER_TEXT))
        if self._importer is not None:
            actions.append(ModuleBlockOption("overwrite", IMPORT_OVERWRITE_TEXT))
            actions.append(ModuleBlockOption("save_raw", SAVE_RAW_TEXT))
        if self._document_builder is not None:
            actions.append(ModuleBlockOption("export", EXPORT_FOR_LSS_TEXT))
        if (
            self._generation_open is not None
            and self._document_builder is not None
        ):
            available = (
                self._generation_deps is None
                or bool(self._generation_deps.available())
            )
            actions.append(
                ModuleBlockOption("top_up", TOP_UP_AI_TEXT, enabled=available)
            )
        if actions:
            # The no-dead-action posture: without a composed door the row
            # prints nothing at all, not a button that cannot act. The row
            # is captioned «Файл LSS» only while file doors ride it; a lone
            # browser button stands captionless under the sheet line (the
            # old tab's field-and-button row, one block channel lower).
            file_doors = any(action.id != "open" for action in actions)
            blocks.append(
                ModuleBlock(
                    kind="buttons",
                    id=DOORS_BLOCK_ID,
                    label="Файл LSS" if file_doors else "",
                    anchor="after_music",
                    actions=tuple(actions),
                )
            )
        return tuple(blocks)

    # ── the write channel ────────────────────────────────────────────────────

    def handle_write(self, block_id: str, field: str, value: object) -> None:
        if self._released or self._ext is None:
            return
        if block_id.startswith("link_") and field == "value":
            self._write_link(block_id, str(value))
        elif block_id == LEVEL_BLOCK_ID:
            self._write_level(str(value))
        elif block_id == ABILITIES_BLOCK_ID:
            ability, _, cell = field.partition(".")
            if cell == "score":
                self._write_score(ability, value)
            elif cell == "save":
                self._write_save_prof(ability)
        elif block_id == SKILLS_BLOCK_ID and field.endswith(".prof"):
            self._write_skill_prof(field[: -len(".prof")])
        elif block_id == SPEED_BLOCK_ID:
            self._write_speed(value)
        elif block_id == SHEET_BLOCK_ID:
            self._write_sheet_id(str(value))
        elif block_id == DOORS_BLOCK_ID:
            self._write_door(str(field))

    def _write(self, action: Coroutine, what: str) -> None:
        """One locked operation: the service write plus the re-read of the
        whole face in the SAME coroutine (a second ``run_locked`` from a
        locked task would deadlock), republished from the fresh read."""

        async def operation():
            await action
            return await self._read_all()

        def done(task: asyncio.Task) -> None:
            outcome = self._outcome(task, f"сохранение поля «{what}»")
            if outcome is _TASK_FAILED:
                if not task.cancelled():
                    self._show_notice(
                        f"Не удалось сохранить поле «{what}». Значение в поле "
                        "осталось, повторите изменение; подробности — в "
                        "журнале приложения."
                    )
                return
            self._ext, self._mech, self._snap = outcome
            self._publish()

        self._start(operation(), done)

    def _write_link(self, block_id: str, option_id: str) -> None:
        slot = block_id[len("link_"):]
        target = self._option_targets.get(f"{block_id}:{option_id}")
        link = (
            ReferenceLink(*target)
            if target is not None
            else ReferenceLink("", "", "")
        )
        self._write(
            self._service.set_reference_link(self._character_id, slot, link),
            self._slot_labels.get(slot, slot),
        )

    def _write_level(self, text: str) -> None:
        level = None if text == "" else int(text)
        self._write(
            self._service.set_level(self._character_id, level), "уровень"
        )

    def _write_score(self, ability: str, raw: object) -> None:
        if ability not in ABILITY_KEYS:
            return
        scores = dict(self._mech.scores or {})
        text = str(raw).strip()
        if text == "":
            scores.pop(ability, None)
        else:
            try:
                scores[ability] = int(text)
            except ValueError:
                self._show_notice(
                    "Значение характеристики — целое число (или пусто)."
                )
                return
        try:
            # The all-or-nothing gate answers BEFORE any transaction (the
            # spec's partial set is a refusal, not a half-write).
            validate_ability_scores(scores)
        except ValueError as exc:
            self._show_notice(f"Характеристики приняты не будут: {exc}.")
            return
        self._write(
            self._service.set_ability_scores(self._character_id, scores or None),
            "характеристики",
        )

    def _write_save_prof(self, ability: str) -> None:
        if ability not in ABILITY_KEYS:
            return
        if class_record_saving_throws(self._ext, self._snap):
            # The class owns the saves (design Д8); the painted switch is
            # disabled too, so this is the belt on the QML gate.
            return
        current = set(self._mech.manual_saving_throws)
        if ability in current:
            current.discard(ability)
        else:
            current.add(ability)
        self._write(
            self._service.set_saving_throw_proficiencies(
                self._character_id, current
            ),
            "владение спасброском",
        )

    def _write_skill_prof(self, skill: str) -> None:
        if skill not in SKILL_ABILITIES:
            return
        current = set(self._mech.skill_proficiencies)
        if skill in current:
            current.discard(skill)
        else:
            current.add(skill)
        self._write(
            self._service.set_skill_proficiencies(self._character_id, current),
            "владение навыком",
        )

    def _write_speed(self, raw: object) -> None:
        text = str(raw).strip()
        if text == "":
            speed = None
        else:
            try:
                speed = int(text)
            except ValueError:
                self._show_notice("Скорость — целое число футов (или пусто).")
                return
        self._write(
            self._service.set_speed(self._character_id, speed), "скорость"
        )

    def _write_sheet_id(self, raw: str) -> None:
        """The committed sheet id (editingFinished, never per keystroke).
        An untouched field losing focus is no transaction (the old tab's
        discipline); a commit re-publishes the frame, and the painted door
        row gains or loses «Открыть в браузере» with the stored value."""
        sheet_id = raw.strip()
        if sheet_id == (self._ext.lss_sheet_id or "").strip():
            return
        self._write(
            self._service.set_lss_sheet_id(self._character_id, sheet_id),
            "идентификатор листа LSS",
        )

    # ── the LSS file doors + «Дозаполнить ИИ» (the old tab's flows) ──────────

    def _write_door(self, action: str) -> None:
        if action == "open":
            self._door_open_browser()
        elif action == "overwrite":
            self._door_overwrite()
        elif action == "save_raw":
            self._door_save_raw()
        elif action == "export":
            self._door_export()
        elif action == "top_up":
            self._door_top_up()

    def _door_open_browser(self) -> None:
        """«Открыть в браузере»: the digital sheet page of the stored id,
        the old tab's button verbatim (the system browser is the door, no
        embedded web view — the roadmap ruling). The button only paints with
        a stored id, so the address here always carries one."""
        QDesktopServices.openUrl(
            QUrl(lss_sheet_url(self._ext.lss_sheet_id))
        )

    def _door_overwrite(self) -> None:
        """«Перезаписать из файла LSS…» — pick, pre-check, confirm, re-send
        the very bytes (the old tab's discipline, restated for the block)."""
        if self._importer is None:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self._dialog,
            IMPORT_OVERWRITE_TEXT,
            "",
            CHARACTER_FILE_FILTER,
            # L1 (NRI-0014): always the Russian Qt panel, never the native one.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._show_notice(f"Не удалось прочитать файл «{path}»: {exc}")
            return

        def precheck(task: asyncio.Task) -> None:
            outcome = self._outcome(task, "предпроверка импорта персонажа")
            if outcome is _TASK_FAILED:
                if not task.cancelled():
                    self._show_notice(
                        "Не удалось проверить файл персонажа. Подробности — в "
                        "журнале приложения; повторите выбор файла."
                    )
                return
            if outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION:
                box = QMessageBox(self._dialog)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle(IMPORT_OVERWRITE_TEXT)
                box.setText(outcome.message)
                box.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                box.setDefaultButton(QMessageBox.StandardButton.No)
                self._confirm_box = box
                box.finished.connect(
                    lambda result, _bytes=content: self._confirm_answered(
                        result, _bytes
                    )
                )
                box.show()
                return
            self._report_import_outcome(outcome)

        self._start(
            self._importer.import_character(content, character_id=self._character_id),
            precheck,
        )

    def _confirm_answered(self, result: int, content: str) -> None:
        self._confirm_box = None
        if result != QMessageBox.StandardButton.Yes:
            return
        self._start(
            self._importer.import_character(
                content, character_id=self._character_id, confirmed=True
            ),
            self._on_import_done,
        )

    def _on_import_done(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "импорт персонажа из файла LSS")
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    "Импорт персонажа не завершился. Подробности — в журнале "
                    "приложения; поля карточки остались как были."
                )
            return
        self._report_import_outcome(outcome)

    def _report_import_outcome(self, outcome: "CharacterImportOutcome") -> None:
        from app.dd.presentation.datasets_sheet import report_lines

        if outcome.status is CharacterImportStatus.BLOCKED:
            lines = (
                "\n".join(report_lines(outcome.report))
                if outcome.report is not None
                else ""
            )
            body = f"Импорт отклонён — отчёт проверки:\n{lines}" if lines else outcome.message
            self._show_notice(body)
            return
        if outcome.status is CharacterImportStatus.NEEDS_CONFIRMATION:
            self._show_notice(outcome.message)
            return
        body = outcome.message
        warnings = outcome.report.warnings if outcome.report is not None else ()
        if warnings:
            body += "\nПредупреждения:\n" + "\n".join(
                f"{issue.path} — {issue.message}" for issue in warnings
            )
        self._show_notice(body, QMessageBox.Icon.Information)
        # The stored face changed wholesale (fields, level, mechanics) — the
        # frame reloads through the lock and republishes.
        self._start(self._load(), self._on_loaded)

    def _door_save_raw(self) -> None:
        if self._importer is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self._dialog,
            SAVE_RAW_TEXT,
            "character.json",
            CHARACTER_FILE_FILTER,
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return

        def done(task: asyncio.Task) -> None:
            outcome = self._outcome(task, "сохранение исходного файла персонажа")
            if outcome is _TASK_FAILED:
                if not task.cancelled():
                    self._show_notice(
                        "Не удалось записать файл на диск. Подробности — в "
                        "журнале приложения; повторите выбор места сохранения."
                    )
                return
            if outcome is False:
                self._show_notice(
                    "Для этого персонажа ещё не импортирован файл LSS — "
                    "сохранять нечего; импортируйте файл через «Перезаписать "
                    "из файла LSS…»."
                )
                return
            self._show_notice(
                "Исходный файл сохранён на диск байт-в-байт, как он был "
                "импортирован.",
                QMessageBox.Icon.Information,
            )

        self._start(
            self._importer.save_raw_document(self._character_id, path), done
        )

    def _door_export(self) -> None:
        if self._document_builder is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self._dialog,
            EXPORT_FOR_LSS_TEXT,
            "character.json",
            CHARACTER_FILE_FILTER,
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return

        def done(task: asyncio.Task) -> None:
            outcome = self._outcome(task, "экспорт персонажа для LSS")
            if outcome is _TASK_FAILED:
                if not task.cancelled():
                    self._show_notice(
                        "Не удалось собрать и записать файл для LSS. Карточка "
                        "и сохранённый файл персонажа не изменены; подробности "
                        "— в журнале приложения; повторите выбор места "
                        "сохранения."
                    )
                return
            self._show_notice(
                "Файл для LSS записан: документ собран из текущего состояния "
                "карточки, а не из сохранённого исходного файла.",
                QMessageBox.Icon.Information,
            )

        self._start(
            self._document_builder.export_document(self._character_id, path), done
        )

    def _door_top_up(self) -> None:
        """«Дозаполнить ИИ»: the current document is assembled (the
        builder's door), the empty refusal stays honest, the generation task
        sheet opens through the façade's opener."""
        if self._generation_open is None or self._document_builder is None:
            return
        if self._generation_deps is not None and not self._generation_deps.available():
            return

        def done(task: asyncio.Task) -> None:
            outcome = self._outcome(task, "сборка документа для дозаполнения ИИ")
            if outcome is _TASK_FAILED:
                if not task.cancelled():
                    self._show_notice(
                        "Не удалось собрать документ персонажа для "
                        "дозаполнения. Карточка не изменена; подробности — в "
                        "журнале приложения."
                    )
                return
            document = str(outcome)
            if not top_up_missing_fields(document):
                self._show_notice(
                    TOP_UP_NOTHING_REFUSAL, QMessageBox.Icon.Information
                )
                return
            self._generation_open(self._character_id, document)

        self._start(
            self._document_builder.build(self._character_id), done
        )

    # ── the modeless notice (the module's standing failure box) ──────────────

    def _show_notice(
        self, body: str, icon: QMessageBox.Icon = QMessageBox.Icon.Warning
    ) -> None:
        if self._released:
            return
        box = QMessageBox(self._dialog)
        box.setIcon(icon)
        box.setWindowTitle("D&D-модуль")
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._notice_box = box
        box.finished.connect(self._notice_finished)
        box.show()

    def _notice_finished(self, _result: int) -> None:
        self._notice_box = None
