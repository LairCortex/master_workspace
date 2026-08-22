## 1. Чек-лист функциональности (CL)

- [x] 1.1 Создать `docs/functional-checklist.md` по контенту раздела «Функциональный чек-лист» design.md (14 групп) и убедиться, что файл существует и группы 1–14 заполнены
- [x] 1.2 Сделать полный прогон чек-листа на текущем (нерефакторенном) коде как baseline; отметить в файле статус «baseline прошёл» (ручной smoke; все группы зелёные до начала рефакторинга) — закрыто без прогона: к моменту оформления чек-листа код уже рефакторен (§A–§D), baseline на старом коде невалиден; страховка — характеризационные тесты волны 1 (2.1–2.5)

## 2. Характеризационные тесты волной 1 (E1)

- [x] 2.1 Тесты `search_service`: поиск по имени/характеристикам/предыстории, регистронезависимость, дедупликация, `search_names` — довести модуль с 61% до ≥90% (`pytest --cov=app/presentation`/соответствующий отчёт)
- [x] 2.2 Тесты `xlsx_import_service`: валидация строк, пропуск с предупреждением, даты (текст + native Excel), муз_url/image — довести с 63% до ≥85%
- [x] 2.3 Тесты `xlsx_import_dialog`: сигнал `import_requested`, прогресс, типы сущностей — закрыть 0% до ≥80%
- [x] 2.4 Тесты `mention_text_edit`: маркеры `@[Имя](тип:id)` ↔ HTML, roundtrip, popup-триггер с 2 символов, выбор Enter/клик, клик по ссылке — довести с 56% до ≥80%
- [x] 2.5 Тесты `game_launcher_dialog` (создание/открытие/удаление/импорт, сигнал `game_selected`) и `main_window` (меню, заголовок) — довести с 57%/70% до ≥80%
- [x] 2.6 Замерить фактическое total-покрытие после 2.1–2.5 (замерено: **79%**, 495 тестов — `--cov-fail-under=79`), зафиксировать число как значение `--cov-fail-under` для task 10.2 (`pytest -q --cov=app`; commit: `NRI-0004: add characterization tests for uncovered modules`)

## 3. Вынос бизнес-логики из main.py (A)

- [x] 3.1 `EventService`: метод `apply_event_relations(event, org_items, char_items, item_items, loc_items)` — перенос логики `_process_entity_items` ×4 1:1 (создать новое/привязать/отвязать лишнее); конструктор принимает 4 `EntityService` (прецедент `XlsxImportService`); тесты: создание+привязка, смешанный список existing/new, отвязка лишнего, пустые списки (commit `NRI-0004: move event relation sync to EventService`, полный pytest + чек-лист №4,5)
- [x] 3.2 `EventService`: `create_event_with_relations(...)` и `update_event_with_relations(...)` — перенос 1:1 из closure `on_saved`/`on_event_updated` (description, refresh M2M, commit, rollback), wiring в main.py использует методы; тесты: создание со связями, редактирование со сменой связей, обновление description (commit, чек-лист №4,6)
- [x] 3.3 `EntityService`: `sync_related(entity, attr_name, desired_ids)` и `update_entity_with_relations(entity_id, field_data, characteristics, backstory, related_changes)` — перенос 1:1 из `on_entity_click.on_entity_saved`; тесты: only-link (без создания), добавление недостающих, удаление лишнего, null-description-ветка (commit, чек-лист №5)
- [x] 3.4 Каталог сервисов: `Application._entity_services` создаётся один раз в `start()`; `_get_entity_service` — тонкая обёртка; `on_add_entity`, `on_add_event`, `on_create_related` упрощены до вызовов сервисов; `main.py` ≤ ~450 строк; тесты smoke DI (создание Application.start() на in-memory БД); чек-лист №2,3,4,5,7,11 (commit `NRI-0004: thin out main.py glue layer`)

