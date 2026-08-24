## Context

См. proposal.md → Why. Текущее состояние, влияющее на подход:

- Слой LLM: `BaseLlmProvider` (ABC: `generate`, `is_ready`, `load_model`, `unload_model`) → `LocalGgufProvider` (llama-cpp-python) → `LlmService` (очередь + сборка промтов, provider через setter) → `LlmViewModel` (статусы `not_installed/downloading/loading/ready`, download/load/delete модели, per-game промоуты мира/полей) → `LlmSetupDialog` (8 страниц) + `AiAssistButton`.
- `ModelManager` — самый хрупкий узел: pip-установка в venv рядом с приложением, `_get_python_executable` с преференциями Homebrew, `sys.path`-хаки, скачивание 8.5 ГБ с HuggingFace.
- Приложение крутится на Qt event loop через qasync: любой сетевой код обязан быть async — синхронные блокирующие вызовы замораживают UI.
- Per-game настройки (world/field promos) — в `game_settings` (остаются без изменений).
- Git: 11 LLM-коммитов, 10 из них уже в origin/main; в диапазоне есть два немодельных коммита (`fe7a094` codesign, `54a92ad` logging toggle).
- CI строит 3 ОС; PyInstaller spec (`nri_manager.spec`) — directory bundle.

## Goals / Non-Goals

**Goals:**
- Внешняя LLM через OpenAI-совместимый endpoint (облачные + локальные серверы) без установки зависимостей и без загрузки моделей.
- Один общий async HTTP-транспорт приложения для LLM и будущих сетевых фич.
- Полное удаление локального GGUF-механизма без мёртвого кода.
- TDD: provider и HTTP-слой тестируются без сети.

**Non-Goals:**
- Мультипровайдерная абстракция (отдельные классы под OpenAI/Anthropic/Gemini).
- Streaming-генерация (UI потребляет только готовый текст; очередь остаётся).
- UI для параметров генерации (temperature, max_tokens) — константы.
- Профили подключений (несколько LLM одновременно) — одна конфигурация.
- Шифрование ключа, keyring/OS-хранилища.
- Переписывание git-истории и миграция пользовательских данных (app не разошёлся).

## Decisions

**D1. Только OpenAI-совместимый протокол, один провайдер.**
`RemoteLlmProvider` обращается к `POST {base_url}/chat/completions` с заголовком `Authorization: Bearer {key}` (если ключ задан). Пользователь вводит `base_url` до `/v1` включительно (OpenAI `https://api.openai.com/v1`, Ollama `http://localhost:11434/v1`, vLLM `http://host:8000/v1`, LM Studio `http://localhost:1234/v1`). Это эталонный паттерн openai-python SDK, покрывает все целевые бэкенды одним классом. Альтернативы: (a) отдельные провайдеры под API каждого вендора — неоправданное усложнение, каждый из них всё равно упирается в OpenAI-совместимые серверы; (b) SDK `openai` как зависимость — тянет за собой весь клиент и версии, ради одного endpoint избыточно; паттерны SDK (base_url, ретраи, таймауты) воспроизведены вручную (~60 строк).

**D2. httpx как base-зависимость; общий `AsyncClient` в инфраструктуре.**
Новый модуль `app/infrastructure/http/`: фабрика/реестр одного `httpx.AsyncClient` (дефолтные таймауты: connect 10 s, read 120 s — константы) с жизненным циклом «создан на старте приложения (в `Application`), закрыт в `shutdown()`». LLM-модуль получает клиент через DI. Альтернативы: (a) `requests` + `asyncio.to_thread` — блокирующее ядро требует воркер-потоки на каждый запрос, `requests.Session` не потокобезопасна, общий слой расширяется потоковой синхронизацией; (b) клиент внутри провайдера — будущие фичи плодили бы отдельные клиенты без пула соединений.

**D3. Глобальный конфиг-файл с правами 0600, без OS-зависимостей.**
`~/.nri_manager/llm_config.json` (локация уже используется приложением), JSON `{base_url, model, api_key}`; `api_key` опционален (`""` = без авторизации, локальные серверы). `os.chmod(0o600)` при записи (на Windows — no-op, не ошибка). Альтернативы: (a) python-keyring — «золотой стандарт», но бэкенд Linux требует системные пакеты (`dbus-python`/`secretstorage`, часто не ставятся через pip), в headless Linux тихо деградирует в null-keyring, в PyInstaller-сборке бэкенды не гарантированы; (b) per-game `game_settings` — подключение это инфраструктура приложения, а не свойство игры (world/prompts остаются per-game).

**D4. Сужение ABC: `generate()` + `close()`.**
`load_model`/`unload_model`/`is_ready` умирают вместе с локальной моделью — для remote ничего не загружается, «готовность» определяется конфигом. Остаются: `async generate(system_prompt, user_prompt, max_tokens) -> str` и `async close()` (освобождение ресурсов клиента). `LlmService` и контракт генерации не меняются.

**D5. Статусы `not_configured` / `ready`, сеть при старте запрещена.**
`ready` ⇔ сохранены непустые `base_url` и `model`. Приложение запускается мгновенно и офлайн; «готовность» никогда не зависит от сети. Ошибки соединения поверхность: кнопка «Проверить» в диалоге и сигнал `generation_error`.

