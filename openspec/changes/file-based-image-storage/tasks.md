# Tasks: file-based-image-storage

## 1. Core storage (ImageStore)

- [x] 1.1 Создать `app/infrastructure/images/` (package) с path-resolver'ом: `original_path(image_dir, sha256, ext)`, `preview_path(image_dir, sha256)` (раскладка `images/<hash[:2]>/<hash>.<ext>` / `<hash>.preview.webp`). Verify: unit-тесты резолвера (2-буквенный подкаталог, имена preview, детерминированность) — `python -m pytest tests/test_image_paths.py` зелёный.
- [x] 1.2 Реализовать preview-генератор: `(original_bytes) -> preview_bytes`, 512px, WebP lossy q80, фиксированные константы. Verify: тесты — выходной формат `webp`, max-сторона ≤ 512, повторный вызов на тех же bytes даёт тот же hash (детерминизм) — `python -m pytest tests/test_image_preview.py` зелёный.
- [x] 1.3 Реализовать `ImageStore.store(data) -> image_id`: декод/валидация (QImage/QImageReader: размеры, формат), sha256, dedup-hit (SELECT by hash + оба файла на месте → return, без записи), иначе temp+rename original → preview → INSERT `images` (sha256 unique; IntegrityError → повторный SELECT). Неисправимый файл → исключение. Verify: тесты на tmp-каталоге (нормальный импорт, dedup-hit, невалидный файл, race-ветка через monkeypatch) — `python -m pytest tests/test_image_store.py` зелёный.
- [x] 1.4 Реализовать `ImageStore.refcount(image_id)`, `gc_after_commit(*old_ids)` (refcount==0 → unlink original+preview + DELETE row; ошибка unlink → только log, данные не трогаются) и `startup_gc()` (4-state по design D7: orphan-файлы → unlink; row без original → row + SET NULL ×3; row с original без preview → regenerate; unreferenced row → row + unlink; плюс unlink `*.tmp-*` остатков). Verify: тесты каждого state, включая ветку `unlink`-сбоев через monkeypatch и идемпотентный повторный прогон — `python -m pytest tests/test_image_gc.py` зелёный.

## 2. DB schema и миграция схемы

- [x] 2.1 Добавить `ImageModel` (`images`: id, sha256 UNIQUE, ext, width, height, size_bytes, created_at) и `image_id` FK (`ON DELETE SET NULL`) на `OrganizationModel`/`CharacterModel`/`LocationModel`. Verify: in-memory aiosqlite тест создания схемы и FK-поведения (SET NULL при delete сущности) — `python -m pytest tests/test_models_images.py` зелёный.
- [x] 2.2 Расширить `_MIGRATIONS`/`init_db()`: создание `images` и добавление `image_id` в 3 таблицы (идемпотентно для существующих БД). Verify: тест — свежая и «старая» (без `image_id`) БД после `init_db()` имеют схему — `python -m pytest tests/test_init_db_migration.py` зелёный.

## 3. Каталог-игра (game_manager)

- [x] 3.1 Переделать `create_game`/`list_games`/`delete_game` на каталоги: `games/<name>/game.db` + пустой `images/`; имя игры = имя каталога; delete — удаление каталога. Verify: тесты с tmp `games_dir` (создание, список, дубль-имя → ошибка, удаление) — `python -m pytest tests/test_game_manager_catalog.py` зелёный.
- [x] 3.2 Реализовать экспорт v2: `game.db` в корне zip + `images/**` (recursive, если не пусто) + `meta.json` (`version` приложения, `archive_version: 2`, name, exported_at, db_size). Verify: тест-архив содержит ровно ожидаемый набор, `archive_version == 2`, пустая игра без `images/` тоже экспортируется — `python -m pytest tests/test_game_export_v2.py` зелёный.
- [x] 3.3 Реализовать атомарный импорт: распаковка в tempdir (та же ФС, рядом с `games/`) → верификация sha256 каждого файла `images/**` (mismatch → `ValueError` с именем файла + rmtree temp) → отказ при существующем имени → атомарный rename в `games/<name>/`. Verify: тесты — успешный импорт v2, повреждённый файл (битый байт → отмена, в `games/` ничего не появилось), конфликт имён, битый/отсутствующий `meta.json` — `python -m pytest tests/test_game_import_v2.py` зелёный.
- [x] 3.4 Ветка совместимости v1: архив без `images/` → каталог без файлов, без верификации; поведение `FileExistsError`/`ValueError` как сейчас. Verify: тест-архив v1 (только `game.db`+`meta.json`) импортируется — `python -m pytest tests/test_game_import_v2.py -k v1` зелёный.

