"""The module's section on the game window (task 2.4; design Д8/Д9).

The one place the D&D module touches the kernel's chrome: while attached it
owns a badge «D&D» in the window's menu bar (a corner widget — design Д8
«Метка главного окна — виджет в строке меню, добавляемый модулем при
attach») and a «D&D» menu group holding the module's entries. Removing the
section (module off, task 2.3) takes both back, leaving the ordinary game's
menu bar byte-for-byte as it stood before the attach.

The section is inert beyond assembling widgets: the disable flow's
confirmation, the flag write and the re-show of the kernel's enable entry
are the façade's business (:class:`app.dd.module.DndModule`), reached only
through the :attr:`disable_requested` signal. Since group 5 the menu also
carries «Датасеты D&D…» (spec main-window «Метка системы и меню модуля»),
which does the same trick through :attr:`datasets_requested`: the façade
owns the sheet, its stack entry and its single-instance raise. The entry is
printed only when the composition gave the module the datasets screen stack
(the constructor's ``datasets_available`` flag) — a module composed without
it never shows a dead action.

Like the kernel's own menu bar (NRI-0014 L2), every action is pinned to
``NoRole`` — Russian captions must never feed the macOS special-menu
heuristic, and this menu is built after the kernel's construction-time
NoRole loop has run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel

from app.presentation.utils.caption_utils import button_caption

if TYPE_CHECKING:
    from app.presentation.views.main_window import MainWindow

#: The menu-bar badge text (spec main-window «Метка системы и меню модуля»).
DD_BADGE_TEXT = "D&D"
#: The module's menu group title.
DD_MENU_TITLE = "D&D"
#: The module's own lifecycle entry (spec dnd-module-lifecycle «Выключение
#: модуля с сохранением данных»).
DD_DISABLE_ACTION_TEXT = "Выключить D&D-модуль…"
#: The module's datasets entry (spec main-window «Метка системы и меню
#: модуля»: «Датасеты D&D…» opens the одноимённый лист — the caption is the
#: sheet header's too, one threaded name, the «Настройка LLM…» precedent).
DD_DATASETS_ACTION_TEXT = "Датасеты D&D…"
#: The module's reference-sheet entry (add-dnd-game-face task 6.3, spec
#: dnd-reference-records «Справочный лист с вкладками по типам»; the proposal
#: names the caption «Справочник…» — again one name with the sheet header).
DD_REFERENCE_ACTION_TEXT = "Справочник…"
#: The module's character-import entry (add-dnd-game-face task 9.4, spec
#: dnd-character-import «Точки входа явные»: the creation half — a fresh
#: character has no id and no module tab, so the module's own menu is its
#: entry; the overwrite half lives on the «D&D» tab of an open card).
DD_CHARACTER_IMPORT_ACTION_TEXT = "Импорт персонажа из файла LSS…"
#: The module's bestiary entry (add-dnd-game-face task 10.1, spec dnd-bestiary
#: «Меню модуля SHALL открывать лист "Бестиарий"» — again one caption with
#: the sheet header, the «Справочник…» precedent).
DD_BESTIARY_ACTION_TEXT = "Бестиарий…"
#: The module's grimoire entry (add-dnd-game-face task 4.5, spec
#: dnd-grimoire-import «Гримуары доступны из интерфейса игры» — the sheet is
#: named «Гримуары…», one caption with the sheet header, the «Справочник…»
#: precedent).
DD_GRIMOIRES_ACTION_TEXT = "Гримуары…"
#: The module's character-generation entry (add-dnd-lss-generation task 7.3,
#: spec dnd-generation «Генерация персонажа с нуля»: the creation entry of the
#: generation task sheet — the top-up half lives on the «D&D» tab of an open
#: card, exactly like the two halves of the import entry above).
DD_CHARACTER_GENERATION_ACTION_TEXT = "Сгенерировать персонажа…"


class DndWindowSection(QObject):
    """Badge + «D&D» menu installed on one game window's menu bar.

    Constructed by the façade per attach and removed per detach; the parent
    is the window, so an abandoned section dies with the window anyway.
    :meth:`remove` is called once per install (the façade keeps that pair),
    and restores the corner widget that stood under the badge before.
    """

    #: The master picked «Выключить D&D-модуль…» — the façade answers with
    #: the confirmation and the whole disable flow.
    disable_requested = Signal()
    #: The master picked «Датасеты D&D…» — the façade raises (or builds) the
    #: datasets sheet on the connector's stack (task 5.2).
    datasets_requested = Signal()
    #: The master picked «Справочник…» — the façade raises (or builds) the
    #: reference sheet on the connector's stack (add-dnd-game-face task 6.3).
    reference_requested = Signal()
    #: The master picked «Импорт персонажа из файла LSS…» — the façade opens the
    #: file dialog and runs the creation half of the import (add-dnd-game-face
    #: task 9.4; the overwrite half lives on the «D&D» tab of an open card).
    character_import_requested = Signal()
    #: The master picked «Бестиарий…» — the façade raises (or builds) the
    #: bestiary sheet on the connector's stack (add-dnd-game-face task 10.1).
    bestiary_requested = Signal()
    #: The master picked «Гримуары…» — the façade raises (or builds) the
    #: grimoire sheet on the connector's stack (add-dnd-game-face task 4.5).
    grimoires_requested = Signal()
    #: The master picked «Сгенерировать персонажа…» — the façade checks the
    #: dataset gate (spec «Гейт активации генерации»: ≥1 подключённый датасет,
    #: иначе пояснение) and raises the character generation task sheet
    #: (add-dnd-lss-generation task 7.3).
    character_generation_requested = Signal()

    def __init__(
        self,
        window: MainWindow,
        datasets_available: bool = False,
        reference_available: bool = False,
        character_import_available: bool = False,
        bestiary_available: bool = False,
        grimoires_available: bool = False,
        character_generation_available: bool = False,
    ) -> None:
        super().__init__(window)
        self._window = window
        menu_bar = window.menuBar()

        # The badge rides the menu bar's corner — the штатный seat for a
        # widget in the bar; whatever stood there before returns on remove.
        self._previous_corner = menu_bar.cornerWidget(Qt.Corner.TopRightCorner)
        self._badge = QLabel(DD_BADGE_TEXT, menu_bar)
        self._badge.setObjectName("ddSystemBadge")
        self._badge.setContentsMargins(6, 0, 6, 0)
        menu_bar.setCornerWidget(self._badge, Qt.Corner.TopRightCorner)

        # The menu family consumes a single '&' as a mnemonic marker — the
        # live audit 2026-10-10 caught «D&D» printed as «DD»; doubling keeps
        # the group title and both ampersand entries verbatim on screen.
        self._menu = menu_bar.addMenu(button_caption(DD_MENU_TITLE))
        self._menu.setObjectName("ddModuleMenu")
        self._menu.menuAction().setMenuRole(QAction.MenuRole.NoRole)
        self._datasets_action: QAction | None = None
        if datasets_available:
            # A module composed without the datasets screen stack prints no
            # dead action (group 2's posture, kept for that composition).
            self._datasets_action = QAction(
                button_caption(DD_DATASETS_ACTION_TEXT), self._menu
            )
            self._datasets_action.setObjectName("ddDatasetsAction")
            self._datasets_action.setMenuRole(QAction.MenuRole.NoRole)
            self._datasets_action.triggered.connect(self.datasets_requested.emit)
            self._menu.addAction(self._datasets_action)
        self._reference_action: QAction | None = None
        if reference_available:
            # The browsing sheet needs a composed source to browse (task 6.3
            # — the same no-dead-action posture as the datasets entry).
            self._reference_action = QAction(DD_REFERENCE_ACTION_TEXT, self._menu)
            self._reference_action.setObjectName("ddReferenceAction")
            self._reference_action.setMenuRole(QAction.MenuRole.NoRole)
            self._reference_action.triggered.connect(self.reference_requested.emit)
            self._menu.addAction(self._reference_action)
        self._bestiary_action: QAction | None = None
        if bestiary_available:
            # The bestiary needs the composed service (task 10.1 — the same
            # no-dead-action posture as every other entry here).
            self._bestiary_action = QAction(DD_BESTIARY_ACTION_TEXT, self._menu)
            self._bestiary_action.setObjectName("ddBestiaryAction")
            self._bestiary_action.setMenuRole(QAction.MenuRole.NoRole)
            self._bestiary_action.triggered.connect(self.bestiary_requested.emit)
            self._menu.addAction(self._bestiary_action)
        self._grimoires_action: QAction | None = None
        if grimoires_available:
            # The grimoire screen needs its composed storage/connections/
            # import trio (task 4.5 — the same no-dead-action posture).
            self._grimoires_action = QAction(DD_GRIMOIRES_ACTION_TEXT, self._menu)
            self._grimoires_action.setObjectName("ddGrimoiresAction")
            self._grimoires_action.setMenuRole(QAction.MenuRole.NoRole)
            self._grimoires_action.triggered.connect(self.grimoires_requested.emit)
            self._menu.addAction(self._grimoires_action)
        self._character_import_action: QAction | None = None
        if character_import_available:
            # The creation entry of task 9.4 (spec dnd-character-import
            # «Точки входа явные»); without a composed import service the
            # menu prints no dead action (the datasets entry's posture).
            self._character_import_action = QAction(
                DD_CHARACTER_IMPORT_ACTION_TEXT, self._menu
            )
            self._character_import_action.setObjectName("ddCharacterImportAction")
            self._character_import_action.setMenuRole(QAction.MenuRole.NoRole)
            self._character_import_action.triggered.connect(
                self.character_import_requested.emit
            )
            self._menu.addAction(self._character_import_action)
        self._character_generation_action: QAction | None = None
        if character_generation_available:
            # Пункт генерации персонажа (add-dnd-lss-generation task 7.3).
            # Общий AI-гейт перечитывается façade при каждом срабатывании
            # (настройка LLM меняется посреди сессии), поэтому действие
            # печатается активным, а отказ объясняет modeless-боксом; тут
            # фиксируется только факт собранной генерации.
            self._character_generation_action = QAction(
                DD_CHARACTER_GENERATION_ACTION_TEXT, self._menu
            )
            self._character_generation_action.setObjectName(
                "ddCharacterGenerationAction"
            )
            self._character_generation_action.setMenuRole(QAction.MenuRole.NoRole)
            self._character_generation_action.triggered.connect(
                self.character_generation_requested.emit
            )
            self._menu.addAction(self._character_generation_action)
        self._disable_action = QAction(
            button_caption(DD_DISABLE_ACTION_TEXT), self._menu
        )
        self._disable_action.setObjectName("ddDisableAction")
        self._disable_action.setMenuRole(QAction.MenuRole.NoRole)
        self._disable_action.triggered.connect(self.disable_requested.emit)
        self._menu.addAction(self._disable_action)

    def remove(self) -> None:
        """Take the badge and the menu group out of the window's menu bar."""
        menu_bar = self._window.menuBar()
        # Drop the badge only while it is still the corner's resident (the
        # kernel owns the bar too; a foreign widget must not be unseated).
        if menu_bar.cornerWidget(Qt.Corner.TopRightCorner) is self._badge:
            menu_bar.setCornerWidget(self._previous_corner, Qt.Corner.TopRightCorner)
        menu_bar.removeAction(self._menu.menuAction())
        self._menu.deleteLater()
        self._badge.deleteLater()
