## Context

См. proposal.md — Why. Текущее состояние кода:

- `EventDialog` (`app/presentation/views/event_dialog.py`): 4 таба `_EntityTabWidget` — инлайн-форма создания (название/характеристики/предыстория/даты/тип-специфичные поля) + «Привязать существующего» + «Добавить»/«Удалить». `get_data()` отдаёт dicts: либо `_existing_id`, либо kwargs создания. `EventService._process_items` при сохранении события создаёт сущности из dicts и синхронизирует M2M.
- `EntityCardDialog` (`app/presentation/views/entity_card_dialog.py`): приватный `_RelatedSection` (список + «Привязать существующего»/«Создать нового»/«Отвязать»), сигнал `create_related_requested(attr, entity_type)`; по нему `ApplicationWiring` открывает суб-`EntityCardDialog` (parent — карточка), по его сохранению — `create_entity()` + `session.flush()` без commit + добавление в секцию родителя. Суб-окно не наполняется доступными сущностями, `related_changes` в нём отбрасываются.
- Общий app-сессии: один `AsyncSession` на игру (`expire_on_commit=False`), commit только на действиях; E2E-харнесс `tests/ui/` гоняет полные пользовательские пути через wiring (фикстуры `app`, `wait_for`, `query_db`).
- CI-ограничение: 100% строкового покрытия `app/` (`fail_under = 100` в pyproject, run 1 в CI) — все новые строки должны выполняться тестами.

Ключевые ограничения: сервисы и их API не меняются (решение grilling-сессии); поведение при отмене родителя переносится «как есть» (flush без commit).

## Goals / Non-Goals

**Goals:**
- Единый виджет секции связанных сущностей в `EventDialog` и `EntityCardDialog`.
- «Создать нового» из диалога события открывает отдельное окно; поппап наполняется доступными сущностями и применяет их связи к созданной сущности.
- Суб-поток карточки сущности приводится к тому же уровню; общий glue-хелпер для обоих потоков.
- Сохранение события по контракту сервиса не меняется (dicts `{"_existing_id": id}`); 100% строковое покрытие сохраняется.

**Non-Goals:**
- Standalone-создание сущности по «+» в таймлайне (`on_add_entity`): его related-секции по-прежнему без наполнения, `related_changes` отбрасываются.
- Изменения `EventService` / `EntityService`, схемы БД, XLSX-импорта, DetailPanel.
- Валидация полей в поппапе создания (сохранить можно с пустым названием — унаследованное поведение), смена заголовка поппапа.
- Устранение quirk «pending-строка при отмене» (см. Risks).

## Decisions

### D1. Общий модуль виджета: `app/presentation/views/related_section.py`, публичное `RelatedSection`

`_RelatedSection` переезжает в новый модуль и переименовывается (сбрасывается underscore). Оба диалога импортируют его.
Альтернативы: импорт приватного класса из `entity_card_dialog` (прецедент `_RELATED_CONFIG` есть, но приватные имена чужих модулей как общий UI — смелее); дублирование виджета (расхождение в будущем). Выбран переезд: один источник истины, минимальный рефакторинг.

### D2. Единый публичный API обоих диалогов для wiring

`EventDialog` получает такие же методы, что и `EntityCardDialog`: `set_available_entities(attr, entities)`, `add_related_entity(attr, entity)`, `create_related_requested = Signal(str, str)` (attr, entity_type). `populate(event)` заполняет секции `set_entities(...)`. Атрибуты `org_tab`/`char_tab`/`item_tab`/`loc_tab` (инстансы `RelatedSection`) сохраняются — на них ссылаются тесты.
Почему: wiring обращается к обоим диалогам единообразно; хелпер суб-окна получает «родитель» любого из двух типов без разбавления.

### D3. Контракт `EventDialog.get_data()` не меняется

`organizations/characters/items/locations` → списки `{"_existing_id": id}` (маппинг из `get_current_ids()` секций). `EventService.apply_event_relations`/`_process_items` не тронуты; их create-ветка (создание из dict без `_existing_id`) из UI уже не вызывается, но остаётся в API сервиса (покрывается существующими тестами).
Альтернатива, отклонена в grilling: смена контракта на id-списки и вырезание create-ветки — расширяет scope на сервис и его тесты.

