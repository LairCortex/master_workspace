"""The monster card — creation and editing (add-dnd-game-face task 10.1;
spec dnd-bestiary «Создание и правка — карточкой с табами»).

The module's own editable sheet for the game's own entity: the dataset
records stay read-only everywhere (their file is the truth), the monster is
hand-written — so this card has what the generic preview deliberately lacks:
input fields, tabs, a save. Deletion does not exist (the product has no
removal path; the spec names no «Удалить» and there is none).

Tabs (spec «карточкой с табами», the tabbing the kernel cards set): «Обзор»
carries the identity fields — name, the 1…20 rating the spinbox prints, and
the picture (kernel store: pick from disk, replace, remove); «Тексты» carries
the named text blocks in the order they were added — mechanics included,
they are text by design (spec «Механика — текстом»).

Window class: the sheet contract — the attached native sheet on the
connector's stack, :class:`SheetFrame` chrome (windowTitle = the header
caption: «Новый монстр» until the first save, the name afterwards), fixed
default size, the tab content scrolling beyond it. Cancel is the header's
«Закрыть»/Esc (a QDialog reject — no half-typed save); the save button is
the only write door and its refusal (empty name, rating out of range, a file
that is not an image, the monster gone) prints Russian in the notice line,
never a nested box over a live sheet.

Async posture: reads and the save ride the connector's session lock through
the injected ``run_locked`` (the datasets sheet's discipline — one
coroutine does the write and the reload-visible-after part, no second locked
task from inside a locked one); the in-flight tasks are held as live refs and
cancelled in :meth:`done` (PR-037: a released widget answers nothing —
after an await the code checks liveness before touching fields).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Coroutine

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
import shiboken6

from app.dd.application.monster_service import MONSTER_GONE_REFUSAL
from app.dd.domain.monster import RATING_MAX, RATING_MIN
from app.domain.allowed_image_extensions import ALLOWED_IMAGE_EXTENSIONS
from app.presentation.views.sheet_frame import SheetFrame

if TYPE_CHECKING:
    from app.dd.application.monster_service import DdMonsterService

#: Titles of the two card tabs.
DD_MONSTER_TAB_OVERVIEW = "Обзор"
DD_MONSTER_TAB_TEXTS = "Тексты"
#: The creation window's title; an opened monster is titled by its name.
DD_MONSTER_CARD_NEW_TITLE = "Новый монстр"
#: The save line of the notice (the write succeeded — kept short, the
#: notice slot doubles as the refusal slot).
DD_MONSTER_SAVED_TEXT = "Сохранено."
#: Field captions (QFormLayout labels — the штатный naming of the fields).
DD_MONSTER_NAME_LABEL = "Имя"
DD_MONSTER_RATING_LABEL = "Рейтинг"
#: Picture actions.
DD_MONSTER_IMAGE_PICK_TEXT = "Выбрать изображение…"
DD_MONSTER_IMAGE_REMOVE_TEXT = "Убрать изображение"
#: Block row action and the block-add entry.
DD_MONSTER_BLOCK_REMOVE_TEXT = "Удалить блок"
DD_MONSTER_BLOCK_ADD_TEXT = "Добавить блок"
DD_MONSTER_BLOCK_TITLE_PLACEHOLDER = "Заголовок блока…"
#: The file-dialog caption and filter — the same six extensions as every
#: other image pick in the app (domain whitelist, audit A5).
DD_MONSTER_IMAGE_DIALOG_TITLE = "Выберите изображение"
DD_MONSTER_IMAGE_FILTER = "Изображения (*" + " *".join(e.lstrip(".") for e in ALLOWED_IMAGE_EXTENSIONS) + ")"
#: The Russian sentence for a file the decoder rejected — the store raises
#: with its own reason, this is the line printed above the fields when the
#: chosen bytes never decode (the pick validates early so the master sees
#: it BEFORE pressing «Сохранить»).
DD_MONSTER_IMAGE_UNDECODABLE = "выбранный файл не является изображением"


class _BlockRow:
    """One named block while the card is open: title field, text field, the
        row's own removal. Plain widgets only — every control is named by
        its caption, its buddy label or its accessibleName (task 12.1: a
        placeholder paints but never names)."""

    def __init__(self, host: QWidget, layout: QVBoxLayout, on_remove) -> None:
        self.row = QWidget(host)
        row_layout = QVBoxLayout(self.row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(2)
        line = QHBoxLayout()
        self.title = QLineEdit(self.row)
        self.title.setObjectName("ddMonsterBlockTitle")
        self.title.setPlaceholderText(DD_MONSTER_BLOCK_TITLE_PLACEHOLDER)
        # The placeholder paints, it does not name (task 12.1): the row
        # carries no buddy, so the caption rides the accessibleName slot.
        self.title.setAccessibleName("Заголовок блока")
        line.addWidget(self.title, 1)
        remove = QPushButton(DD_MONSTER_BLOCK_REMOVE_TEXT, self.row)
        remove.setObjectName("ddMonsterBlockRemove")
        remove.clicked.connect(lambda: on_remove(self))
        line.addWidget(remove)
        row_layout.addLayout(line)
        self.text = QPlainTextEdit(self.row)
        self.text.setObjectName("ddMonsterBlockText")
        self.text.setAccessibleName("Текст блока")
        # Three visible lines: block bodies (mechanics prose) are written
        # here, a one-liner field would hide what was typed.
        self.text.setFixedHeight(72)
        self.text.setPlaceholderText("Текст блока…")
        row_layout.addWidget(self.text)
        layout.insertWidget(layout.count() - 1, self.row)
        layout.setStretch(layout.count() - 1, 0)

    def remove(self, layout: QVBoxLayout) -> None:
        layout.removeWidget(self.row)
        self.row.setParent(None)
        self.row.deleteLater()


class DndMonsterCardSheet(SheetFrame):
    """The create/edit card of one monster (module docstring)."""

    def __init__(
        self,
        monster_id: int | None,
        service: "DdMonsterService",
        run_locked: Callable[[Coroutine], asyncio.Task],
        on_saved: Callable[["DndMonsterCardSheet"], None],
        source: object | None = None,
        parent: QWidget | None = None,
        theme: object | None = None,
    ) -> None:
        super().__init__(
            DD_MONSTER_CARD_NEW_TITLE if monster_id is None else "Монстр",
            parent,
            theme,
        )
        self._monster_id = monster_id
        self._service = service
        self._run_locked = run_locked
        self._on_saved = on_saved
        # The showcase source (duck door ``warm``): the cache behind search,
        # mentions and the preview column is reconciled right after a save,
        # so the surfaces show the new values without waiting for the next
        # search's refresh. Optional by composition like everything here.
        self._source = source
        # Picture state while the card is open: fresh bytes to ingest, or
        # the pending «убрать» — both applied by the service's save.
        self._pending_image: bytes | None = None
        self._clear_image = False
        # The live block rows in on-screen order — the collection reads THIS
        # list (a findChildren scan would need a name-filter branch no honest
        # state ever takes: the list holds nothing but block rows).
        self._block_rows: list[_BlockRow] = []
        self._load_task: asyncio.Task | None = None
        self._save_task: asyncio.Task | None = None

        self.setMinimumSize(560, 480)

        body = QWidget(self)
        body.setObjectName("ddMonsterCardBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        tabs = QTabWidget(body)
        tabs.setObjectName("ddMonsterTabs")

        # ── «Обзор» — the identity fields ───────────────────────────────────
        overview = QWidget(tabs)
        overview.setObjectName("ddMonsterOverview")
        overview_layout = QVBoxLayout(overview)
        form_host = QScrollArea(overview)
        form_host.setObjectName("ddMonsterOverviewScroll")
        form_host.setWidgetResizable(True)
        form_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form = QWidget(form_host)
        form_layout = QFormLayout(form)
        self._name = QLineEdit(form)
        self._name.setObjectName("ddMonsterName")
        form_layout.addRow(DD_MONSTER_NAME_LABEL, self._name)
        self._rating = QSpinBox(form)
        self._rating.setObjectName("ddMonsterRating")
        self._rating.setRange(RATING_MIN, RATING_MAX)
        form_layout.addRow(DD_MONSTER_RATING_LABEL, self._rating)
        # Picture row: the thumbnail (or its absence) beside the two actions.
        picture_row = QHBoxLayout()
        self._thumb = QLabel(form)
        self._thumb.setObjectName("ddMonsterThumb")
        self._thumb.setFixedSize(96, 72)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setText("Нет изображения")
        picture_row.addWidget(self._thumb)
        picture_actions = QVBoxLayout()
        self._image_pick = QPushButton(DD_MONSTER_IMAGE_PICK_TEXT, form)
        self._image_pick.setObjectName("ddMonsterImagePick")
        self._image_pick.clicked.connect(self._on_pick_image)
        picture_actions.addWidget(self._image_pick)
        self._image_remove = QPushButton(DD_MONSTER_IMAGE_REMOVE_TEXT, form)
        self._image_remove.setObjectName("ddMonsterImageRemove")
        self._image_remove.clicked.connect(self._on_remove_image)
        picture_actions.addWidget(self._image_remove)
        picture_actions.addStretch(1)
        picture_row.addLayout(picture_actions)
        picture_row.addStretch(1)
        form_layout.addRow(picture_row)
        form_host.setWidget(form)
        overview_layout.addWidget(form_host, 1)
        tabs.addTab(overview, DD_MONSTER_TAB_OVERVIEW)

        # ── «Тексты» — the named blocks ─────────────────────────────────────
        texts = QWidget(tabs)
        texts.setObjectName("ddMonsterTexts")
        texts_layout = QVBoxLayout(texts)
        blocks_host = QScrollArea(texts)
        blocks_host.setObjectName("ddMonsterBlocksScroll")
        blocks_host.setWidgetResizable(True)
        blocks_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._blocks_list = QWidget(blocks_host)
        self._blocks_list.setObjectName("ddMonsterBlocksList")
        self._blocks_layout = QVBoxLayout(self._blocks_list)
        self._blocks_layout.setContentsMargins(0, 0, 8, 0)
        self._blocks_layout.setSpacing(6)
        self._blocks_layout.addStretch(1)
        blocks_host.setWidget(self._blocks_list)
        texts_layout.addWidget(blocks_host, 1)
        self._block_add = QPushButton(DD_MONSTER_BLOCK_ADD_TEXT, texts)
        self._block_add.setObjectName("ddMonsterBlockAdd")
        self._block_add.clicked.connect(lambda: self._add_block_row("", ""))
        add_row = QHBoxLayout()
        add_row.addWidget(self._block_add)
        add_row.addStretch(1)
        texts_layout.addLayout(add_row)
        tabs.addTab(texts, DD_MONSTER_TAB_TEXTS)

        layout.addWidget(tabs, 1)

        # ── footer: notice + the two actions ────────────────────────────────
        footer = QHBoxLayout()
        self._notice = QLabel("", body)
        self._notice.setObjectName("ddMonsterNotice")
        self._notice.setWordWrap(True)
        self._notice.hide()
        footer.addWidget(self._notice, 1)
        footer.addStretch(1)
        cancel = QPushButton("Отмена", body)
        cancel.setObjectName("ddMonsterCancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self._save_button = QPushButton("Сохранить", body)
        self._save_button.setObjectName("ddMonsterSave")
        self._save_button.clicked.connect(self._on_save_clicked)
        footer.addWidget(self._save_button)
        layout.addLayout(footer)

        self.add_content(body, 1)
        if monster_id is not None:
            self._start_load()

    @property
    def monster_id(self) -> int | None:
        """The row this card writes: ``None`` until a creation card has
        saved once (the façade re-keys its live ref from this door)."""
        return self._monster_id

    # ── loading ───────────────────────────────────────────────────────────────

    def _start_load(self) -> None:
        """Read the monster and its preview picture through the locked door;
        the row gone under an open card prints the refusal and bars the save
        (recreating a vanished monster under a new id would be a different
        operation than the edit the card was opened for)."""

        async def _load() -> None:
            monster = await self._service.get_monster(self._monster_id)
            if monster is None:
                self._set_notice(MONSTER_GONE_REFUSAL)
                self._save_button.setEnabled(False)
                return
            preview = (
                await self._service.image_preview_path(monster.image_id)
                if monster.image_id is not None
                else None
            )
            if not shiboken6.isValid(self):  # closed while the door was open
                return
            self.setWindowTitle(monster.name)
            self._name.setText(monster.name)
            self._rating.setValue(monster.rating)
            for title, text in monster.blocks.items():
                self._add_block_row(title, text)
            if preview is not None:
                self._show_thumb_path(preview)

        self._load_task = self._run_locked(_load())

    # ── picture ───────────────────────────────────────────────────────────────

    def _on_pick_image(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            DD_MONSTER_IMAGE_DIALOG_TITLE,
            "",
            DD_MONSTER_IMAGE_FILTER,
            # L1 (NRI-0014): always the Russian Qt panel, never the native one.
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return  # the отвод is a no-op
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            self._set_notice(f"не удалось прочитать файл: {exc}")
            return
        probe = QPixmap()
        if not probe.loadFromData(data) or probe.isNull():
            # Decode-checked at pick time (the entity card's posture and its
            # idiom — loadFromData: PySide6 binds QPixmap(bytes) to the FILE
            # name overload, a bytes ctor would reject every valid pick):
            # the master learns about a non-image before the save, not after
            # the whole transaction. The service still validates on its own door.
            self._set_notice(DD_MONSTER_IMAGE_UNDECODABLE)
            return
        self._pending_image = data
        self._clear_image = False
        self._show_thumb_bytes(data)
        self._set_notice("")

    def _on_remove_image(self) -> None:
        """The pending «убрать»: applied by the save (the picture leaves the
        row only through the one transaction, together with the fields)."""
        self._pending_image = None
        self._clear_image = True
        self._thumb.setPixmap(QPixmap())
        self._thumb.setText("Нет изображения")
        self._set_notice("")

    def _show_thumb_path(self, path: Path) -> None:
        self._show_thumb(QPixmap(str(path)))

    def _show_thumb_bytes(self, data: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self._show_thumb(pixmap)

    def _show_thumb(self, pixmap: QPixmap) -> None:
        """One thumb painter for both sources (stored preview, picked bytes):
        a picture scaled into the fixed slot, its absence honest placeholder
        text — never a broken frame."""
        if pixmap.isNull():
            self._thumb.setText("Нет изображения")
            return
        self._thumb.setText("")
        self._thumb.setPixmap(
            pixmap.scaled(
                self._thumb.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # ── blocks ────────────────────────────────────────────────────────────────

    def _add_block_row(self, title: str, text: str) -> _BlockRow:
        row = _BlockRow(self._blocks_list, self._blocks_layout, self._remove_block_row)
        row.title.setText(title)
        row.text.setPlainText(text)
        self._block_rows.append(row)
        return row

    def _remove_block_row(self, row: _BlockRow) -> None:
        self._block_rows.remove(row)
        row.remove(self._blocks_layout)

    def _collect_blocks(self) -> dict[str, str]:
        """Row order, empty titles skipped (the domain's normalize_blocks
        repeats the rule — one knowledge, two honest floors)."""
        collected: dict[str, str] = {}
        for row in self._block_rows:
            title = row.title.text().strip()
            if not title:
                continue
            collected[title] = row.text.toPlainText()
        return collected

    # ── save ──────────────────────────────────────────────────────────────────

    def _on_save_clicked(self) -> None:
        """One write door. A save already in flight answers itself — no
        second race (the sheet's loaders are single in flight everywhere)."""
        if self._save_task is not None and not self._save_task.done():
            return
        self._save_task = self._run_locked(self._save())

    async def _save(self) -> None:
        """The whole save flow lives inside one locked coroutine (the tab
        frames' discipline: a second ``run_locked`` from inside a locked task
        would deadlock the lock). The service's refusals — empty name,
        rating out of the spin's band a foreign writer produced, the gone
        monster, the store rejecting bytes that are not an image — print
        Russian in the notice; the sheet stays open with the master's text
        intact (a lost draft is the bug this line exists to prevent)."""
        try:
            monster = await self._service.save_monster(
                monster_id=self._monster_id,
                name=self._name.text(),
                rating=self._rating.value(),
                blocks=self._collect_blocks(),
                image_data=self._pending_image,
                clear_image=self._clear_image,
            )
        except ValueError as exc:
            if not shiboken6.isValid(self):
                return
            self._set_notice(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — persistence never goes silent
            logging.getLogger("app.dd.monster_card").error(
                "monster save failed: %s", exc, exc_info=True
            )
            if not shiboken6.isValid(self):
                return
            self._set_notice(
                f"не удалось сохранить монстра: {exc}"
            )
            return
        if self._source is not None:
            warm = getattr(self._source, "warm", None)
            if callable(warm):
                await warm()
        if not shiboken6.isValid(self):
            return
        self._monster_id = monster.id
        self._pending_image = None
        self._clear_image = False
        self.setWindowTitle(monster.name)
        self._name.setText(monster.name)
        self._rating.setValue(monster.rating)
        self._reload_blocks_from(monster)
        if monster.image_id is not None:
            # Re-aim the thumb at the STORED preview (the picked bytes' own
            # decoded render and the store's preview can differ; the stored
            # file is what every other surface will show).
            preview = await self._service.image_preview_path(monster.image_id)
            if shiboken6.isValid(self) and preview is not None:
                self._show_thumb_path(preview)
        self._set_notice(DD_MONSTER_SAVED_TEXT)
        self._on_saved(self)

    def _reload_blocks_from(self, monster) -> None:
        """Rebuild the block rows from the saved value: the normalize pass
        dropped the titleless rows and folded same-title rows, so the rows on
        screen become exactly the stored dictionary (the same re-render the
        text would need after any server-side rule)."""
        for row in self._block_rows:
            row.remove(self._blocks_layout)
        self._block_rows.clear()
        for title, text in monster.blocks.items():
            self._add_block_row(title, text)

    # ── notice ────────────────────────────────────────────────────────────────

    def _set_notice(self, text: str) -> None:
        """The single result line above the buttons (refusal or «Сохранено.»)
        — modeless by construction, no box over a live sheet, PR-010."""
        self._notice.setText(text)
        self._notice.setVisible(bool(text))

    # ── teardown ──────────────────────────────────────────────────────────────

    def done(self, result: int) -> None:
        # A closed card answers nothing: both in-flight tasks die with it
        # (the PR-037 posture — a live ref would keep waking a dead widget).
        for task in (self._load_task, self._save_task):
            if task is not None and not task.done():
                task.cancel()
        self._load_task = None
        self._save_task = None
        super().done(result)
