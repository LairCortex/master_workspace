## Context

См. `proposal.md`. Применять после A1…C. Источник правды значений — `game.db` мастера. Веб не монтирует SQLite. Цикл — qasync (тот же, что LLM `httpx`). Спеки: `character-sheet-host`, `character-sheet-instance`, `character-sheet-editor`, `image-storage`.

aiohttp: `AppRunner` + `TCPSite` на уже бегущем loop; тесты — `aiohttp.TestClient`/`TestServer` in-process.

## Goals / Non-Goals

**Goals:**

- Сервер на loop приложения, bind `0.0.0.0`, в UI только IPv4 из локальных интерфейсов (не 127.0.0.1 как единственный, но localhost для тестов ок).
- Сессия игрока: cookie/token в памяти процесса, не таблица в БД.
- Патч значения: REST JSON `{field_id, value}` + WebSocket push мастеру и (при reload лейаута) клиенту.

**Non-Goals:**

- Reverse proxy, HTTPS, mDNS, отдельный процесс сервера.
- IndexedDB у игрока как копия игры.

## Decisions

### D1. aiohttp на qasync

`web.AppRunner(app); await runner.setup(); web.TCPSite(runner, "0.0.0.0", port); await site.start()`. Стоп: `runner.cleanup()`. Не `web.run_app` (свой loop).

Статика: `app/presentation/views/table_host/web/` (HTML/CSS/JS), раздавать как static. В `nri_manager.spec` `datas`.

Альтернатива: stdlib `asyncio.start_server` — отвергнута (multipart, WS, static). Uvicorn/FastAPI — второй loop.

### D2. Протокол

| путь | роль |
|---|---|
| `GET /` | лендинг: PIN, имя, список свободных (после PIN) |
| `POST /api/join` | PIN+имя+instance_id → token |
| `GET /api/sheet` | лейаут+значения (Bearer/token) |
| `POST /api/field` | коммит поля; 409 если вытеснен |
| `POST /api/image` | multipart → ImageStore |
| `GET /api/image/{id}` | preview, только для своей сессии / публично с token |
| `WS /ws` | `value` / `layout` / `kicked` / `stopped` |

PIN сверяется на join, в token не кладётся повторно как секрет страницы (token = `secrets.token_urlsafe`, map в `TableHostSession`).

### D3. Посадка и вытеснение

`seated_ids: set[int]`. `occupancy: instance_id -> {name, token, ws}`. Join: имя уникально; если то же имя — закрыть старый ws (`kicked`), занять тот же лист если occupancy.name совпало, иначе отказ если имя занято на другом листе. Другое имя + занятый instance → 409.

### D4. QR и URL

`segno.make(url)` → PNG в `QLabel`. URL: `http://{ip}:{port}/` для каждого IPv4 кроме loopback, плюс loopback строкой для отладки на той же машине.

Порт: поле до старта, default `7845`. `OSError` bind → сообщение.

### D5. Qt-просмотр

Тот же канвас Fill с флагом `read_only`. Подписка на `TableHostService.valuesChanged`. Design `save()` → `host.broadcast_layout(template_id)`.

Старт стола: если Fill dirty — prompt; согласие — закрыть без save; затем запрет writable Fill.

Смена игры: `host.stop()` сначала.

### D6. Тесты без внешней сети

`TestClient` для join/field/kick. Loopback `127.0.0.1:0` только если нужен живой TCP (QR/bind). CI без интернета. HTML: jsdom нет — проверять API и что static отдаёт index.html; геометрию — unit раскладки JSON→CSS `left/top/width/height` в pt.

## Risks / Trade-offs

- [Фаервол Windows] → в панели текст «разрешите порт»; не автоматический netsh.
- [0.0.0.0 и случайный WAN] → продукт LAN; NAT сам не открываем.
- [Две вкладки вытесняют] → принято.
- [Длинный лист в мобильном браузере] → лента+зум; телефон как целевой клиент позже, но HTML тот же.

## Migration Plan

1. После влитых A…C. pip: `aiohttp`, `segno` в `pyproject.toml`; hiddenimports в spec.
2. Откат: нет сервера; экземпляры B не менялись схемой.
3. Drop таблиц нет.

## Open Questions

Нет.
