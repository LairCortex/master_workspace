## 1. Удаление локального GGUF (коммит `NRI-0003: remove local GGUF LLM and model download`)

- [x] 1.1 Удалить `tests/infrastructure/test_model_manager.py` и download/delete-тесты из `tests/presentation/test_llm_viewmodel.py`, `tests/presentation/test_llm_setup_dialog.py`, `tests/presentation/test_ai_assist_button.py`; прогон `python -m pytest` подтверждает ожидаемые падения (красный старт TDD)
- [x] 1.2 Удалить `app/infrastructure/llm/local_provider.py` и `app/infrastructure/llm/model_manager.py`; сузить `BaseLlmProvider` до `async generate(...)` + `async close()`; проверить, что `python -m pytest` собирает тесты без ImportError
- [x] 1.3 Удалить extra `[llm]` из `pyproject.toml`; проверить `python -m pip install -e .` и отсутствие `llama-cpp-python`/`huggingface-hub` в зависимостях
- [x] 1.4 Ввести минимальный `RemoteLlmProvider` (чтение конфига `~/.nri_manager/llm_config.json`, статус `not_configured`/`ready` по непустым `base_url`+`model`, `generate()` с ошибкой «LLM не настроен» при отсутствии конфига) и подключить его в `Application` взамен `LocalGgufProvider`; приложение запускается, AI-кнопки неактивны; `python -m app.main` открывается без ошибок
- [x] 1.5 Вычистить из `LlmViewModel`/`LlmSetupDialog`/`main.py` весь download/load/delete-механизм (кнопки, `QProgressBar`, download-сигналы, `_do_llm_download`, `_on_cancel_llm_download`, `_llm_downloading`, `STATUS_DOWNLOADING`/`STATUS_LOADING`, статусная логика по model_path); страница модели в диалоге временно — заглушка «подключение настраивается в этом диалоге»; `python -m pytest` зелёный
- [x] 1.6 Гейт коммита 1: `python -m pytest` зелёный, `git grep -i "llama\|gguf\|huggingface\|model_manager"` в `app/` пуст; закоммитить `NRI-0003: remove local GGUF LLM and model download`

## 2. Remote-провайдер и подключение (коммит `NRI-0003: add OpenAI-compatible remote LLM provider`)

- [x] 2.1 TDD: `LlmConfig` (dataclass: `base_url`, `model`, `api_key` опционально) + менеджер конфига: чтение/запись `~/.nri_manager/llm_config.json`, `chmod 0600`, валидность старого формата (`repo`/`filename`) = «конфиг отсутствует»; тесты `tests/infrastructure/test_llm_config.py` (создание, права, опциональный ключ, старый формат, отсутствие файла) зелёные
- [x] 2.2 TDD: `app/infrastructure/http/` — единственный `httpx.AsyncClient` приложения (таймауты const: connect 10 s, read 120 s), функции создания на старте и закрытия в `shutdown()`; тесты жизненного цикла (без сети)
- [x] 2.3 TDD: иерархия ошибок `LlmError → LlmHttpError(status, server_message)` / `LlmNetworkError` / `LlmTimeoutError` + маппинг статусов в русские сообщения (401/403, 404, 429, прочее), парсинг тела `{"error": {"message": ...}}` с фолбэком; тесты маппинга
- [x] 2.4 TDD: реализовать в `RemoteLlmProvider` запрос `POST {base_url}/chat/completions` (Bearer-заголовок только при непустом ключе, `max_tokens`/`temperature` из констант), ретраи: до 2 с backoff на таймаут/сбой соединения/429/5xx, без ретрая на прочие 4xx; тесты через `httpx.MockTransport`: успех, пустой ключ, 401 без повтора, 503→200, 429, таймаут, сеть недоступна, пустой `choices`; `python -m pytest tests/infrastructure` зелёное
- [x] 2.5 Проверить, что `LlmService` (очередь, сборка промтов) без изменений: существующие тесты `tests/application/test_llm_service.py` проходят без правок
- [x] 2.6 TDD: `LlmViewModel` — статусы только `not_configured`/`ready` (`ready` = непустые `base_url`+`model`, без сети), method применения нового конфига (пересоздание провайдера), `is_generation_available()`; переписать `tests/presentation/test_llm_viewmodel.py`
- [x] 2.7 TDD: страница подключения в `LlmSetupDialog`: поля endpoint/model + маскируемый ключ + кнопка «Проверить соединение» (тестовый запрос `max_tokens=1`, label результата, блокировка кнопки на время проверки), сохранение недоступно при пустых endpoint/model, обновлённый текст warnings; переписать `tests/presentation/test_llm_setup_dialog.py`
- [x] 2.8 TDD: `AiAssistButton` — статусы `not_configured`/`ready`, тексты подсказок («настройте LLM в меню LLM → Настройка LLM…»); обновить `tests/presentation/test_ai_assist_button.py`
- [x] 2.9 `app/main.py`: DI http-клиента и `RemoteLlmProvider` в `Application` (создание при старте, `close()` в `shutdown()`), сохранение конфига по `dialog.saved` (конфиг + world/field промоуты), загрузка конфига при старте; `python -m pytest` полностью зелёное
- [x] 2.10 `pyproject.toml`: `httpx` в base dependencies; `pip install -e .` проходит, `python -m pytest` зелёное
- [x] 2.11 Гейт коммита 2: полный `python -m pytest` зелёный, мёртвого кода от локальной модели нет (`git grep -i "llama\|gguf\|huggingface\|download_model"` в `app/` пуст); закоммитить `NRI-0003: add OpenAI-compatible remote LLM provider`

