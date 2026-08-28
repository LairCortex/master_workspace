# Tasks: add-character-sheet-a1

TDD: в каждой группе сначала тесты (красные), затем реализация. Валидация: `QT_QPA_PLATFORM=offscreen python -m pytest`. Без сети. Код NRI-0007 не копировать.

## 1. Domain: модель и геометрия

- [x] 1.1 Тесты `tests/domain/test_character_sheet.py`: `SheetField`/`SheetPage`/`SheetTemplate` (одна страница, portrait, schema_version 1); `FieldType` = label/text/textarea; `clamp_rect` не выпускает рамку за A4 595.28×841.89; `default_size(type)` = 72×18 / 120×18 / 120×54; min 16×16; `place_field(type, click)` — левый верх в точке клика, затем clamp. Проверка: тесты красные до 1.2.
- [x] 1.2 Реализовать domain (`app/domain/entities/character_sheet.py`, `app/domain/enums/field_type.py`, константы страницы). Проверка: тесты 1.1 зелёные.

## 2. Схема БД

- [x] 2.1 Тесты `tests/infrastructure/test_character_sheet_model.py`: `create_all` на свежей БД создаёт `character_sheets` (колонки id, name UNIQUE, schema_version, orientation, pages, created_at, updated_at); `init_db()` на «старой» БД без этой таблицы добавляет её, существующие сущности не повреждены. Проверка: красные до 2.2.
- [x] 2.2 Добавить `CharacterSheetModel` в `models.py` (D1). Проверка: тесты 2.1 зелёные.

## 3. Repository и Service

- [x] 3.1 Тесты репозитория: get_all / get_by_id / get_by_name / create / update / delete на in-memory session. Проверка: `tests/infrastructure/test_character_sheet_repository.py` красные до 3.2.
- [x] 3.2 `CharacterSheetRepository`. Проверка: тесты 3.1 зелёные.
- [x] 3.3 Тесты сервиса: create с пустой страницей и schema_version 1; конфликт имени отклонён; rename сразу меняет имя и не трогает pages; конфликт rename отклонён; update_pages round-trip JSON; delete; load битого JSON — ошибка, шаблон не отдаётся как макет; id поля uuid, стабилен после update_pages. Проверка: `tests/application/test_character_sheet_service.py` красные до 3.4.
- [x] 3.4 `CharacterSheetService` (D5). Проверка: тесты 3.3 зелёные.

## 4. ViewModel

- [x] 4.1 Тесты VM (qapp): place сбрасывает инструмент в pointer, выделяет новое поле, инлайн не открыт; id не меняется при move/resize/content; удаление соседнего не меняет id оставшегося; clamp на move/resize; одно выделение; dirty после правки, save() сбрасывает dirty и пишет pages; reload после несохранённого move возвращает старую геометрию. Проверка: `tests/presentation/test_character_sheet_viewmodel.py` красные до 4.2.
- [x] 4.2 `CharacterSheetViewModel` (D4), save/reload через сервис. Проверка: тесты 4.1 зелёные.

## 5. Канвас, палитра, свойства, шрифт

- [x] 5.1 Положить DejaVu Sans (Regular) + LICENSE в `app/presentation/views/character_sheet/fonts/`; в `nri_manager.spec` добавить этот каталог в `datas`. Проверка: файлы на месте, spec содержит путь.
- [x] 5.2 Тесты виджетов (offscreen): палитра (указатель + 3 типа); клик типа + клик по странице ставит одно поле, указатель снова активен, рамка видна; hit-test наложения выбирает верхнее (позже поставленное); Delete/Backspace удаляют выбранное без инлайна; Esc снимает выделение без инлайна; зум колесом, при открытии страница вписана; кириллица рисуется, пикера семьи нет. Проверка: `tests/presentation/test_character_sheet_canvas.py` красные до 5.3.
- [x] 5.3 Канвас + палитра + `QFontDatabase.addApplicationFont` (D3). Проверка: тесты 5.2 зелёные.
- [x] 5.4 Тесты инлайна и панели: даблклик открывает правку; Enter фиксирует label/text; textarea Enter = новая строка, Ctrl+Enter фиксирует; Esc откатывает текст, поле выделено; клик мимо фиксирует; клик по другому полю фиксирует A и выбирает B; пока инлайн — нет move/resize; правка в панели меняет ту же строку на канвасе и наоборот; x/y/w/h с зажимом; перенос/обрезка текста в рамке (label/textarea wrap+clip по высоте, text одна линия clip по ширине). Проверка: красные до 5.5.
- [x] 5.5 Инлайн (`QGraphicsProxyWidget`) и панель свойств. Проверка: тесты 5.4 зелёные.

## 6. Список и окно редактора

- [x] 6.1 Тесты списка: создать с именем → строка в списке и запись в БД (пустая страница); конфликт имени — отказ, списка не дублирует; переименовать сразу в БД; конфликт rename — имя старое; удалить с подтверждением / отказ оставляет; delete открытого id недоступен. Проверка: `tests/presentation/test_character_sheet_list_dialog.py` красные до 6.2.
- [x] 6.2 Диалог списка (немодальный). Проверка: тесты 6.1 зелёные.
- [x] 6.3 Тесты редактора: заголовок = имя; «Сохранить» пишет макет; закрытие dirty — confirm, отказ оставляет окно, согласие не пишет pages; переименование извне меняет заголовок и не сбрасывает dirty. Проверка: `tests/presentation/test_character_sheet_editor_dialog.py` красные до 6.4.
- [x] 6.4 Окно редактора (палитра | канвас | свойства, кнопка «Сохранить»). Проверка: тесты 6.3 зелёные.

## 7. Проводка Application

- [x] 7.1 Меню «Чар-листы» на `MainWindow`, сигнал; `Application` держит list/editor, DI repo→service. Проверка: пункт меню есть в тестах окна.
- [x] 7.2 Тесты: меню открывает список; создать открывает чистый редактор; второй Open/Create при живом редакторе — dirty-prompt, один редактор; смена игры при dirty — prompt, отказ не переключает, согласие закрывает окна без save макета. Проверка: красные до 7.3.
- [x] 7.3 Реализовать проводку в `app/main.py` / wiring (D6). Проверка: тесты 7.2 зелёные.

## 8. Интеграция

- [x] 8.1 E2E `tests/ui/test_e2e_char_sheets.py`: создать → открыть → поставить label+text → сохранить → закрыть → открыть: те же id/текст/геометрия; сущность Character не создаётся. Проверка: тест зелёный.
- [x] 8.2 Roundtrip `.nri`: шаблоны переживают экспорт/импорт. Проверка: `tests/test_character_sheet_nri_roundtrip.py` зелёный.
- [x] 8.3 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
- [x] 8.4 `docs/CHANGELOG.md`: меню «Чар-листы», тонкий редактор A1, пометка незавершённого. Проверка: запись есть; `openspec validate add-character-sheet-a1 --strict` зелёный.
