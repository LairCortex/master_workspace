# Tasks: add-character-sheet-d1

Делать **после** A1…C. TDD. `QT_QPA_PLATFORM=offscreen python -m pytest`. Без внешней сети (`aiohttp.TestClient`). HTTPS/mDNS/аккаунты/десктоп-клиент игрока не делать.

## 1. Зависимости и каркас сервера

- [x] 1.1 Добавить `aiohttp` и `segno` в `pyproject.toml` dependencies; `hiddenimports` в `nri_manager.spec`. Проверка: `pip install -e ".[dev]"` проходит.
- [x] 1.2 Тесты AppRunner: start/stop на TestServer; `GET /` отдаёт HTML. Проверка: `tests/infrastructure/test_table_host_http.py` красные до 1.3.
- [x] 1.3 Статика `table_host/web/` + aiohttp app (D1). Проверка: тесты 1.2 зелёные; spec `datas` содержит путь.

## 2. Сессия, посадка, join

- [x] 2.1 Тесты: старт без посадки — отказ; PIN 4 цифры, новый на рестарт; join неверный PIN; имя уникально; свободный лист ок; занятый другому имени 409; то же имя вытесняет; field commit пишет values в БД; stop режет токен. Проверка: `tests/application/test_table_host_service.py` красные до 2.2.
- [x] 2.2 `TableHostService` + join/field (D2, D3). Проверка: тесты 2.1 зелёные.
- [x] 2.3 Тесты: удаление посаженного экземпляра пока стол открыт — отказ. Проверка: сервис экземпляра дополнен, зелёный после правки delete.

## 3. Картинки и лейаут

- [x] 3.1 Тесты: multipart image → ImageStore + image_id в values; нечитаемый файл — ошибка без записи; Save шаблона шлёт layout клиенту (подписка/флаг). Проверка: красные до 3.2.
- [x] 3.2 `POST /api/image`, `broadcast_layout` (D5). Проверка: тесты 3.1 зелёные.

## 4. Веб-Fill

- [x] 4.1 Тесты раскладки: JSON поля → CSS left/top/width/height в pt; label не в списке ввода. Проверка: `tests/domain/test_sheet_html_layout.py` зелёные после 4.2.
- [x] 4.2 JS/HTML: лента страниц, ввод по типам, фиксация на blur/Enter/toggle, зум; без undo. Проверка: index отдаётся, ручной smoke не в CI; API-тесты 2.x зелёные.
- [x] 4.3 WS: kicked / stopped / value. Проверка: TestClient ws, зелёный.

## 5. UI мастера

- [x] 5.1 Тесты панели: URL IPv4+QR; порт до старта; меню «Стол»; список игроков; выгнать. Проверка: `tests/presentation/test_table_host_panel.py` красные до 5.2.
- [x] 5.2 Панель + segno (D4). Проверка: тесты 5.1 зелёные.
- [x] 5.3 Тесты: Fill read_only на столе; dirty Fill prompt при старте; смена игры зовёт stop; клик списка меняет просмотр. Проверка: красные до 5.4.
- [x] 5.4 Wiring `Application` (D5). Проверка: тесты 5.3 зелёные.

## 6. Интеграция

- [x] 6.1 E2E loopback: старт → join TestClient → field → в БД есть значение → stop. Проверка: `tests/ui/test_e2e_table_host.py` зелёный.
- [x] 6.2 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
- [x] 6.3 `docs/CHANGELOG.md` (стол, браузер LAN, незавершено пока нет… D1 *есть* поставка эпика — пометить стол как часть незавершённого, если телефон/AP ещё впереди); roadmap D1 = этот change. Проверка: `openspec validate add-character-sheet-d1 --strict` зелёный.