## 3. Документация и версии (коммит `NRI-0003: update docs for remote LLM setup`)

- [x] 3.1 `docs/README.md`: переписать раздел «AI-ассистент (LLM)» — настройка endpoint/model/ключ (примеры: OpenAI, Ollama, vLLM/LM Studio), убрать шаги скачивания модели и `[llm]` extra; таблица зависимостей — `httpx`
- [x] 3.2 `AGENTS.md`: обновить блок «LLM» (внешняя OpenAI-совместимая LLM, общий http-слой, конфиг 0600) и оговорку про LLM extras
- [x] 3.3 Версия 0.1.0 → 0.1.1 синхронно в трёх местах: `pyproject.toml`, `CFBundleShortVersionString` в `nri_manager.spec`, `docs/CHANGELOG.md` (запись: **BREAKING** удаление локальной LLM + remote-подключение); проверить согласованность `grep 0.1`
- [x] 3.4 Гейт коммита 3: `python -m pytest` зелёное; закоммитить `NRI-0003: update docs for remote LLM setup`

## 4. Финальная проверка

- [x] 4.1 Полный прогон `python -m pytest` (и `QT_QPA_PLATFORM=offscreen python -m pytest` как в CI) — все тесты зелёные
- [x] 4.2 Смоук-ручной: `python -m app.main` — лаунчер, окно, меню LLM → диалог с формой подключения; пустые endpoint/model блокируют сохранение; неверный ключ при «Проверить» показывает ошибку 401
- [x] 4.3 `openspec validate --change remote-llm-provider` — валидно; статус change завершён

## 5. Follow-up по решению пользователя (2026-08-22)

- [x] 5.1 Версия поднята до **0.13.0** (продолжение линии от 0.12.0, а не 0.1.1) синхронно в трёх местах: `pyproject.toml`, `CFBundleShortVersionString` в `nri_manager.spec`, `docs/CHANGELOG.md`
- [x] 5.2 Гонка сохранения/закрытия приложения закрыта: диалог не закрывается до завершения async-записи, кнопка «Сохранить» не дизейблится, повторный клик игнорируется, `reject()`/`closeEvent` блокируются во время записи; диалог принимает себя в `finish_saving(True)`; при `shutdown()` во время записи глобальный конфиг сохраняется, запись per-game промтов пропускается, исключений нет. Тесты: `test_dialog_not_accepted_until_save_finished`, `test_save_reentry_ignored_while_saving`, `test_reject_blocked_while_saving`, `test_close_and_reject_blocked_while_saving`, `test_finish_saving_failure_shows_warning_and_keeps_open`; смоки: race (save → immediate shutdown), flow (401 → ok → save → авто-accept), roundtrip (сохранение → рестарт → промты восстановлены → живой generate)
