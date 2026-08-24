# Design: файловое хранилище изображений с адресацией по sha256

## Context

- PySide6 desktop app, MVVM + qasync (весь async на Qt event loop), SQLAlchemy 2.0 async + aiosqlite, одна SQLite-игра.
- Сейчас: legacy-колонки `image` (base64 PNG ≤1000x1000) у `organizations/characters/locations`; два источника ингеста (`EntityCardDialog` и `XlsxImportService`); игровые данные — flat-файл `games/<name>.db`; экспорт/импорт `.nri` = `game.db` + `meta.json`.
- Ограничения окружения: миграции только inline в `init_db()` (alembic не используется); тестовый gate — 100% line coverage, DB-тесты на in-memory aiosqlite из `tests/conftest.py`, сетевые тесты не допускаются; PyInstaller (bundle-директория, `nri_manager.spec`); WebP-плагин входит в PySide6 wheels (подтверждено: `libqwebp` в imageformats), PyInstaller hooks PySide6 собирают Qt-плагины сами.
- Полное согласование решений: сессия grilling перед этим change (все решения фиксированы, open questions ниже — только deferred).

## Goals / Non-Goals

**Goals:**
- Убрать пиксели из SQLite; DB хранит только метаданные + sha256.
- Детерминированное, восстанавливаемое хранилище: любой файл (кроме original) может быть пересоздан; инвариант согласованности после каждого старта.
- Честный «оригинал» (без cap 1000px) + дешёвое preview 512px.
- Переносимая игра: экспорт/импорт = один каталог; импорт атомен и верифицируется.

**Non-Goals:**
- Не удаляем legacy-колонки `image` из схемы (обнуляем; drop — будущий release).
- Не вводим «единое хранилище на несколько игр»/глобальный кэш: дедупликация в пределах одной игры.
- Не делаем background/deferred GC: GC — синхронный best-effort шаг после commit.
- Не делаем пересчёт preview при изменении констант: константы фиксированы (512, WebP, q80); при будущем изменении — отдельная миграция.
- Не валидируем `archive_version` на входе (поле информационное; блокировка будущих форматов — вопрос будущих release).

## Decisions

### D1. Игра — каталог `games/<name>/` (game.db + images/)
- **Почему**: игра самодостаточна; экспорт/импорт сводятся к zip-ке каталога; «чьи это файлы» решается каталогом, без связующих таблиц.
- **Альтернативы**: flat `games/<name>.db` + общий каталог изображений (требует маппинг игра→файлы, ломается при копировании одного файла); `~/.nri_manager/images/...` (рассеivent, хрупко при переносе); `/tmp` (эфемерно, отвергнуто).
- **Влияние**: `create_game/list_games/delete_game` работают с каталогами; `Application.start(db_path)` принимает путь к `game.db` внутри каталога (имя игры — имя каталога).

### D2. Addressing: путь = f(каталог игры, sha256), пути в DB не хранятся
- `images/<hash[:2]>/` (2-буквенные подкаталоги против thousands-файлов в одной папке): `<hash>.<ext>` — original, `<hash>.preview.webp` — preview.
- `ext` определяется по реальному формату содержимого (QImageReader), а не по имени файла: имя «photo.PNG» с JPEG-содержимым не должно давать ложное расширение (хэш уже определяет «какой» файл, а расширение — «как открыть»).
- **Почему без path-колонк**: путь выведен, значит не может рассинхронизироваться; нет DDL при смене имени; экспорт/импорт независимо от абсолютных путей.
- **Альтернатива отвергнута**: `original_path/preview_path` в `images` — дублирование истины, лишняя миграция при смене схемы; отладочные «какие файлы» закрываются списком каталога.

### D3. Таблица `images` + `image_id` FK, а не «хэш в колонках сущностей»
- `images(id, sha256 UNIQUE, ext, width, height, size_bytes, created_at)`; сущности получают `image_id` FK `ON DELETE SET NULL`.
- **Почему**: unique-индекс = O(1) dedup-проверка; refcount = `COUNT(*)` по `image_id` в 3 таблицах (одна точка); width/height снимаются один раз при ингесте (не при каждом open); FK даёт декларативное снятие ссылок.
- **Альтернатива**: хранить «`<hash>.<ext>`» прямо в legacy-колонке `image` — без отдельной таблицы; rejected: refcount требует UNION по 3 таблицам, метаданные дублируются, дедуп-проверка по строке, а не по индексу.

### D4. Ингест: один сервис `ImageStore` (infrastructure), DI
- API (контур): `store(data: bytes) -> image_id` (raise при невалидном), `preview_path(image_id)`, `original_path(image_id)`, `refcount(image_id)`, `gc_after_commit(*old_image_ids)`, `startup_gc()`, `resolve_for_display(entity)`.
- Внутри конвейера (порядок — контракт, spec «Единый конвейер»): декод (валидация, размеры, альфа — альфа не влияет на выбор формата preview: WebP поддерживает) → sha256 → SELECT by hash: exists **и** оба файла на месте → return id (без записи) → иначе temp+rename original, генерация preview (temp+rename) → INSERT (unique по sha256; IntegrityError → повторный SELECT, race-защита).
- **Почему сервис в infrastructure, а не в viewmodel**: `EntityCardDialog` сейчас сам трогает `image_utils` и сохраняет бинарь; перенос в сервис делает и диалог, и xlsx-импорт, и миграцию клиентами одного pipeline (единый источник «правильного» файла).
- **Почему temp+rename, а не прямая запись**: частичный файл по финальному имени = нарушение инварианта; rename атомарен внутри одной ФС (каталог игры — одна ФС).

