"""Sync VM for the LLM setup QML island (R3 pack 2)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.application.services.llm_service import FIELD_CONFIG, FIELD_LABELS

_ENTITY_LABELS: dict[str, str] = {
    "event": "События",
    "organization": "Организации",
    "character": "Персонажи",
    "item": "Предметы",
    "location": "Локации",
}

_ENTITY_ORDER = ["event", "organization", "character", "item", "location"]

_FIELD_PLACEHOLDERS: dict[str, dict[str, str]] = {
    "event": {
        "name": "Короткое название события в духе мира",
        "characteristics": "Опиши ключевые характеристики события",
        "backstory": "Напиши предысторию не менее 20 слов",
    },
    "organization": {
        "name": "Название организации, подходящее сеттингу",
        "characteristics": "Основные характеристики организации",
        "backstory": "Предыстория организации",
        "tasks": "Текущие задачи и цели организации",
    },
    "character": {
        "name": "Имя персонажа, подходящее миру",
        "characteristics": "Внешность и ключевые черты персонажа",
        "backstory": "Предыстория персонажа не менее 20 слов",
        "personality": "Черты характера и особенности поведения",
        "tasks": "Текущие цели и задачи персонажа",
    },
    "item": {
        "name": "Название предмета в духе мира",
        "characteristics": "Описание и свойства предмета",
        "backstory": "История предмета",
    },
    "location": {
        "name": "Название локации, подходящее сеттингу",
        "characteristics": "Описание и особенности локации",
        "backstory": "История локации",
        "tasks": "Что происходит в этой локации",
    },
}

#: Connection + world + one page per entity type, warnings last.
PAGE_WARNINGS = 2 + len(_ENTITY_ORDER)


class LlmSetupViewModel(QObject):
    pageChanged = Signal()
    connectionChanged = Signal()
    worldChanged = Signal()
    checkChanged = Signal()
    savingChanged = Signal()
    checkRequested = Signal()
    saveRequested = Signal()

    def __init__(
        self,
        endpoint: str = "",
        model: str = "",
        api_key: str = "",
        world_prompt: str = "",
        field_prompts: dict | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._page = 0
        self._endpoint = endpoint
        self._model = model
        self._api_key = api_key
        self._world = world_prompt
        self._saving = False
        self._check_busy = False
        self._check_text = ""
        self._check_status: str | None = None
        initial = field_prompts or {}
        self._pages: list[dict] = []
        for etype in _ENTITY_ORDER:
            fields = []
            seeded = initial.get(etype, {})
            for name in FIELD_CONFIG[etype]:
                fields.append({
                    "name": name,
                    "label": FIELD_LABELS.get(name, name),
                    "placeholder": _FIELD_PLACEHOLDERS.get(etype, {}).get(name, ""),
                    "value": seeded.get(name, ""),
                })
            self._pages.append({
                "entityType": etype,
                "title": f"Промты полей — {_ENTITY_LABELS.get(etype, etype)}",
                "fields": fields,
            })

    def _get_page(self) -> int:
        return self._page

    currentPage = Property(int, _get_page, notify=pageChanged)

    def _get_page_count(self) -> int:
        return PAGE_WARNINGS + 1

    pageCount = Property(int, _get_page_count, constant=True)

    def _get_endpoint(self) -> str:
        return self._endpoint

    def _set_endpoint(self, value: str) -> None:
        if self._endpoint != value:
            self._endpoint = value
            self.connectionChanged.emit()
            self.checkChanged.emit()

    endpoint = Property(str, _get_endpoint, _set_endpoint, notify=connectionChanged)

    def _get_model(self) -> str:
        return self._model

    def _set_model(self, value: str) -> None:
        if self._model != value:
            self._model = value
            self.connectionChanged.emit()
            self.checkChanged.emit()

    model = Property(str, _get_model, _set_model, notify=connectionChanged)

    def _get_api_key(self) -> str:
        return self._api_key

    def _set_api_key(self, value: str) -> None:
        if self._api_key != value:
            self._api_key = value
            self.connectionChanged.emit()

    apiKey = Property(str, _get_api_key, _set_api_key, notify=connectionChanged)

    def _get_world(self) -> str:
        return self._world

    def _set_world(self, value: str) -> None:
        if self._world != value:
            self._world = value
            self.worldChanged.emit()

    worldPrompt = Property(str, _get_world, _set_world, notify=worldChanged)

    def _get_field_pages(self) -> list:
        return self._pages

    # The row set is fixed at construction (FIELD_CONFIG order): a constant
    # property keeps typing in one field from rebuilding every delegate.
    fieldPages = Property("QVariant", _get_field_pages, constant=True)

    def _get_check_enabled(self) -> bool:
        return (not self._check_busy) and bool(self._endpoint.strip()) and bool(self._model.strip())

    checkEnabled = Property(bool, _get_check_enabled, notify=checkChanged)

    def _get_check_text(self) -> str:
        return self._check_text

    checkText = Property(str, _get_check_text, notify=checkChanged)

    def _get_check_status(self) -> str:
        return self._check_status or ""

    checkStatus = Property(str, _get_check_status, notify=checkChanged)

    def _get_back_enabled(self) -> bool:
        return (not self._saving) and self._page > 0

    backEnabled = Property(bool, _get_back_enabled, notify=pageChanged)

    def _get_next_visible(self) -> bool:
        return self._page < PAGE_WARNINGS

    nextVisible = Property(bool, _get_next_visible, notify=pageChanged)

    def _get_save_visible(self) -> bool:
        return self._page == PAGE_WARNINGS

    saveVisible = Property(bool, _get_save_visible, notify=pageChanged)

    def _get_save_enabled(self) -> bool:
        return not self._saving

    saveEnabled = Property(bool, _get_save_enabled, notify=savingChanged)

    def _get_saving(self) -> bool:
        return self._saving

    saving = Property(bool, _get_saving, notify=savingChanged)

    @Slot()
    def goBack(self) -> None:
        if self._saving or self._page <= 0:
            return
        self._page -= 1
        self.pageChanged.emit()
        self.savingChanged.emit()

    @Slot()
    def goNext(self) -> None:
        if self._saving or self._page >= PAGE_WARNINGS:
            return
        self._page += 1
        self.pageChanged.emit()
        self.savingChanged.emit()

    @Slot()
    def requestCheck(self) -> None:
        if self.checkEnabled:
            self.checkRequested.emit()

    @Slot()
    def requestSave(self) -> None:
        if not self._saving:
            self.saveRequested.emit()

    @Slot(int, int, str)
    def setFieldValue(self, page_index: int, field_index: int, value: str) -> None:
        # No fieldsChanged here: the model is the delegates' own source, and
        # re-emitting it while typing would reset the editing field.
        if not 0 <= page_index < len(self._pages):
            return
        fields = self._pages[page_index]["fields"]
        if 0 <= field_index < len(fields):
            fields[field_index]["value"] = value

    def field_prompts_dict(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for page in self._pages:
            out[page["entityType"]] = {
                f["name"]: f["value"].strip() for f in page["fields"]
            }
        return out

    def set_check_running(self, text: str) -> None:
        """Facade started the request: neutral status, control blocked."""
        self._check_busy = True
        self._check_text = text
        self._check_status = None
        self.checkChanged.emit()

    def set_check_result(self, text: str, status: str | None) -> None:
        self._check_text = text
        self._check_status = status
        self._check_busy = False
        self.checkChanged.emit()

    def set_saving(self, saving: bool) -> None:
        self._saving = saving
        self.savingChanged.emit()
        self.pageChanged.emit()
        self.checkChanged.emit()
