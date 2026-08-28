# Tasks: add-character-sheet-a-playable

Делать **после** влитого `add-character-sheet-a1`. TDD: сначала тесты. `QT_QPA_PLATFORM=offscreen python -m pytest`. Без сети. A-editor (undo/snap/z-order/duplicate) не делать.

## 1. Domain: лента, clamp по странице, v2

- [x] 1.1 Тесты `scene_to_page` / `page_origin` (GUTTER 24, альбом swap w/h); `clamp_rect` в локале страницы; `parse_template` v1 → одна «Страница 1»; v2 с двумя страницами; unknown type → ошибка; нормализация `,`→`.` для number; пустая опция dropdown отвергается. Проверка: `tests/domain/test_character_sheet.py` расширен, красные до 1.2.
- [x] 1.2 Реализовать геометрию ленты, `FieldType` (+checkbox/number/dropdown/image/rect/line), парсер v1/v2 (D3). Проверка: тесты 1.1 зелёные.

## 2. Service: create v2, load, страницы

- [x] 2.1 Тесты сервиса: create пишет schema_version 2 и «Страница 1»; load v1 не теряет поля; save пишет 2; unknown type не отдаёт макет; add/remove/reorder/rename страниц в модели (последнюю удалить нельзя). Проверка: `tests/application/test_character_sheet_service.py` красные до 2.2.
- [x] 2.2 Дописать `CharacterSheetService` / сериализацию. Проверка: тесты 2.1 зелёные.

## 3. ImageStore: ссылки из JSON листов

- [x] 3.1 Тесты: `refcount` учитывает `image_id` в pages; поле листа + персонаж на одном файле — удаление персонажа файл не снимает; delete шаблона / очистка поля + save → gc удаляет сироту; startup_gc не удаляет запись, на которую ссылается только лист. Проверка: красные до 3.2.
- [x] 3.2 `iter_sheet_image_ids` + правки `refcount` / `_null_references` / unused в `ImageStore` (D6). Проверка: тесты 3.1 зелёные.

## 4. ViewModel: страницы, ориентация, перенос

- [x] 4.1 Тесты VM: вставить страницу после текущей; удалить непустую только после confirm-флага/метода; нельзя удалить последнюю; reorder; orientation clamp без scale; move с дропом на другой лист меняет page index; дроп в зазор оставляет исходную страницу. Проверка: `tests/presentation/test_character_sheet_viewmodel.py` красные до 4.2.
- [x] 4.2 Операции страниц / ориентации / `relocate_field` в VM. Проверка: тесты 4.1 зелёные.

## 5. Канвас-лента, рейка, колесо

- [x] 5.1 Тесты: две страницы столбиком; клик в зазор не place; клик рейки скроллит; колесо без Ctrl не меняет scale; Ctrl+колесо меняет; открытие — fit по ширине. Проверка: `tests/presentation/test_character_sheet_canvas.py` красные до 5.2.
- [x] 5.2 Сцена-лента, рейка, `wheelEvent` (D1, D2). Проверка: тесты 5.1 зелёные.

## 6. Типы (приёмка D8, по типу)

Для каждого типа ниже: place, select, move, resize+зажим, свойства/default, save/open, portrait→landscape. Нет набора — тип не в скоупе.

- [x] 6.1 Чекбокс: default выкл; даблклик/панель переключают. Проверка: параметризованный/отдельный тест зелёный после реализации.
- [x] 6.2 Число: «1,5» → 1.5; вне min/max и не-число отвергаются. Проверка: тесты зелёные.
- [x] 6.3 Список: опции без пустых; default в панели, на канвасе текст default. Проверка: тесты зелёные.
- [x] 6.4 Картинка: выбор файла → ImageStore; даблклик открывает выбор; очистка + save → refcount 0; нечитаемый файл — ошибка, поле пустое. Проверка: тесты зелёные.
- [x] 6.5 Рамка: нет content; только обводка. Проверка: тесты зелёные.
- [x] 6.6 Линия: w>h → горизонталь; иначе вертикаль. Проверка: тесты зелёные.
- [x] 6.7 Палитра содержит указатель + 9 типов; постановка по-прежнему разовая. Проверка: тест палитры зелёный.

## 7. Интеграция

- [x] 7.1 E2E: две страницы, поле перенести на вторую, сохранить, открыть; v1-шаблон открыть и сохранить → version 2. Проверка: `tests/ui/test_e2e_char_sheets.py` дополнен, зелёный.
- [x] 7.2 `.nri` roundtrip с картинкой на листе. Проверка: существующий nri-тест или новый — зелёный.
- [x] 7.3 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
- [x] 7.4 `docs/CHANGELOG.md` (страницы, типы, колесо, v2, незавершено); в `docs/character-sheets-roadmap.md` статус A-playable = план/в работе. Проверка: `openspec validate add-character-sheet-a-playable --strict` зелёный.