### D5. Preview: 512px WebP lossy q80, единственный формат
- **Почему WebP**: плагин во всех wheels, PyInstaller соберёт сам, альфа на месте (JPEG дал бы плоский фон артам с прозрачностью — пришлось бы ветку «альфа→PNG», т.е. 2 формата), размер при 512px меньше JPEG.
- **Почему единственный формат**: детерминированное пересоздание = одна функция `(original_bytes) -> preview_bytes`; без веток по альфе/формату.
- **Почему 512**: максимальный слот UI — 280px (карточка); 512 покрывает Retina (2x) с запасом, не превращая превью в псевдо-оригинал.

### D6. GC: commit-first, sync best-effort, refcount-driven
- Порядок (заменa / снять / удалить сущность): мутация ссылок → commit → `gc_after_commit(старые image_id)`: `refcount == 0` → unlink original + preview → DELETE row `images`.
- **Почему не в транзакции**: unlink не транзакционен c SQLite: commit-first гарантирует, что «операция пользователя» сохранена даже при сбое FS; сбой unlink → log, данные согласованы (строка+файл просто останутся — уберёт startup-gc как unreferenced).
- **Почему не background task**: отложенный GC = новая поверхность (race со стартом, cancel, отладка) ради экономии ~2 unlink за операцию; операции редкие.
- **Почему без колонки-маркера `deleting`**: маркер = 3-е состояние, требующее своей обработки в startup-gc и UI; не нужно.

### D7. Startup-GC: 4-state скан, без декодирования originals
- Алгоритм (контур): читать список файлов `images/**` (имя → hash из имени) + `SELECT` всех строк `images` + set-операции:
  1. hash на диске, без строки → unlink both files;
  2. строка, original отсутствует → `UPDATE ... SET image_id=NULL` по 3 таблицам → DELETE row;
  3. строка, original есть, preview отсутствует → regenerate preview (D5 pipeline);
  4. строка без ссылок (refcount 0) → unlink both + DELETE row;
  5. строка с ссылокaми, both files → OK.
- **Почему без декода originals на старте**: декод всех файлов на каждом старте — O(весь storage) CPU; existence+размер достаточно для инварианта «каждый файл принадлежит строке» и «у строки есть original». Битый (но существующий) original покрывается деградацией отображения (spec image-display): строка не удаляется автоматически — пользователь может перезаписать картинку; самодельная утилизация чужих данных отклонена.
- **Точка запуска**: в `Application.start()`, после `init_db()` (нужна готовая схема + каталог игры), до открытия MainWindow.

### D8. Миграция legacy в `init_db()` + VACUUM один раз
- Детектор legacy: значение в `image` не NULL и не пустое (после перехода колонка будет только NULL; legacy-значения — именно base64). Порядок в `init_db()`: `_MIGRATIONS` (создать `images`, добавить `image_id`) → миграция per-row: для каждой legacy-строки: декод bytes → `ImageStore.store` (вычитает sha256, пишет files, вставляет row — **в той же сессии**) → `entity.image_id = new` → `entity.image = NULL` → commit → (после цикла, если count>0) `VACUUM`.
- **Почему per-row commit в цикле**: краш в середине миграции не должен оставлять game.db на полпути без возможности продолжить: идемпотентность строки-статьи — (legacy не NULL) → повторный старт доделает остаток.
- **Почему VACUUM после миграции, а не вообще/в фоне**: VACUUM блокирует DB; UI ещё не открыт (one-cost, user accepts longer one-time startup), в фоне — блокировка во время работы; «всегда VACUUM» — бессмысленная цена для новых игр.
- Мигрированный original = то, что было в base64 (≤1000px PNG по legacy-импорту) — ограничение данных, не дизайна (fix в spec).

### D9. Архив `.nri` v2: zip каталога + sha256-верификация + temp-import
- Экспорт: `zipfile` по каталогу игры: `game.db` (корень), `images/**` (recursive), `meta.json` (version приложения, `archive_version: 2`, name, exported_at, db_size). `game.db` в корне, а не `images/...` под префиксом `<name>/`: совместимо с текущим layout архива и кодом import, который читает `_ARCHIVE_DB_NAME = "game.db"`.
- Импорт: `tempdir` рядом с `games/` (та же ФС!) → extractall → верификация: для каждого файла в `images/`: hash по имени vs sha256(content) mismatch → `ValueError(файл)` → shutil.rmtree(temp) → raise; `meta.json` отсутствует/битый → reject (текущее поведение сохранено); target `games/<name>/` существует → `FileExistsError` (текущее поведение); иначе `tempdir.rename(target)`.
- **Почему tempdir на той же ФС**: cross-device `rename` не работает (fallback copy — не атомарен); `games/` и tempdir соседи.
- **Почему верификация обязательна**: имя файла = хэш — corruption бита ловится бесплатно при уже читаемых для rename файлах; без проверки битый файл просуществует до первого клика.
- **v2 в старом app**: старый `import_game` делает `zf.extract("game.db")` — `images/**` тихо игнорируются. Принятое ограничение (fix в compat spec); предупреждать нельзя — старый код.

