"""The «Способности» tab of a character card (dd-card-redesign task 5.2;
spec dnd-character-mechanics «Черты — ссылки на записи датасетов»).

A feat choice is the spell binding's form copied to the feat: the pair
«source + id» plus the name snapshot, a REFERENCE into a connected dataset's
record of type «черта», never a text copy (and never merged into the free
«Черты характера» text of «Личность» — the spec names the two apart).

The frame is the module tab posture established by «Заклинания»: a native
widget floated over the QML body, штатные controls carrying their captions
as ``accessibleName``, ``ddFeats*`` object names for the offscreen tests,
every write one locked operation (write + re-read in ONE coroutine — a
second ``run_locked`` from a locked task would deadlock), failures a
modeless Russian box, a released tab answering nothing.

The candidate wall reads the ``feats`` section of the connected datasets.
A chosen feat whose source went away (or whose record vanished) keeps its
stored snapshot and prints the дословная mark «источник не подключён» in
place of the origin (spec scenario «Датасет сняли — имена целы»); choosing
from a wall that no dataset feeds is honestly impossible, and the empty
hint says so.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# The dataset section feats are chosen from (one of the protocol's six) — the
# domain's constant (dd-card-redesign task 6.1: the importer resolves feat
# references through the same section, one knowledge, one place).
from app.dd.domain.character import DdFeatLink, FEATS_SECTION
from app.dd.presentation.captions import button_caption
from app.dd.presentation.character_tab_frames import (
    SOURCE_UNAVAILABLE_NOTE,
    UNSAVED_CHARACTER_REFUSAL,
    _LockedFrame,
    _TASK_FAILED,
)

if TYPE_CHECKING:
    from app.dd.application.dataset_index_service import (
        DatasetIndexService,
        IndexSnapshot,
    )
    from app.dd.application.dnd_character_extension_service import (
        DndCharacterExtensionService,
    )


@dataclass(frozen=True)
class _FeatCandidate:
    """One feat the tab can choose right now: the pair it will store, the
    name it will snapshot, the dataset title it prints."""

    source_key: str
    ref_id: str
    name: str
    origin: str


class DndFeatsTabFrame(_LockedFrame):
    """Chosen feats with removal, a filterable candidate wall capped like
    the spells tab's (a full SRD carries dozens of feats)."""

    #: Rows rendered from the candidate list before the filter is asked for.
    CANDIDATE_ROW_LIMIT = 50

    def __init__(
        self,
        *,
        character_id: int | None,
        service: "DndCharacterExtensionService",
        dataset_index: "DatasetIndexService",
        run_locked: Callable[[Coroutine], asyncio.Task],
        parent=None,
    ) -> None:
        super().__init__(run_locked, parent)
        self._character_id = character_id
        self._service = service
        self._index = dataset_index
        self._links: tuple[DdFeatLink, ...] = ()
        self._snap: "IndexSnapshot | None" = None
        self._candidates: tuple[_FeatCandidate, ...] = ()

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setObjectName("ddFeatsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)

        content_layout.addWidget(self._header("Выбранные черты"))
        self._links_host = QWidget(content)
        self._links_host.setObjectName("ddFeatsHost")
        self._links_layout = QVBoxLayout(self._links_host)
        self._links_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._links_host)

        content_layout.addWidget(
            self._header("Добавить из подключённых датасетов")
        )
        self._filter = QLineEdit(content)
        self._filter.setObjectName("ddFeatsFilter")
        self._filter.setAccessibleName("Фильтр черт")
        self._filter.setPlaceholderText("Фильтр по имени…")
        self._filter.textChanged.connect(lambda _text: self._render_candidates())
        content_layout.addWidget(self._filter)
        self._candidates_host = QWidget(content)
        self._candidates_host.setObjectName("ddFeatsCandidatesHost")
        self._candidates_layout = QVBoxLayout(self._candidates_host)
        self._candidates_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._candidates_host)
        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.request_refresh()

    def request_refresh(self) -> None:
        # The character half of the read rides the id. The unsaved card (the
        # empty id, checkpoint-2 audit; spec «Новая карточка с пустыми
        # разделами») still reads the dataset door: the wall of candidates
        # is dataset knowledge, an unsaved character simply has none chosen
        # — answering «no candidates» would be the lie, and no service door
        # is knocked. The task lands long before any click could arrive
        # (every queued read releases with the tab, silently).
        self._start_locked(self._read_state(), self._on_loaded)

    # ── state (one locked read: choices + the dataset door) ──────────────────

    async def _read_state(self):
        links = (
            ()
            if self._character_id is None
            else tuple(await self._service.get_feat_links(self._character_id))
        )
        return links, await self._index.snapshot()

    def _on_loaded(self, task: asyncio.Task) -> None:
        outcome = self._outcome(task, "загрузка выбранных черт")
        if outcome is _TASK_FAILED:
            if task.cancelled():
                return  # the released tab answers nothing
            self._show_notice(
                "Не удалось загрузить выбранные черты. Подробности — в "
                "журнале приложения; повторите, закрыв и открыв карточку."
            )
            return
        self._links, self._snap = outcome
        self._render()

    # ── rendering (the spells tab's shape, restated for feats) ───────────────

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _header(self, caption: str) -> QLabel:
        label = QLabel(caption)
        label.setObjectName("ddFeatsHeader")
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _render(self) -> None:
        self._clear(self._links_layout)
        if self._links:
            for link in self._links:
                self._links_layout.addWidget(self._link_row(link))
        else:
            hint = QLabel("Пока нет ни одной выбранной черты.")
            hint.setObjectName("ddFeatsEmpty")
            hint.setWordWrap(True)
            self._links_layout.addWidget(hint)
        self._render_candidates()

    def _link_row(self, link: "DdFeatLink") -> QWidget:
        """One choice: name + dataset title (or the dead-source mark) +
        «Снять»."""
        row = QWidget(self)
        row.setObjectName("ddFeatsRow")
        name = link.snapshot_name or link.ref_id
        origin = self._origin_of(link)
        caption = (
            f"{name} · {origin}" if origin else f"{name} — {SOURCE_UNAVAILABLE_NOTE}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(caption)
        label.setObjectName("ddFeatsRowName")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        button = QPushButton("Снять", row)
        button.setObjectName("ddFeatsRemove")
        button.clicked.connect(
            lambda _checked=False, _link=link: self._on_remove(_link)
        )
        layout.addWidget(button)
        return row

    def _origin_of(self, link: "DdFeatLink") -> str:
        """The title of the connected dataset whose ``feats`` section holds
        the pair right now; empty = nobody answers, and the row carries the
        «источник не подключён» mark instead (spec scenario «Датасет сняли —
        имена целы»: the snapshot survives verbatim, only the label dies)."""
        if self._snap is None:
            return ""
        if self._snap.entry(FEATS_SECTION, link.source_key, link.ref_id) is not None:
            return self._snap.titles.get(link.source_key, link.source_key)
        return ""

    def _collect_candidates(self, needle: str) -> tuple[_FeatCandidate, ...]:
        """The choosable feats of the connected datasets, already-chosen
        pairs removed, the filter applied to name and id — the spec's
        «добавление из записей типа „черта“ подключённых датасетов»."""
        lowered = needle.strip().lower()
        chosen = {(link.source_key, link.ref_id) for link in self._links}
        candidates: list[_FeatCandidate] = []
        if self._snap is None:
            return ()
        for dataset_id in self._snap.ids:
            title = self._snap.titles.get(dataset_id, dataset_id)
            for entry in self._snap.entries(FEATS_SECTION, dataset_id):
                if (dataset_id, entry.entry_id) in chosen:
                    continue
                if (
                    lowered
                    and lowered not in entry.name.lower()
                    and lowered not in entry.entry_id.lower()
                ):
                    continue
                candidates.append(
                    _FeatCandidate(dataset_id, entry.entry_id, entry.name, title)
                )
        return tuple(candidates)

    def _render_candidates(self) -> None:
        layout = self._candidates_layout
        self._clear(layout)
        self._candidates = self._collect_candidates(self._filter.text())
        if not self._candidates:
            hint = QLabel("Нет подключённых датасетов или ничего не нашлось по фильтру.")
            hint.setObjectName("ddFeatsNoCandidates")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            return
        shown = self._candidates[: self.CANDIDATE_ROW_LIMIT]
        for candidate in shown:
            button = QPushButton(
                button_caption(f"Добавить: {candidate.name} · {candidate.origin}"),
                self,
            )
            button.setObjectName("ddFeatsCandidate")
            button.clicked.connect(
                lambda _checked=False, _candidate=candidate: self._on_add(_candidate)
            )
            layout.addWidget(button)
        hidden = len(self._candidates) - len(shown)
        if hidden > 0:
            cap = QLabel(
                f"Показаны первые {self.CANDIDATE_ROW_LIMIT}; ещё {hidden} — "
                "уточните фильтр."
            )
            cap.setObjectName("ddFeatsCandidateCap")
            layout.addWidget(cap)

    # ── writes (write + reload inside ONE locked coroutine) ──────────────────

    def _on_add(self, candidate: _FeatCandidate) -> None:
        if self._character_id is None:
            self._show_notice(UNSAVED_CHARACTER_REFUSAL)
            return
        link: DdFeatLink = DdFeatLink(
            source_key=candidate.source_key,
            ref_id=candidate.ref_id,
            snapshot_name=candidate.name,
        )
        self._start_locked(
            self._add_link(link),
            lambda task: self._on_write(task, "выбор черты"),
        )

    async def _add_link(self, link: "DdFeatLink"):
        await self._service.add_feat_link(self._character_id, link)
        return await self._read_state()

    def _on_remove(self, link: "DdFeatLink") -> None:
        if self._character_id is None:
            self._show_notice(UNSAVED_CHARACTER_REFUSAL)
            return
        self._start_locked(
            self._remove_link(link),
            lambda task: self._on_write(task, "снятие черты"),
        )

    async def _remove_link(self, link: "DdFeatLink"):
        await self._service.remove_feat_link(
            self._character_id, link.source_key, link.ref_id
        )
        return await self._read_state()

    def _on_write(self, task: asyncio.Task, what: str) -> None:
        outcome = self._outcome(task, what)
        if outcome is _TASK_FAILED:
            if not task.cancelled():
                self._show_notice(
                    f"Не удалось выполнить действие ({what}). Повторите; "
                    "подробности — в журнале приложения."
                )
            return
        self._links, self._snap = outcome
        self._render()
