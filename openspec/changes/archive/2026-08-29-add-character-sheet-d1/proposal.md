# Proposal: add-character-sheet-d1

## Why

После B и C заполненный лист живёт у мастера, но игроки за столом не могут вводить значения сами. D1 открывает стол в существующей LAN: браузер по HTTP, экземпляр B, значения сразу в `game.db`. Без этого эпик не отдаётся пользователю.

Зависит от [`add-character-sheet-a1`](../add-character-sheet-a1/), [`add-character-sheet-a-playable`](../add-character-sheet-a-playable/), [`add-character-sheet-a-editor`](../add-character-sheet-a-editor/), [`add-character-sheet-b`](../add-character-sheet-b/), [`add-character-sheet-c`](../add-character-sheet-c/) (применять шестым).

## What Changes

- Меню **«Стол»**: посадка экземпляров (хотя бы один) → старт HTTP в LAN. Панель: локальные IPv4-URL, QR, PIN из 4 цифр (новый на каждый старт), порт 7845 (смена до старта).
- Игрок в **браузере** (не второе PySide): PIN + уникальное имя за стол → свободный лист посадки. Это Fill экземпляра B, не копия шаблона.
- Веб: поля по геометрии шаблона, лента страниц, зум; без undo; label/рамка/линия без ввода. Фиксация поля сразу в БД. Картинки → ImageStore мастера.
- Мастер пока стол открыт **не пишет** значения. Список игроков; один Qt-просмотр read-only. Design шаблона можно; Save → клиенты перечитывают лейаут.
- Один клиент на лист; повторный вход тем же именем вытесняет. Выйти / выгнать / добавить в посадку на ходу. Посаженный лист во время хоста не удалять.
- Стоп: клиенты отрезаны, значения в БД, мастер снова как в B.

Не входит: интернет, HTTPS, mDNS, аккаунты, туннель, десктоп-клиент игрока, софт-AP, правки мастера поверх игрока, PDF.

## Capabilities

### New Capabilities

- `character-sheet-host`: сессия стола, PIN/посадка/входы, HTTP+веб-Fill, вытеснение, стоп.

### Modified Capabilities

- `character-sheet-instance`: удаление посаженного листа во время хоста запрещено; значения с веб-Fill пишутся в ту же карту.
- `character-sheet-editor`: пока стол открыт — мастер не пишет значения; просмотр read-only; Save шаблона уведомляет хост.
- `image-storage`: загрузка картинки с веб-Fill идёт через тот же конвейер ImageStore.

## Impact

- Новые runtime: `aiohttp` (сервер на цикле qasync), `segno` (QR). Статика веб-клиента в бандле + `nri_manager.spec` `datas`.
- `TableHostService` + панель «Стол»; веб не открывает `game.db` сам.
- Тесты: `aiohttp.TestClient` / loopback на 127.0.0.1, без внешней сети. Offscreen Qt для панели и read-only просмотра.
- `docs/CHANGELOG.md`, `docs/character-sheets-roadmap.md`.
- `schema_version` шаблона остаётся 2. ALTER не нужен.
