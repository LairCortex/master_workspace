# Tasks: add-character-sheet-c

Делать **после** A1, A-playable, A-editor и B. TDD. `QT_QPA_PLATFORM=offscreen python -m pytest`. Без сети. Anima/официальные PDF не копировать. C2+ и новые типы полей не делать. `schema_version` шаблона не менять.

## 1. Каталог и файлы бандла

- [x] 1.1 Тесты: `PresetCatalog.list()` — ровно два элемента в порядке Fate Core, Mörk Borg; `license_text` Fate содержит CC BY и faterpg.com; текст MB содержит «Third Party License» и «©2019»; load JSON даёт schema 2, одну книжную страницу. Проверка: `tests/application/test_character_sheet_presets.py` красные до 1.2.
- [x] 1.2 `catalog.py` + `fate_core.json` + `mork_borg.json` (D1); строки лицензии как в spec. Проверка: тесты 1.1 зелёные.
- [x] 1.3 В `nri_manager.spec` `datas` — оба JSON пресетов (явный список файлов). Проверка: `tests/test_spec_presets_bundle.py` (datas покрывает все файлы каталога) + артефакт сборки содержит оба JSON.

## 2. Состав полей

- [x] 2.1 Тесты Fate JSON: есть image-портрет без image_id; text имя; textarea описание; number обновление; 5 аспектов (высокая концепция, проблема, три свободных); 18 number с подписями навыков из spec; textarea трюки; 4+4 checkbox стресса; 3 text последствий; label с полным CC BY. Нет table/radio. Проверка: красные до 2.2.
- [x] 2.2 Дописать `fate_core.json` (D3, D6). Проверка: тесты 2.1 зелёные.
- [x] 2.3 Тесты Mörk Borg JSON: портрет пустой; имя; класс/предыстория; серебро; HP тек. и макс.; сила, ловкость, присутствие, стойкость; 2 checkbox знамений; оружие, броня; снаряжение, способности textarea; label с обоими абзацами 3PP; нет логотипов. Проверка: красные до 2.4.
- [x] 2.4 Дописать `mork_borg.json`. Проверка: тесты 2.3 зелёные.

## 3. Сервис снимка

- [x] 3.1 Тесты: `create_from_preset` пишет шаблон с заданным именем и pages пресета; конфликт имени отклонён; пустое имя отклонён; бандл-файл после INSERT не меняется; шаблон живёт только в текущей сессии БД. Проверка: `tests/application/test_character_sheet_service.py` дополнен, красные до 3.2.
- [x] 3.2 `create_from_preset` (D2, D4). Проверка: тесты 3.1 зелёные.

## 4. Диалог и список

- [x] 4.1 Тесты диалога: два пункта; смена пункта меняет license_text; имя подставляется из title; отмена не вызывает create. Проверка: `tests/presentation/test_character_sheet_preset_dialog.py` красные до 4.2.
- [x] 4.2 Диалог пресета (D5). Проверка: тесты 4.1 зелёные.
- [x] 4.3 Тесты списка: на вкладке «Шаблоны» есть «Создать из пресета…»; на «Листы» нет; успех → строка в списке и Design с dirty=false; конфликт имени — отказ. Проверка: `tests/presentation/test_character_sheet_list_dialog.py` дополнен, красные до 4.4.
- [x] 4.4 Кнопка + wiring открыть Design. Проверка: тесты 4.3 зелёные.

## 5. Интеграция

- [x] 5.1 E2E: пресет → копия → открыть Design → поле на месте → закрыть → список содержит имя. Проверка: `tests/ui/test_e2e_char_sheets.py` дополнен, зелёный.
- [x] 5.2 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
- [x] 5.3 `docs/CHANGELOG.md` (пресеты Fate Core и Mörk Borg, незавершено); в `docs/character-sheets-roadmap.md` C = план этого change. Проверка: `openspec validate add-character-sheet-c --strict` зелёный.