**D6. Ошибки — иерархия `LlmError` → `LlmHttpError(status, server_message)` / `LlmNetworkError` / `LlmTimeoutError`.**
Карта статусов в человекочитаемые русские сообщения (401/403 → неверный ключ/права; 404 → модель или endpoint не найдены; 429 → лимит; прочее — текст ошибки сервера + статус). Текст ошибки из тела ответа парсится по OpenAI-формату `{"error": {"message": ...}}` с фолбэком на сырой body. Поверхность: `generation_error` (существующий сигнал) и результат проверки в диалоге.

**D7. Ретраи — ручной цикл в провайдере, без новых зависимостей.**
До 2 повторов с экспоненциальным backoff (0.5 s, 1 s) только на: таймауты, ошибки соединения, HTTP 429/5xx. Прочие 4xx — немедленный `LlmHttpError`. httpx встраиваемых ретраев не имеет, `tenacity`/`urllib3.retry` не вводим ради трёх строк цикла.

**D8. UI: визард не перестраивается, заменяется страница 1.**
Страница «Модель» → «Подключение»: `QLineEdit` endpoint, `QLineEdit` model, `QLineEdit.Password` key (placeholder «необязательно для локальных серверов»), кнопка «Проверить соединение» (запрос `max_tokens=1`, результат — label c ок/ошибка). Удалены: кнопки скачать/удалить, `QProgressBar`, download-сигналы в ViewModel и `main.py`. Кнопка «Сохранить» (на последней странице) не даёт сохранить пустые endpoint/model (`saved`-сигнал не подаётся / диалог остаётся открытым с подсказкой). Тестовый запрос в диалоге идёт через тот же `AsyncClient`; `async def`-обработчик клика, во время теста кнопка заблокирована.

**D9. Коммиты — forward, без переписывания истории.**
Revert диапазона `77e1670..02fada7` невозможен: диапазон уже в origin/main, а `fe7a094` (codesign) и `54a92ad` (logging toggle) не относятся к LLM. Три коммита: (1) `NRI-0003: remove local GGUF LLM and model download`, (2) `NRI-0003: add OpenAI-compatible remote LLM provider`, (3) `NRI-0003: update docs for remote LLM setup`.

## Risks / Trade-offs

- [Несовместимость отдельных OpenAI-совместимых серверов: `max_tokens` vs `max_completion_tokens`, нестрогое поведение с `/v1` в base_url] → тестирование на референсных серверах (OpenAI, Ollama, vLLM/LM Studio); в подсказке формы явно указать формат «базовый URL до /v1»; `max_tokens` остаётся — параметр поддерживаем всеми целевыми серверами.
- [До 120 с ожидание ответа блокирует поле (read-only)] → существующий прогресс-индикатор 4px + запрет закрытия окна во время генерации; поведение не меняется по сравнению с локальной моделью.
- [Ключ в plaintext-файле] → сознательный trade-off: ключ собственного провайдера на собственной машине, 0600 + маскирование в UI; OS-keyring отклонён (D3).
- [chmod 0600 не работает на Windows] → best-effort: `os.chmod` без ошибки, правам NTFS управление не ведём.
- [httpx в base-зависимостях попадает в каждую сборку] → размер ~50 КБ вместе с зависимостями, приемлемо; PyInstaller подхватывает автоматически (spec не правится).
- [Отсутствие миграции: старый `llm_config.json` (repo/filename) у разработчиков] → приложение не разошлось; старый формат при чтении считается «конфиг отсутствует» (валидация ключей файла).

## Migration Plan

1. Коммит 1 (NRI-0003): удалить `LocalGgufProvider`, `ModelManager`, `tests/infrastructure/test_model_manager.py`, extra `[llm]` из `pyproject.toml`, download-кнопки/прогресс/обработчики в `LlmSetupDialog`, `LlmViewModel` (`download_model`, `delete_model`, download-сигналы, `STATUS_DOWNLOADING/LOADING`) и `main.py` (`_do_llm_download`, `_on_cancel_llm_download`, `set_download_progress` и т.п.), сузить ABC. Прогон `python -m pytest` зелёный.
2. Коммит 2 (NRI-0003): TDD: тесты конфига (создание/0600/опциональный ключ/валидация) → тесты `RemoteLlmProvider` через `httpx.MockTransport` (успех, ретраи, 401/404/429/таймаут, пустой ключ) → `app/infrastructure/http/` → DI в `Application` → страница подключения в диалоге + статусы ViewModel + тексты `AiAssistButton`. Прогон `python -m pytest` зелёный. Прогон детектов не требуется (не настроены) — гейт только тесты.
3. Коммит 3 (NRI-0003): `pyproject` (+`httpx`), `docs/README.md` (раздел LLM: шаги настройки подключения), `AGENTS.md` (блок «LLM»), `docs/CHANGELOG.md` (0.1.1: BREAKING removal + remote LLM).

Rollback: app не разошёлся — откатка = откат 3 коммитов (или новая сборка с `develop`-точки); пользователей без данных нет, миграция обратная не требуется.

## Open Questions

- Точный текст подсказки/placeholder для `base_url` в форме (с примерами популярных endpoint'ов) — решается при реализации UI, спецификации не затрагивает.
