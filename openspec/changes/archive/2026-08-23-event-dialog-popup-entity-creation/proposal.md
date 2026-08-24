## Why

В приложение существуют два разных паттерна создания связанных сущностей из диалогов редактирования: в карточке сущности — кнопка «Создать нового», открывающая отдельное окно (суб-`EntityCardDialog`), в диалоге события — инлайн-форма создания прямо в табе. Второй паттерн признан лучшим; задача — перенести его на диалог события (создание и редактирование) и привести суб-поток карточек к единому уровню.

## What Changes

- Табы `EventDialog` (организации/персонажи/предметы/локации) заменяются из инлайн-формы на общий виджет «список + кнопки» (аналог `_RelatedSection`): «Привязать существующего», «Создать нового», «Отвязать». Паттерн применяется и к созданию, и к редактированию события (один и тот же виджет).
- По «Создать нового» открывается отдельное полноразмерное окно `EntityCardDialog` нужного типа. По его «Сохранить» сущность создаётся немедленно (`create_entity()` + `session.flush()` без commit) и добавляется в список таба диалога-родителя; commit происходит вместе с сохранением родителя.
- Поппап подгружает списки доступных сущностей для своих related-секций — «Привязать существующего» внутри поппапа работает; `related_changes` из поппапа применяются к созданной сущности (link-only sync через `sync_related`).
- Суб-поток «Создать нового» из карточки сущности доводится до того же уровня: поппап наполняется доступными сущностями, `related_changes` новой сущности применяются (ранее отбрасывались). Общий glue-хелпер в `ApplicationWiring` используется обоими потоками.
- Общий виджет таба выносится в новый модуль `app/presentation/views/related_section.py` (публичное имя `RelatedSection`), используется `EventDialog` и `EntityCardDialog`.
- Контракт сохранения события не меняется на уровне сервиса: табы `EventDialog` эмитят списки dicts `{"_existing_id": id}`; `EventService` (`apply_event_relations` и пр.) без изменений.
- В списках табов нет маркеров (честные имена сущностей).

## Capabilities

### New Capabilities

- `related-entity-creation`: создание и привязка связанных сущностей из диалогов редактирования события и карточки сущности через отдельное окно-поппап; семантика записи (flush при сохранении поппапа, commit при сохранении родителя), применение связей из поппапа, поведение при отмене.

### Modified Capabilities

(нет — существующие specs `llm-configuration`, `llm-remote-provider`, `ui-testing` на уровне требований не меняются)

## Impact

- `app/presentation/views/event_dialog.py` — убирается `_EntityTabWidget`, табы на `RelatedSection`, новый сигнал `create_related_requested`, новое attr-API `set_available_entities` / `add_related_entity`, `get_data()` → dicts `{"_existing_id": id}`.
- `app/presentation/views/entity_card_dialog.py` — `_RelatedSection` заменяется импортом из общего модуля.
- `app/presentation/views/related_section.py` — новый модуль (переезд виджета).
- `app/application/wiring.py` — общий хелпер суб-окна (наполнение доступных + создание + применение связей), подключение к `EventDialog` и `EntityCardDialog`; `_load_available_into_dialog` переводится на attr-API.
- Сервисы (`event_service.py`, `entity_service.py`) и `tests/application/test_event_service.py` — не меняются.
- Тесты: `tests/presentation/test_views.py` (TestEventDialogEditMode), `tests/presentation/test_dialogs.py`, новые тесты `RelatedSection`; E2E в `tests/ui/` закрывают новые wiring-пути (CI-гейт — 100% строкового покрытия `app/`, все новые строки должны выполняться тестами); `tests/ui/helpers.py` обновляется под новый attr-API диалога.
