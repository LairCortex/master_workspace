# Tasks: nri-0011-refactor-tail

Порядок групп = порядок волн (B3 → C2 → C5 → Q14 → документация/закрытие). Каждая волна заканчивается полным зелёным прогоном `QT_QPA_PLATFORM=offscreen python -m pytest` со шлюзом покрытия 100% и закрытием статуса находки в `docs/refactoring-audit.md` коммитом волны (`NRI-0011: …`).

## 1. Волна B3 — дробление `connect()` и мост таймлайна

- [x] 1.1 В `ApplicationWiring` добавить приватный помощник таймлайна (доступ к `window.timeline_widget`, `update_events`, `set_selected`) и заменить им все 11 обращений `window.timeline_widget.*` и `scale = window.timeline_widget` внутри `connect()`; проверить, что grep `window.timeline_widget` по `app/presentation/wiring.py` находит обращения только внутри помощника, и что `tests/ui/test_e2e_wiring_gaps.py` зелёный
- [x] 1.2 Разбить тело `connect()` на приватные секции `_connect_timeline`, `_connect_xlsx_import`, `_connect_event_types`, `_connect_event_dialogs`, `_connect_entity_cards`, `_connect_search`, `_connect_snapshot` (перенос кода без изменений), `connect()` вызывает их строго в текущем линейном порядке; проверить: `connect()` ≤ 15 строк, полный зелёный прогон, публичный API `ApplicationWiring` не изменился

## 2. Волна C2 — фабрика провайдеров, `LlmStatus`, проверка соединения во вьюмоделе

- [x] 2.1 Создать `app/application/services/llm_status.py` с `LlmStatus(str, Enum)` (`NOT_CONFIGURED="not_configured"`, `READY="ready"`); удалить константы `LlmViewModel.STATUS_*`, перевести `LlmViewModel`, `event_dialog_island_view_model.py` (литералы `:147,:228` и сравнения `"ready"`) на перечисление; проверить: греп `"not_configured"`/`"ready"` по `app/**/*.py` даёт совпадения только в модуле-источнике, тесты LLM зелёные
- [x] 2.2 Собрать фабрику `LlmConfig -> BaseLlmProvider` в `Application.start()` (замыкание на общий HTTP-клиент), внедрить обязательным параметром в `LlmViewModel`; `main.py` собирает `LlmService` через ту же фабрику; удалить импорт `RemoteLlmProvider` из `llm_viewmodel.py`; обновить фикстуры/тесты, конструирующие `LlmViewModel`; проверить: полный зелёный прогон, `tests/ui/test_e2e_llm.py` зелёный
- [x] 2.3 Перенести проверку соединения: новый `async LlmViewModel.check_connection(config)` (одноразовый провайдер через фабрику, успех/отобразимая ошибка); `llm_setup_dialog._on_check` сокращается до вызова модели и показа результата с прежними текстами, импорт `RemoteLlmProvider` и параметр `http` из диалога удаляются; проверить: тесты диалога настройки зелёные, поведение «Проверить соединение» для пользователя не изменилось
- [x] 2.4 Добавить в `tests/test_architecture_layers.py` правила R5 (нет импорта `RemoteLlmProvider` в `app/presentation/**`) и R6 (нет литералов `"not_configured"`/`"ready"` в `app/` вне модуля-источника) с тестом-самопроверкой на подложном нарушителе; проверить: новый тест падает на искусственном нарушении и зелёный на кодовой базе

## 3. Волна C5 — примесь `AiStateHolder`

- [x] 3.1 Выделить `AiStateHolder` (QObject-примесь: `_ai_state`, `_status`, `_has_world_prompt`, `aiState = Property(str, ...)`, обновление состояния) и подключить её в `AiFieldProxy` и `EntityGenerateProxy`, оставив каждому своё правило активности; значения `active`/`disabled`, имена сигналов, пути QML и `ai_state_is()` не меняются; проверить: греп задвоенного объявления `aiState = Property` даёт ровно одно определение, `tests/presentation/test_dialogs.py` и `tests/ui/test_e2e_llm.py` зелёные, QML-файлы не изменены (git diff пуст по `app/presentation/qml/`)

## 4. Волна Q14 — управляемые задачи и приём картинок в единице работы

- [x] 4.1 В `fill_dialog` и `editor_dialog` добавить параметр `uow: GameSessionUoW | None` (default `None`), передавать `self._uow` из `app/main.py`; приём картинки (`_store_and_set_image` → `store(...)`) выполняется в `async with uow.transaction()` при непустом `uow`; проверить: новый юнит-тест подтверждает коммит строки `ImageModel` сразу после приёма и откат при падении приёма, существующие тесты листов зелёные
- [x] 4.2 Заменить сырые `asyncio.ensure_future` этих диалогов (сохранение, экспорт PDF, приём картинки, привязка/отвязка персонажа) на управляемый `_run_task`: диалог хранит задачи, отменяет их при закрытии, ошибку из задачи показывает видимым сообщением; проверить: юнит-тест отмены незавершённой задачи при закрытии и тест видимости ошибки, полный зелёный прогон

## 5. Закрытие заявки

- [x] 5.1 Обновить таблицу статусов `docs/refactoring-audit.md` (B3/C6 → закрыты волной 1, C2 → волной 2, C5 → волной 3, Q14-остаток → волной 4 с явной фиксацией самоизлечения сирот картинок через `startup_gc`); проверить: в таблице не осталось строк ⚠️/⏳, кроме строки «Флак среды»
- [x] 5.2 Запись в `docs/CHANGELOG.md` по заявке, синк дельты `architecture-integrity` в основной спек (`openspec archive`), финальный полный зелёный прогон; проверить: `openspec validate --all` зелёный, `pytest` зелёный со 100% покрытия
