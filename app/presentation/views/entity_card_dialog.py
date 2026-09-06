"""Entity card QML island in the stable native dialog facade."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import QDate, QEvent, QPoint, QRect, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtQml import QQmlComponent, QQmlContext
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.dialog_image_provider import clear_dialog_pixmap, put_dialog_pixmap
from app.presentation.qml.engine import QML_IMPORT_PATH
from app.presentation.qml.island_size import fit_dialog_to_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.utils.image_utils import load_entity_original, load_entity_preview
from app.presentation.viewmodels.entity_card_island_view_model import (
    EntityCardIslandViewModel,
)
from app.presentation.views.event_dialog import (
    _CheckProxy,
    _ClickProxy,
    _FieldProxy,
    _ListProxy,
)
from app.presentation.views.image_viewer_dialog import ImageViewerDialog
from app.presentation.views.theme_date_popup import ThemeDatePopup

ROOT_QML = str(Path(QML_IMPORT_PATH) / "EntityCardRoot.qml")


@dataclass(frozen=True)
class _FieldSpec:
    name: str
    label: str
    kind: str


_FIELD_SPECS: dict[str, list[_FieldSpec]] = {
    "character": [
        _FieldSpec("personality", "Личность", "mention"),
        _FieldSpec("image", "Изображение", "image"),
        _FieldSpec("tasks", "Задачи", "mention"),
    ],
    "organization": [
        _FieldSpec("image", "Изображение", "image"),
        _FieldSpec("tasks", "Задачи", "mention"),
    ],
    "location": [
        _FieldSpec("image", "Изображение", "image"),
        _FieldSpec("tasks", "Задачи", "mention"),
    ],
    "item": [],
    "rating": [],
}

_RELATED_CONFIG: dict[str, list[dict[str, str]]] = {
    "organization": [
        {"attr": "characters", "label": "Персонажи", "entity_type": "character"},
        {"attr": "items", "label": "Предметы", "entity_type": "item"},
        {"attr": "locations", "label": "Локации", "entity_type": "location"},
    ],
    "character": [
        {"attr": "items", "label": "Предметы", "entity_type": "item"},
        {"attr": "locations", "label": "Локации", "entity_type": "location"},
        {"attr": "organizations", "label": "Организации", "entity_type": "organization"},
    ],
    "item": [
        {"attr": "locations", "label": "Локации", "entity_type": "location"},
        {"attr": "characters", "label": "Персонажи", "entity_type": "character"},
        {"attr": "organizations", "label": "Организации", "entity_type": "organization"},
    ],
    "location": [
        {"attr": "characters", "label": "Персонажи", "entity_type": "character"},
        {"attr": "organizations", "label": "Организации", "entity_type": "organization"},
        {"attr": "items", "label": "Предметы", "entity_type": "item"},
    ],
}

_IMAGE_FILTERS = "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Все файлы (*)"


class _ValueProxy:
    def __init__(
        self,
        getter: Callable[[], int],
        setter: Callable[[int], None],
        minimum: int,
        maximum: int,
    ) -> None:
        self._getter = getter
        self._setter = setter
        self._minimum = minimum
        self._maximum = maximum

    def value(self) -> int:
        return self._getter()

    def setValue(self, value: int) -> None:
        self._setter(value)

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum


class _DateProxy:
    def __init__(self, dialog: "EntityCardDialog", which: str) -> None:
        self._dialog = dialog
        self._which = which

    def date(self) -> QDate:
        value = (
            self._dialog.vm._start_date
            if self._which == "start"
            else self._dialog.vm._end_date
        )
        return QDate(value.year, value.month, value.day)

    def setDate(self, value: QDate) -> None:
        if self._which == "start":
            self._dialog.vm.set_dates(start=value.toPython())
        else:
            self._dialog.vm.set_dates(end=value.toPython())

    def isVisible(self) -> bool:
        return self._which == "start" or not self._dialog.vm._no_end

    def isHidden(self) -> bool:
        return not self.isVisible()


class _VisibleProxy:
    def __init__(
        self,
        visible: Callable[[], bool],
        click: Callable[[], None] | None = None,
        text: Callable[[], str] = lambda: "",
    ) -> None:
        self._visible = visible
        self._click = click
        self._text = text

    def isVisible(self) -> bool:
        return self._visible()

    def isHidden(self) -> bool:
        return not self._visible()

    def click(self) -> None:
        if self._click is not None:
            self._click()

    def text(self) -> str:
        return self._text()


class _MusicFieldProxy(_FieldProxy):
    def __init__(self, dialog: "EntityCardDialog") -> None:
        super().__init__(
            lambda: dialog.vm._music_url,
            dialog.vm.setMusicUrl,
        )
        self._dialog = dialog

    def isVisible(self) -> bool:
        return self._dialog.vm._music_editing or not self._dialog.vm._music_url

    def isHidden(self) -> bool:
        return not self.isVisible()

    def setFocus(self) -> None:
        return None


class _ReadOnlyFieldProxy(_FieldProxy):
    def __init__(self, getter, setter, ai_proxy) -> None:
        super().__init__(getter, setter)
        self._ai_proxy = ai_proxy

    def isReadOnly(self) -> bool:
        return self._ai_proxy.is_generating


class _ImageProxy:
    def __init__(self, dialog: "EntityCardDialog") -> None:
        self._dialog = dialog

    def pixmap(self) -> QPixmap:
        return QPixmap(self._dialog._displayed_pixmap)

    def text(self) -> str:
        return "" if self._dialog.vm._image_available else "Нет изображения"

    def click(self) -> None:
        self._dialog._open_image_viewer()


class _SectionProxy:
    def __init__(self, dialog: "EntityCardDialog", attr: str) -> None:
        self._dialog = dialog
        self._attr = attr
        self._state = dialog.vm.sections[attr]
        self.create_requested = self._state.createRequested
        self.list_widget = _ListProxy(self._state)
        self.link_button = _ClickProxy(self._on_link_existing)
        self.create_button = _ClickProxy(self._state.requestCreate)
        self.remove_button = _ClickProxy(
            self._state.unlinkSelected, lambda: self._state.selectedIndex >= 0
        )

    @property
    def _available(self):
        return self._state._available

    def set_entities(self, entities) -> None:
        self._state.set_entities(entities)

    def set_available(self, entities) -> None:
        self._state.set_available(entities)

    def add_entity(self, entity) -> None:
        self._state.add_entity(entity)

    def get_current_ids(self):
        return self._state.get_current_ids()

    def _on_link_existing(self) -> None:
        cfg = next(c for c in self._dialog._related_configs if c["attr"] == self._attr)
        self._dialog._open_related_picker(self._attr, cfg["label"])

    def _on_remove(self) -> None:
        self._state.unlinkSelected()


class EntityCardDialog(QDialog):
    saved = Signal(dict)
    create_related_requested = Signal(str, str)
    mention_clicked = Signal(str, int)
    image_picked = Signal(bytes)
    open_character_sheet_requested = Signal()

    def __init__(
        self,
        entity_vm,
        entity_type: str = "organization",
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = entity_vm
        self._theme = theme
        self._qml_theme = theme if theme is not None else get_default_theme()
        self._entity_type = entity_type
        self._extra_specs = list(_FIELD_SPECS.get(entity_type, []))
        self._related_configs = list(_RELATED_CONFIG.get(entity_type, []))
        self._has_image_field = any(spec.kind == "image" for spec in self._extra_specs)
        self._populated_entity_id: int | None = None
        self._image_id: int | None = None
        self._viewer_original = QPixmap()
        self._viewer_preview = QPixmap()
        self._displayed_pixmap = QPixmap()
        self._image_key = f"entity-card-{uuid4().hex}"
        self._saving = False
        self._close_guard = None
        self._date_target = "start"
        self.setWindowTitle(f"Карточка: {entity_type}")
        # Floor only: the window opens at the island's content size below, so
        # every field, the related section and the action row are visible.
        self._size_floor = (750 if self._has_image_field else 550, 550)
        self.setMinimumSize(*self._size_floor)

        self.vm = EntityCardIslandViewModel(
            entity_type,
            self._extra_specs,
            self._related_configs,
            owner=self,
            parent=self,
        )
        self._ai_buttons = [
            self.vm.nameAi,
            self.vm.ai_proxies["characteristics"],
            self.vm.ai_proxies["backstory"],
            *[
                self.vm.ai_proxies[spec.name]
                for spec in self._extra_specs
                if spec.kind == "mention"
            ],
        ]
        self._entity_button = self.vm.entityAi

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._engine = setup_qml_shell(QApplication.instance(), self._qml_theme)
        self.quick = QQuickWidget(self._engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._qml_theme, parent=self)
        self._context = QQmlContext(self._engine.rootContext(), self)
        self.vm.setParent(self._context)
        self._palette.setParent(self._context)
        self._context.setContextProperty("entityCardVm", self.vm)
        self._context.setContextProperty("islandPalette", self._palette)
        source = QUrl.fromLocalFile(ROOT_QML)
        self._component = QQmlComponent(self._engine, source, self)
        root = self._component.create(self._context)
        assert root is not None, self._component.errors()
        self.quick.setContent(source, self._component, root)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)
        self._root = root
        fit_dialog_to_island(self, root, floor=self._size_floor)

        for host in self.vm.hosts.values():
            host.attachWidget(self.quick)
        for proxy in self.vm.mention_proxies.values():
            proxy.mention_clicked.connect(self.mention_clicked)
        self.vm.saveRequested.connect(self._on_save)
        self.vm.cancelRequested.connect(self._on_cancel_clicked)
        self.vm.datePopupRequested.connect(self._open_date_popup)
        self.vm.imagePickRequested.connect(self._on_pick_image)
        self.vm.imageClearRequested.connect(self._on_clear_image)
        self.vm.imageOpenRequested.connect(self._open_image_viewer)
        self.vm.musicOpenRequested.connect(self._open_music_url)
        self.vm.characterSheetRequested.connect(self.open_character_sheet_requested)

        self.date_popup = ThemeDatePopup(self)
        self.date_popup.date_selected.connect(self._set_selected_date)

        self._related_sections: dict[str, _SectionProxy] = {}
        for cfg in self._related_configs:
            attr = cfg["attr"]
            state = self.vm.sections[attr]
            proxy = _SectionProxy(self, attr)
            self._related_sections[attr] = proxy
            state.createRequested.connect(
                lambda a=attr, t=cfg["entity_type"]:
                    self.create_related_requested.emit(a, t)
            )
            state.linkRequested.connect(
                lambda a=attr, label=cfg["label"]:
                    self._open_related_picker(a, label)
            )

        # Non-widget ducks preserve the Python facade while the visible form is QML.
        self.name_input = _ReadOnlyFieldProxy(
            lambda: self.vm.name,
            lambda value: setattr(self.vm, "name", value),
            self.vm.nameAi,
        )
        self.rating_input = _ValueProxy(
            lambda: self.vm._rating, self.vm.set_rating, 1, 20
        )
        self.start_date_input = _DateProxy(self, "start")
        self.end_date_input = _DateProxy(self, "end")
        self.no_end_date_cb = _CheckProxy(self.vm)
        self.characteristics_input = self.vm.mention_proxies["characteristics"]
        self.backstory_input = self.vm.mention_proxies["backstory"]
        self.characteristics_input.isReadOnly = (
            lambda: self.vm.ai_proxies["characteristics"].is_generating
        )
        self.backstory_input.isReadOnly = (
            lambda: self.vm.ai_proxies["backstory"].is_generating
        )
        self._extra_widgets = {
            spec.name: self.vm.mention_proxies[spec.name]
            for spec in self._extra_specs if spec.kind == "mention"
        }
        for name, proxy in self._extra_widgets.items():
            proxy.isReadOnly = lambda n=name: self.vm.ai_proxies[n].is_generating
        self.personality_input = self._extra_widgets.get("personality")
        self.tasks_input = self._extra_widgets.get("tasks")
        self.image_input = None
        self.music_input = _MusicFieldProxy(self)
        self.music_display = _VisibleProxy(
            lambda: bool(self.vm._music_url) and not self.vm._music_editing,
            text=lambda: self.vm._music_url,
        )
        self.music_edit_btn = _ClickProxy(self.vm.toggleMusicEdit)
        self.image_label = _ImageProxy(self) if self._has_image_field else None
        self.pick_image_btn = _ClickProxy(self._on_pick_image)
        self.clear_image_btn = _ClickProxy(
            self._on_clear_image, lambda: self.vm._image_available
        )
        self.open_sheet_button = _VisibleProxy(
            lambda: self.vm._character_sheet_available,
            self.vm.requestCharacterSheet,
            lambda: "Открыть чар-лист",
        )
        self.save_button = _ClickProxy(self.vm.requestSave, lambda: self.vm.saveEnabled)
        self.cancel_button = _ClickProxy(self._on_cancel_clicked)

    @property
    def entity_type(self) -> str:
        return self._entity_type

    @property
    def populated_entity_id(self) -> int | None:
        return self._populated_entity_id

    def set_character_sheet_available(self, available: bool) -> None:
        self.vm.set_character_sheet_available(
            self._entity_type == "character" and available
        )

    def _set_music_url(self, url: str) -> None:
        self.vm.set_music_url(url)

    def _on_toggle_music_edit(self) -> None:
        self.vm.toggleMusicEdit()

    def _open_music_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _on_pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите изображение", "", _IMAGE_FILTERS
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError:
            QMessageBox.warning(
                self, "Изображение", f"Не удалось прочитать файл: {path}"
            )
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data) or pixmap.isNull():
            QMessageBox.warning(
                self, "Изображение", "Файл повреждён или не является изображением."
            )
            return
        self._image_id = None
        self._viewer_original = pixmap
        self._viewer_preview = QPixmap()
        self._display_pixmap(
            pixmap.scaled(
                280,
                280,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.image_picked.emit(data)

    def set_stored_image_id(self, image_id: int) -> None:
        self._image_id = image_id

    def _on_clear_image(self) -> None:
        self._image_id = None
        self._viewer_original = QPixmap()
        self._viewer_preview = QPixmap()
        self._clear_preview()

    def _open_image_viewer(self) -> None:
        if not self._has_image_field:
            return
        ImageViewerDialog(
            self._viewer_original,
            self._viewer_preview,
            parent=self,
            theme=self._theme,
        ).exec()

    def _display_pixmap(self, pixmap: QPixmap) -> None:
        if not self._has_image_field:
            return
        if pixmap.isNull():
            self._clear_preview()
            return
        self._displayed_pixmap = QPixmap(pixmap)
        put_dialog_pixmap(self._image_key, pixmap)
        self.vm.set_image_source(f"image://dialog/{self._image_key}", True)

    def _clear_preview(self) -> None:
        if not self._has_image_field:
            return
        self._displayed_pixmap = QPixmap()
        clear_dialog_pixmap(self._image_key)
        self.vm.set_image_source("", False)

    def populate(self, entity: Any) -> None:
        self._populated_entity_id = getattr(entity, "id", None)
        self.vm.name = getattr(entity, "name", "")
        rating = getattr(entity, "rating", 1)
        if isinstance(rating, int):
            self.vm.set_rating(rating)
        start = getattr(entity, "start_date", None)
        end = getattr(entity, "end_date", None)
        if isinstance(start, date):
            self.vm.set_dates(start=start)
        if isinstance(end, date):
            self.vm.set_dates(end=end)
            self.vm.set_no_end(False)
        elif end is None:
            self.vm.set_no_end(True)
        description = getattr(entity, "description", None)
        if description is not None:
            self.vm.hosts["characteristics"].storage = (
                getattr(description, "characteristics", "") or ""
            )
            self.vm.hosts["backstory"].storage = (
                getattr(description, "backstory", "") or ""
            )
        for spec in self._extra_specs:
            if spec.kind == "mention":
                self.vm.hosts[spec.name].storage = getattr(entity, spec.name, "") or ""
        if self._has_image_field:
            self._image_id = getattr(entity, "image_id", None)
            self._viewer_original = load_entity_original(entity)
            self._viewer_preview = load_entity_preview(entity, slot_size=4096)
            self._display_pixmap(load_entity_preview(entity, slot_size=280))
        music_url = getattr(entity, "music_url", "")
        self.vm.set_music_url(music_url if isinstance(music_url, str) else "")
        for attr, state in self.vm.sections.items():
            state.set_entities(list(getattr(entity, attr, []) or []))

    def set_available_entities(self, attr: str, entities: list[Any]) -> None:
        state = self.vm.sections.get(attr)
        if state is not None:
            state.set_available(entities)

    def add_related_entity(self, attr: str, entity: Any) -> None:
        state = self.vm.sections.get(attr)
        if state is not None:
            state.add_entity(entity)

    def get_data(self) -> dict:
        data = {
            "name": self.vm.name.strip(),
            "rating": self.vm._rating,
            "start_date": self.vm._start_date,
            "end_date": None if self.vm._no_end else self.vm._end_date,
            "characteristics": self.vm.hosts["characteristics"].storage.strip(),
            "backstory": self.vm.hosts["backstory"].storage.strip(),
            "music_url": self.vm._music_url.strip(),
        }
        for spec in self._extra_specs:
            if spec.kind == "mention":
                data[spec.name] = self.vm.hosts[spec.name].storage.strip()
        if self._has_image_field:
            data["image_id"] = self._image_id
        if self.vm.sections:
            data["related_changes"] = {
                attr: {"current_ids": state.get_current_ids()}
                for attr, state in self.vm.sections.items()
            }
        return data

    def get_mention_edits(self):
        return [
            self.vm.mention_proxies["characteristics"],
            self.vm.mention_proxies["backstory"],
            *[
                self.vm.mention_proxies[spec.name]
                for spec in self._extra_specs if spec.kind == "mention"
            ],
        ]

    def get_ai_buttons(self):
        return list(self._ai_buttons)

    def get_entity_button(self):
        return self._entity_button

    def set_save_locked(self, locked: bool) -> None:
        self.vm.set_save_locked(locked)

    def set_close_guard(self, fn) -> None:
        self._close_guard = fn

    def _is_generation_active(self) -> bool:
        return any(button.is_generating for button in self._ai_buttons) or (
            self._entity_button.is_cancelling
        )

    def _on_save(self) -> None:
        if self._saving or not self.vm.saveEnabled:
            return
        self._saving = True
        self.vm.set_saving(True)
        self.saved.emit(self.get_data())

    def finish_saving(self, success: bool) -> None:
        self._saving = False
        self.vm.set_saving(False)
        if success:
            self.accept()

    def _on_cancel_clicked(self) -> None:
        if self._saving:
            return
        if self._close_guard is not None:
            self._close_guard()
        else:
            super().reject()

    def reject(self) -> None:
        if self._saving or self._is_generation_active():
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._saving:
            event.ignore()
            return
        if self._is_generation_active() and self._close_guard is not None:
            event.ignore()
            self._close_guard()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and (self._saving or self._is_generation_active())
        ):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _open_date_popup(
        self, which: str, x: float, y: float, width: float, height: float
    ) -> None:
        self._date_target = which
        top_left = self.quick.mapToGlobal(QPoint(int(x), int(y)))
        anchor = QRect(top_left, QSize(max(int(width), 0), max(int(height), 0)))
        current = self.vm._start_date if which == "start" else self.vm._end_date
        self.date_popup.open_at(anchor, current)

    def _set_selected_date(self, selected) -> None:
        if self._date_target == "start":
            self.vm.set_dates(start=selected)
        else:
            self.vm.set_dates(end=selected)

    def _open_related_picker(self, attr: str, label: str) -> None:
        state = self.vm.sections[attr]
        candidates = state.candidates()
        if not candidates:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Выберите {label.lower()}")
        dialog.setMinimumSize(300, 400)
        layout = QVBoxLayout(dialog)
        items = QListWidget(dialog)
        items.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for entity in candidates:
            item = QListWidgetItem(getattr(entity, "name", str(entity)))
            item.setData(256, getattr(entity, "id", None))
            items.addItem(item)
        layout.addWidget(items)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_ids = {item.data(256) for item in items.selectedItems()}
            for entity in candidates:
                if getattr(entity, "id", None) in selected_ids:
                    state.add_entity(entity)

    def _release_island(self) -> None:
        clear_dialog_pixmap(self._image_key)
        self.quick.setSource(QUrl())

    def done(self, result: int) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)
