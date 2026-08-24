## 1. Общий виджет секции

- [x] 1.1 Создать `app/presentation/views/related_section.py` с публичным `RelatedSection` — перенос кода `_RelatedSection` из `entity_card_dialog.py` без изменения поведения (сигнал `create_requested`, API `set_entities`/`set_available`/`add_entity`/`get_current_ids`). Проверка: `python -c "from app.presentation.views.related_section import RelatedSection"` выполняется, `ruff check app/` чисто.
- [x] 1.2 В `entity_card_dialog.py` удалить `_RelatedSection` и importar `RelatedSection` из нового модуля (секции карточки продолжают работать как раньше). Проверка: `tests/presentation/test_dialogs.py` и `tests/presentation/test_views.py::TestEntityCardDialogRelated` зелёные.
- [x] 1.3 Тесты виджета: создать/расширить тесты `RelatedSection` — добавление (`add_entity`), множественный выбор в «Привязать существующего», «Отвязать», `get_current_ids`. Проверка: новые тесты зелёные.

## 2. Rebuild EventDialog

- [x] 2.1 В `event_dialog.py` удалить `_EntityTabWidget`; 4 таба (`org_tab`/`char_tab`/`item_tab`/`loc_tab`) становятся инстансами `RelatedSection` с кнопками «Привязать существующего»/«Создать нового»/«Отвязать» и без инлайн-формы; добавить сигнал `create_related_requested(str, str)`, переопределяющий forward из секций. Проверка: `TestEventDialog` / `TestEventDialogEditMode` (обновлённые) зелёные.
- [x] 2.2 Публичный API `EventDialog`: `set_available_entities(attr, entities)`, `add_related_entity(attr, entity)`, `populate(event)` заполняет секции `set_entities(...)`. Проверка: тест предзаполнения при редактировании — секции содержат связи события (id через `get_current_ids`).
- [x] 2.3 `get_data()` — `organizations/characters/items/locations` как списки `{"_existing_id": id}` из `get_current_ids()` секций. Проверка: тест `get_data` (создание и редактирование) отдаёт dicts `_existing_id` для добавленных сущностей.
- [x] 2.4 Тест сигнала: клик «Создать нового» в каждом табе эмитит `create_related_requested` с правильными `(attr, entity_type)`; `add_related_entity` отражается в `get_data()`. Проверка: новые тесты в `test_dialogs.py` зелёные.

## 3. Wiring

- [x] 3.1 Перевести `_load_available_into_dialog` в `wiring.py` на attr-API: `dialog.set_available_entities("organizations", ...)` × 4. Проверка: E2E `create_event_via_ui`-сценарий (tests/ui) работает после обновления helpers (п. 4.1).
- [x] 3.2 Общий async-хелперApplicationWiring по design D4: суб-`EntityCardDialog` (parent — родительский диалог), wiring mentions/AI, наполнение `_RELATED_CONFIG[entity_type]` через `get_all()`, по `saved` — `create_entity` + `flush` + `sync_related` по `related_changes` + `add_related_entity`; `create_related_requested` суб-диалога не подключать. Заменить `on_create_related` карточки этим хелпером; подключить хелпер к `create_related_requested` в `on_add_event` и `on_edit_event`. Проверка: E2E-сценарии группы 4 зелёные.

## 4. Tесты E2E и helpers

- [x] 4.1 Обновить `tests/ui/helpers.py`: `watch_available_entity_load` под новый attr-API (шпион на публичный метод/секции, ожидание всех загрузок), при необходимости — драйвер «создать через поппап» (клик «Создать нового» в секции диалога события/карточки → заполнение полей → save). Проверка: весь существующий E2E-набор (`tests/ui/test_e2e_*`) зелёный.
- [x] 4.2 E2E: событие → «Создать нового» (персонажи) → save поппапа → save события → `query_db`: персонаж записан и связан с событием. Проверка: тест зелёный (сценарии «Создание персонажа из диалога события», «Сохранение события фиксирует созданную сущность»).
- [x] 4.3 E2E: в поппапе создания персонажа привязать существующую локацию → save поппапа → save события → `query_db`: у нового персонажа связь с локацией. Проверка: тест зелёный («Привязка локации к новому персонажу»).
- [x] 4.4 E2E: создание сущности в поппапе, затем отмена диалога события → `query_db`: сущности и связей нет (проверка до любого другого commit). Проверка: тест зелёный («Отмена диалога родителя»).
- [x] 4.5 E2E: создать сущность в поппапе, «Отвязать», сохранить событие → `query_db`: сущность существует, с событием не связана. Проверка: тест зелёный («Отвязание не удаляет сущность»).
- [x] 4.6 E2E: суб-поток карточки — создание сущности из карточки с привязкой существующей → save карточки → `query_db`: связи новой сущности применены; поправить `test_create_related_entity_from_card` под наполненное «Привязать существующего». Проверка: тест зелёный.
- [x] 4.7 E2E: редактирование события — секция содержит ранее связанные и созданные в поппапе сущности, одна ранее связанная отвязана → save → `query_db`: связаны только присутствующие в списке. Проверка: тест зелёный («Смешанный состав секций»).

## 5. Финальная верификация

- [x] 5.1 `QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v --cov=app --cov-report=term-missing` — все тесты зелёные, строковое покрытие `app/` 100% (гейт `fail_under = 100`).
- [x] 5.2 `ruff check app/ tests/` — без ошибок.
- [x] 5.3 Ручной GUI-прогон (дополнительно к автотестам): запуск `python -m app.main`, прогнать сценарии 4.2–4.7 глазами; зафиксировать результат.
- [x] 5.4 Коммит по формату репозитория `<TASK-KEY>: ...` (Jira-ключ — от пользователя); перед коммитом — 5.1 и 5.2.