## 4. Миграция legacy и startup-пайплайн

- [x] 4.1 Миграция legacy-base64 в `init_db()`: per-row цикл (legacy не NULL → декод bytes → `ImageStore.store` → `image_id` → legacy := NULL), per-row commit; после цикла, если миграли > 0 → `VACUUM`. Verify: тесты — legacy-игра со 2 изображениями после старта в файлах на диске, `image_id` проставлены, legacy-колонки NULL; повторный старт ничего не меняет; VACUUM вызвался (monkeypatch-замер) — `python -m pytest tests/test_legacy_migration.py` зелёный.
- [x] 4.2 Связать порядок старта в `Application.start()`: `init_db()` (схема+миграция) → `startup_gc()` → UI; DI `ImageStore` в `start()` (закрытие при shutdown не требуется — без состояний). Verify: offscreen-тест `Application.start()` с legacy-БД — после `start()` файлы на месте, UI-окно создано — `python -m pytest tests/test_application_startup.py` зелёный.

## 5. Презентация: отображение

- [x] 5.1 `image_utils`: заменить base64-функции на null-safe `load_preview(image_id) -> QPixmap` (файл 512 → резайз в слот) и `load_original(image_id) -> QPixmap` (полный размер); missing/corrupt → `QPixmap()` (пустой) + log. Verify: тесты с tmp-файлами (есть/нет/битые) — `python -m pytest tests/test_image_utils.py` зелёный.
- [x] 5.2 Переключить слоты на preview через viewmodel (view не вычисляет пути): `detail_panel` (100px), `world_snapshot_widget` (24px), карточка (280px); плейсхолдер «Нет изображения» при отсутствии. Verify: UI-тесты (qt_api pyside6, offscreen) — сущность с/без изображения — `python -m pytest tests/test_detail_panel.py tests/test_world_snapshot.py tests/test_entity_card_dialog.py` зелёные.
- [x] 5.3 Полный viewer: QDialog (QLabel + QScrollArea, ESC/кнопка — закрыть), открытие по клику image-label в карточке и detail panel; при отсутствии original — preview, при отсутствии обоих — сообщение. Verify: UI-тесты — клик открывает окно, прокрутка крупного изображения, ESC закрывает, fallback-ветки — `python -m pytest tests/test_image_viewer.py` зелёный.

## 6. Презентация: ингест и изменение

- [x] 6.1 Карточка сущности: выбор файла → bytes → ViewModel → `ImageStore.store`; `get_data()` передаёт image_id (не байты); нечитаемый файл → QMessageBox-предупреждение (не молча). Verify: UI-тесты — успешный выбор, нечитаемый файл (dialog не молчит), сохранение → `image_id` в data — `python -m pytest tests/test_entity_card_dialog.py` зелёный.
- [x] 6.2 Кнопка «Убрать» и замена изображения идут через существующий save-путь: после commit вызов `gc_after_commit(старый image_id)` (в service, не в view). Verify: тесты поведения — замена уникальной картинки удаляет старые файлы; замена на общую — не удаляет; «Убрать» — удаляет; unlink-sfail → операции сохранены — `python -m pytest tests/test_image_gc.py tests/test_entity_service_images.py` зелёны.
- [x] 6.3 `XlsxImportService`: поле image → `ImageStore.store` → `image_id` в data; нечитаемый файл → сущность без image_id + warning в отчёт импорта. Verify: тесты xlsx-импорта (норма, битый файл, отсутствующий файл) — `python -m pytest tests/test_xlsx_import_service.py` зелёный.

## 7. Финальные интеграционные проверки

- [x] 7.1 Полный проход: `QT_QPA_PLATFORM=offscreen python -m pytest` зелёный + coverage-гейт (LINE 100%): все ветки (GC-сбои, миграция, import-ошибки, деградация UI) покрыты тестами, `fail_under = 100` не падает.
- [x] 7.2 Ручной smoke (checklist): создать игру → добавить изображения (карточка + xlsx) → проверить превью во всех слотах и полный viewer → экспорт `.nri` → импортом в другой `games_dir` (rename каталога) → открыть → все изображения на месте, sha256 файлов совпадают с именами; legacy-игра (изменённая БД старой версии) мигрируется первым старт.
- [x] 7.3 Версии/доки: bump версии (0.15.0) синхронно в `pyproject.toml` + `CFBundleShortVersionString` в `nri_manager.spec` + `docs/CHANGELOG.md` (запись: каталог-игра, images по sha256, v2-архив, legacy-миграция, принятые ограничения совместимости v2→v1). Verify: три версии совпадают, CHANGELOG отражает breaking-формат.