### D4. Общий glue-хелпер суб-окна в `ApplicationWiring`

Один async-хелпер (например `_open_related_create_dialog(parent_dialog, attr_name, entity_type)`) используется и из обработчика карточки (заменяет текущий `on_create_related`), и из обоих обработчиков события (`on_add_event` / `on_edit_event`, подключённых к `EventDialog.create_related_requested`). Логика хелпера:

1. `sub_dialog = EntityCardDialog(None, entity_type=entity_type, parent=parent_dialog)`; `app._wire_mentions_for_dialog` / `app._wire_ai_buttons`.
2. Наполнение: для каждого cfg из `_RELATED_CONFIG[entity_type]` — `await rel_svc.get_all()` → `sub_dialog.set_available_entities(cfg["attr"], list)` (тот же цикл, что при открытии карточки-родителя).
3. По `sub_dialog.saved`: `sub_svc.create_entity(**sub_data)` → `await session.flush()` (без commit) → для каждого attr из `sub_data["related_changes"]`: `sub_svc.sync_related(new_entity, attr, set(ids))` → `parent_dialog.add_related_entity(attr_name, new_entity)`.
4. `create_related_requested` суб-диалога НЕ подключается — «Создать нового» внутри поппапа остаётся no-op (как сейчас в карточках; глубина вложенности = 1).

Почему `sync_related` (а не новый сервисный метод): примитив уже существует, тестируется и работает на общем session — identity-map гарантирует отсутствие дублей при последующей синхронизации события (`_process_items` → `get_entity` вернёт тот же инстанс).

### D5. Поправка к протоколу grilling (Q8-A): E2E-тесты обязательны, а не «ручный прогон»

CI гейтит 100% строкового покрытия `app/`: «верификация wiring ручным GUI-прогоном» (Q8-A) невозможна без тестового покрытия новых строк `wiring.py`. Существующий E2E-харнесс `tests/ui/` — устоявший способ покрытия glue-слоя (пример: `test_create_related_entity_from_card`). Новые wiring-пути закрываются E2E-сценариями (см. tasks); ручной прогон — только дополнение.

### D6. Deterministic ожидание в E2E

`helpers.watch_available_entity_load` шпионит за `set_available_entities` табов (fire-and-forget загрузка конкурентит с общим session). Под новый attr-API шпион устанавливается через публичный метод диалога (`dialog.set_available_entities`) либо через секции — решается при реализации; семантика «дождаться, пока все 4/3 загрузки завершились» сохраняется.

## Risks / Trade-offs

- [Quirk: при отмене родителя pending-строки созданных сущностей остаются в общем session и могут уехать в БД при любом следующем commit (напр., сохранение настроек LLM)] → наследуемое поведение карточек; фиксируется как известное ограничение, устранение (явный rollback созданных id при reject) — отдельное изменение. В E2E-сценарии «отмена» БД проверяется до любого другого commit.
- [Dead code: create-ветка `_process_items` (dict без `_existing_id`) из UI больше не вызывается] → оставляется ради стабильности сервисного API и покрытия его тестами; вырезание — кандидатура отдельного изменения.
- [Поппап без валидации (пустое название допустим) и mёртвая вложенная кнопка «Создать нового»] → унаследованные поведения карточек; согласовано в grilling (не расширяем scope).
- [Изменение `EventDialog` API ломает существующие тесты и `helpers` → регресс в E2E-наборе] → все E2E-тесты должны остаться зелёными; обновление `TestEventDialogEditMode`, `test_dialogs.py` и `helpers.py` — часть изменения.

## Migration Plan

Схема БД и данные не затрагиваются. Изменение — один коммит (формат `<TASK-KEY>: add ...`); откат — `git revert`. Версионирование релиза за этим изменением не закреплено.

## Open Questions

Нет — все решения зафиксированы в grilling-протоколе (A1–A9).