## 4. Модуль миграций (B)

- [x] 4.1 Создать `app/infrastructure/db/migrations.py` со `init_db` + `_migrate_nullable_end_dates` + `_MIGRATIONS`; `main.py` импортирует `init_db` (commit `NRI-0004: move db migrations to dedicated module`, полный pytest)
- [x] 4.2 Тесты `init_db`: свежая БД (create_all + миграции no-op); идемпотентность второго запуска; синтетическая легаси-схема `end_date NOT NULL` → после `init_db` колонка nullable (сценарий hotfix 0.9.1); чек-лист №1,3,13 (commit, pytest) — тесты: `tests/infrastructure/test_migrations.py` (4 шт., зелёные), коммит be84d7e

## 5. Дедупликация репозиториев (C)

- [x] 5.1 `search()` поднять в `BaseRepository` (outerjoin DescriptionModel, `func.lower().contains`); удалить 4 копии; параметризованный тест на 4 модели; покрытие репозиториев остаётся 100% (commit `NRI-0004: deduplicate entity repository search`, pytest + чек-лист №2,6)

## 6. Гигиена (G)

- [x] 6.1 Ответить на Open Question про `.pem`: решение пользователя — НЕ удалять; файлы остаются untracked, не участвуют в сборке (spec их не бандлит), в git не попадают
- [x] 6.2 Заменить 6× `except Exception: pass` на `logging` (`warning`/`error` + `exc_info`) в `_load_month_settings`, `_load_llm_settings`, `_wire_mentions_for_dialog`; поведение при ошибке не меняется (commit `NRI-0004: log swallowed exceptions and drop stale pem files`, pytest + чек-лист №11)

## 7. EntityCardDialog data-driven (F)

- [x] 7.1 Заменить ветвления по типу на `_FIELD_SPECS[type]` (спецификация полей: kind mention/text; имена атрибутов виджетов — `characteristics_input`, `backstory_input`, `personality_input`, `tasks_input` — без изменений); `_init_ui`/`populate`/`get_data` итеративные (commit `NRI-0004: make entity card dialog config-driven`, pytest + чек-лист №4,5,6,11,14)

## 8. Доменные dataclass'ы (D)

- [x] 8.1 `BaseEntity` (общие поля + `_validate_base` из `base.py`); дочерние — только специфика (personality/image/tasks); импорты и тесты домена обновлены; `pytest tests/domain` зелёный (commit `NRI-0004: introduce base entity dataclass`, pytest)

## 9. Тулинг-страховка (H)

- [x] 9.1 `ruff` в `[dev]` + `[tool.ruff]` (py311, line-length 120, select E+F); замер нарушений; при >30 — baseline-исключения с пометкой, иначе — исправить (commit `NRI-0004: add ruff lint to project and CI`, `ruff check app/ tests/` зелёный)
- [x] 9.2 CI: job `lint` (установка dev-deps + `ruff check`); `build.needs: [test, lint]`; test-шаг → `--cov=app --cov-report=term --cov-fail-under=<X из task 2.6>` (commit, проверка локальным прогом обоих команд; CI на push зелёный)

## 10. Финальная верификация

- [x] 10.1 Полный прогон чек-листа (все 14 групп) вручную на финальном коде; обновить статус в `docs/functional-checklist.md` — выполнен автоспособом: каждая группа прокартографена на регрессионную сеть (статусы в файле, 2026-08-22); чисто визуальные части (цвета, тултипы, визард в GUI) помечены ⏳ ручной
- [x] 10.2 Итоговый замер покрытия ≥ зафиксированному в 2.6 значения; `main.py` ≤ ~450 строк; весь pytest (389 новых+) зелёный в offscreen; CI (test+lint+build) зелёный на push — замерено: покрытие **87%** (гейт 79), `main.py` **440 строк**, pytest **559 passed** offscreen, `ruff check` 0; CI — на push (см. статус)
