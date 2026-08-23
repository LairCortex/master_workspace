## Why

Тестовый слой приложения не покрывает два критических участка: (1) слой запуска и связывания — `Application.start()` (55%) и `ApplicationWiring` (24%) защищены только двумя smoke-тестами, а `app_state.py` не покрыт вовсе; (2) интерактивные views (таймлайн 76%, dialog события 76%, detail panel 79%, карточка сущности 81%) покрыты фрагментарно. Системного UI-тестирования нет: ни одного E2E-сценария полного потока пользователя, LLM в UI-сценариях невозможно проверить детерминированно. Гейт CI держится на 79% (только строки, без веток). Цель: 100% покрытие по строкам всего `app/` и устойчивая двухслойная система UI-тестов.

## What Changes

- **Новая двухслойная UI-тестовая система на pytest-qt** (зависимость уже в dev-extra, `qt_api = "pyside6"` уже в pyproject):
  - **Системные E2E-тесты** (`tests/ui/`) — полный старт `Application` на реальной временной БД. 10 сценариев: создание игры в лаунчере, открытие существующей, CRUD ×4 типа сущностей (контекстное меню таймлайна → карточка → удаление), событие + детальная панель, case-insensitive поиск, LLM-визард («Проверить соединение» + AI-генерация), импорт .xlsx, кастомные месяцы, экспорт `.nri`, переключение игры
  - **Widget-тесты** (расширение `tests/presentation/`) — по основным дырам: `timeline_widget`, `event_dialog`, `detail_panel`, `entity_card_dialog`, `custom_date_edit`, `mention_text_edit`, `world_snapshot_widget`, `ai_assist_button`, `app_state`
- **Покрытие до 100% по строкам** всего пакета `app/`; ветки (`--cov-branch`) измеряются и показываются в репорте, гейтом не используются
- **DI-шов**: `Application.__init__(qapp, http: AppHttpClient | None = None)` — инъекция приложения целиком в тест с клиентом на `httpx.MockTransport`; реальная сеть в UI-тестах исключена
- **Изоляция данных** E2E: реальный временный `.db`-файл, игры — во временной каталог (monkeypatch `get_games_dir` → `tmp_path`), конфиг LLM — во временный файл (monkeypatch константы `CONFIG_FILE`); файловые диалоги (открыть/экспортировать) — stub
- **CI**: coverage-конфигурация переезжает в `pyproject.toml`; два прогона — строки с гейтом `fail_under = 100` и ветки только репортом (гейт отключён через `--cov-fail-under=0`); гейт поднимается скачками 79 → 95 (PR1) → 100 (PR2); триггеры CI не меняются (push/таг/workflow_dispatch, без pull_request)
- **Исключения из покрытия**: `exclude_lines` для `if __name__ == "__main__":` гарда; `# pragma: no cover` — не более 2 шт., каждая с обязательным обоснованием в inline-комментарии
- **Релиз**: PR1 без бампа версии; PR2 — версия **0.13.1** синхронно в трёх местах (`pyproject.toml`, `CFBundleShortVersionString` в `nri_manager.spec`, `docs/CHANGELOG.md`) с секцией «Инфраструктура/Тесты»

## Capabilities

### New Capabilities

- `ui-testing`: система UI-тестирования проекта — E2E-сценарии полного запуска приложения по основным пользовательским потокам, widget-слой интерактивных views, детерминированная изоляция данных и сети, и гейт 100%-покрытия строк в CI.

### Modified Capabilities

<!-- Нет: требования llm-remote-provider / llm-configuration не меняются (DI-шов не изменяет их поведение). -->

## Impact

- **Код приложения:** только `app/main.py` — опциональный параметр `http` в `Application.__init__` (иначе создаётся `AppHttpClient()` как сейчас) и его использование в `start()`. Прочий прода-код не меняется.
- **Тесты:** новый каталог `tests/ui/` (E2E + боот-фикстуры + переезд `tests/test_application_start.py`), расширение файлов `tests/presentation/*`, новый fixture-файл `.xlsx` в тестах, мелкие дополнения юнитов под 100% (frozen-ветки `game_manager` и др.)
- **Конфигурация:** `pyproject.toml` (`[tool.coverage.run]`, `[tool.coverage.report]`), `.github/workflows/build.yml` (два coverage-прогона, гейт скачками)
- **Версии/доки (PR2):** `pyproject.toml`, `nri_manager.spec`, `docs/CHANGELOG.md` → 0.13.1
- **Зависимости:** новых нет (pytest-qt, pytest-cov уже в `[dev]`)
- **Коммиты:** два PR — PR1 «UI test system» (фикстура + E2E + widget-тесты + CI-конфиг), PR2 «100% coverage + 0.13.1». Запланированный task-ключ: `NRI-0005`.
