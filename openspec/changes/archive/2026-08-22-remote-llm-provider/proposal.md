## Why

Сейчас AI-ассистент работает только через локальную модель: приложение должно устанавливать тяжёлые зависимости (`llama-cpp-python`, `huggingface-hub`) в отдельный venv с хаками `sys.path` и качать 8.5 ГБ GGUF-модели с HuggingFace. Это хрупко (отдельный Python, frozen-сборка PyInstaller, сетевые сбои), долго и неудобно. Пользователь, у которого уже есть доступ к LLM (OpenAI, OpenRouter, Groq, vLLM, Ollama, LM Studio, llama.cpp server), обязан тащить всё это локально. Нужно заменить механизм на подключение к внешней LLM по индпоинту + модели + ключу.

## What Changes

- **BREAKING:** Полное удаление локального GGUF-провайдера: `LocalGgufProvider`, `ModelManager` (скачивание с HuggingFace, установка пакетов, venv-логика), extra `[llm]` из `pyproject.toml`, кнопки скачивания/удаления модели и прогрессбар в диалоге настройки, download-сигналы ViewModel. Мёртвого кода от старого механизма не остаётся.
- Новый удалённый LLM-провайдер: OpenAI-совместимый `POST {base_url}/chat/completions` (покрывает OpenAI, OpenRouter, Groq, vLLM, Ollama, LM Studio, llama.cpp server).
- Глобальный конфиг подключения: `~/.nri_manager/llm_config.json` (права 0600) с полями `base_url`, `model`, `api_key` (опционально — локальные бэкенды работают без ключа). Зависимость от ОС keychain отсутствует.
- Диалог «Настройка AI-ассистента»: страница «Модель» заменяется формой подключения (endpoint / model / ключ + кнопка «Проверить соединение» с тестовым запросом `max_tokens=1`). Промты мира и полей (per-game) не меняются.
- Статусы AI-ассистента: вместо `not_installed/downloading/loading/ready` — только `not_configured/ready` (`ready` = сохранены непустые `base_url` и `model`, сеть при старте приложения не требуется).
- Обработка ошибок: собственные исключения (`LlmError → LlmHttpError / LlmNetworkError / LlmTimeoutError`) с русскими user-friendly сообщениями (401/403 → неверный ключ, 404 → модель/endpoint не найдены, 429 → лимит запросов).
- Политика запросов (эталон OpenAI SDK): 2 ретрая с экспоненциальным backoff только на timeout/connection error/429/5xx; прочие 4xx — без ретрая. Таймауты: connect 10 c, read 120 c.
- Общие HTTP-слоя на `httpx` в `app/infrastructure/`: один async-клиент приложения (пул соединений), создаётся на старте, закрывается на shutdown, доступен для будущих сетевых фич.
- `httpx` — новая base-зависимость.

## Capabilities

### New Capabilities

- `llm-remote-provider`: генерация текста через OpenAI-совместимый API, обработка ошибок и ретраи, таймауты, проверка соединения, общий HTTP-транспорт приложения.
- `llm-configuration`: глобальный конфиг подключения (endpoint/model/key, права файла, опциональный ключ), модель статусов AI-ассистента, форма подключения в диалоге настройки и её состояние кнопок AI.

### Modified Capabilities

<!-- Существующих спеков в репозитории нет (openspec/specs пуста) — нет требований к изменениям. -->

## Impact

- **Код:** `app/infrastructure/llm/` (переделка: ABC, провайдер, новый конфиг-менеджер), `app/infrastructure/http/` (новый общий httpx-клиент), `app/application/services/llm_service.py` (без изменений по API — только провайдер), `app/presentation/viewmodels/llm_viewmodel.py` (статусы, удаление download-логики), `app/presentation/views/llm_setup_dialog.py` (страница подключения + тест), `app/presentation/views/ai_assist_button.py` (статусы, тексты), `app/main.py` (DI: http-клиент, конфиг, провайдер; удаление Download/Model-хаков).
- **Зависимости:** + `httpx` (base), − `llama-cpp-python`, `huggingface-hub` (extra `[llm]` удалён), − `tqdm` (только в LLM-пакетах).
- **Тесты:** переписываются `test_llm_providers.py`, `test_llm_viewmodel.py`, `test_llm_setup_dialog.py`; добавляются тесты конфигурации и HTTP-клиента (без сети, `httpx.MockTransport`); удаляется `test_model_manager.py`.
- **Packaging/доки:** `pyproject.toml`, `docs/README.md` (раздел LLM), `AGENTS.md` (блок «LLM»), `docs/CHANGELOG.md`. `nri_manager.spec` и GitHub Actions CI не требуют изменений (httpx подхватывается автоматически).
- **Коммиты:** три forward-коммита `NRI-0003` (удаление локального GGUF → remote-провайдер → документы). История не переписывается; миграция данных пользователей не требуется (app не разошёлся).