### D10. Display: единый резолвер + новый full-size viewer
- `image_utils`: base64-функции заменяются: `load_preview(image_id) -> QPixmap` (512px file → slot-резайз), `load_original(image_id) -> QPixmap` (полный размер). Слоты (detail_panel 100, snapshot 24, card 280) получают path из модели через сервис/viewmodel — view не вычисляет пути.
- Viewer: новый QDialog (QLabel + QScrollArea, `setWindowTitle`, ESC через `keyPressEvent`/dialog close), открывается по клику на image-label в карточке и detail panel (клик по 24px snapshot — не нужен: цель — карточка/панель).
- **Почему in-app, а не `QDesktopServices.openUrl`**: offline-first UX, не зависит от «открыть по умолчанию», один код на 3 ОС.
- **Деградация** (spec image-display): `load_preview`/`load_original` возвращают null-safe `QPixmap()` при missing/undecodable; view показывает плейсхолдер; viewer при отсутствии original — preview либо сообщение. Данные не трогаем (D7 rationale).

### D11. Влияние на xlsx-импорт
- `XlsxImportService` перестанет хранить `image` в `data["image"]`; вызовет `ImageStore.store(bytes)` и передаст `image_id` в repository (совместимо с D3). Файл, указанный в ячейке, нечитаем → сущность без `image_id` + warning в отчёт (единый pipeline, spec image-storage).

## Risks / Trade-offs

- [Крупные user-файлы раздувают каталог/архив без cap] → cap не возвращается (решение Q3); защита по размеру на входе не добавляем (RPG-архив, не сервис). Отмечено как known trade-off.
- [VACUUM на огромной legacy-БД — длинный один раз] → принимаемо (one-time, до UI); прогресс не показываем (не добавляем UI ради one-cost).
- [Cross-version импорта v2→v1 теряет images] → фиксировано документно; обратная миграция невозможна по определению.
- [Расхождение «строка в DB без preview», если original изменён пользовательским копированием] → sha256 в имени ≠ новый хэш: пользовательский «обмен файла» создаёт сироту (старый unlink-нет — нет строки?) — нет: при user-подмене оригинала хэш имени перестанет совпадать с содержимым → startup-gc state (3.5) видит original-present (по имени), preview stale (по старому оригиналу) → preview не пересоздаётся (есть файл). Последствие: превью и полный вид расходятся до ре-импорта. Митигация: startup-gc **дополнительно** (опционально, deferred D12) — sha256-сверка оригинала в режиме «паранойя» только при подозрении; базовая версия: не проверяем оригинал на старте (быстрота старта важнее), расхождение self-heals при замене. Documented trade-off.
- [Temp-file-остатки при жёстком kill (SIGKILL)] → не cleanup'ят startup-gc (имёна не по хэшу, сиротство не детектируется по имени). Митигация: имена temp-файлов `<final>.tmp-<pid>` + при скане `images/**` unlink `*.tmp-*` (однострочное правило, часть D7).
- [100% coverage gate vs. ветки best-effort unlink] → ветки покрываются monkeypatch-ом `Path.unlink` (raise) и tmp-файл-фикстурами; в tasks.
- [PyInstaller + WebP на 3 ОС] → верифицировано (плагин в wheels, hooks); smoke-тест сборки — отдельный CI-артефакт (уже существующий 3-OS build pipeline).

## Migration Plan

1. Деплой = новая версия приложения (каталог-игра создаётся/мигрируется при первом старте каждой игры).
2. Legacy-игра: первый старт → `init_db()` (schema) → migration → VACUUM → startup-gc → UI. Идемпотентно; повторные старты без миграции.
3. Rollback: старая версия видит `games/<name>.db` — **нет файла** (теперь каталог). Rollback-сценарий: пользовательская игра с изображениями в old app не откроется; текстовые данные — вручную через новый экспорт v1-совместимого архива? — нет: v2-архив в old app теряет images (D9), db останется. **Принято**: обратного совместимого экспорта «v2→v1 с images в base64» не делаем; rollback версии приложения для игровых данных с картинками не поддерживается (документировать в CHANGELOG).
4. Новые игры: миграция нет, каталог создаётся сразу в новом layout.

## Open Questions

- Переиспользование 2-буквенного подкаталога против плоского `images/`: при >~10k изображений в игре — нет пересмотра (flat не сломается, это оптимизация).
- Будущее: «переименование игры» (rename каталога) — нет в roadmap, но D1 его делает свободным (все пути выведены из каталога, DB без абсолютных путей) — если понадобится, отдельный change.
- Будущее: `image_id` на больше сущностей (items) — схема уже поддерживает; когда понадобится поле в UI — отдельный change.
