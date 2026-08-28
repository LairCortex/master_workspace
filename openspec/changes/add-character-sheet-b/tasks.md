# Tasks: add-character-sheet-b

Делать **после** A1, A-playable и A-editor. TDD. `QT_QPA_PLATFORM=offscreen python -m pytest`. Без сети. Хост/PDF/пресеты не делать. `schema_version` шаблона не менять.

## 1. Domain: карта значений и join

- [ ] 1.1 Тесты `resolve_display`: нет ключа → default шаблона; ключ есть → значение листа (в т.ч. image `null`); id нет в шаблоне → не в отображаемых полях; `defaults_map(template)` копирует заполняемые типы, label/rect/line без ключей. Проверка: `tests/domain/test_character_sheet_instance.py` красные до 1.2.
- [ ] 1.2 `resolve_display` / `defaults_map` (D2). Проверка: тесты 1.1 зелёные.

## 2. Схема БД

- [ ] 2.1 Тесты: `create_all` создаёт `character_sheet_instances` (id, name UNIQUE, template_id, character_id, values, timestamps); UNIQUE character_id допускает несколько NULL; FK RESTRICT на шаблон; FK SET NULL на персонажа; `init_db()` на старой БД добавляет таблицу. Проверка: `tests/infrastructure/test_character_sheet_instance_model.py` красные до 2.2.
- [ ] 2.2 `CharacterSheetInstanceModel` (D1). Проверка: тесты 2.1 зелёные.

## 3. Repository и Service

- [ ] 3.1 Тесты репозитория: get_all / get_by_id / get_by_name / get_by_character_id / count_by_template / create / update / delete. Проверка: `tests/infrastructure/test_character_sheet_instance_repository.py` красные до 3.2.
- [ ] 3.2 `CharacterSheetInstanceRepository`. Проверка: тесты 3.1 зелёные.
- [ ] 3.3 Тесты сервиса: create копирует defaults и пишет template_id; конфликт имени отклонён; два листа на один шаблон ок; rename сразу, конфликт отклонён; нет setter template_id; delete; bind уникален, второй персонаж отклонён; unbind; delete персонажа оставляет лист с character_id NULL; delete шаблона с листами падает/отклонён. Проверка: `tests/application/test_character_sheet_instance_service.py` красные до 3.4.
- [ ] 3.4 `CharacterSheetInstanceService` (D5); delete шаблона в `CharacterSheetService` проверяет count. Проверка: тесты 3.3 зелёные.

## 4. ImageStore: JSON экземпляров

- [ ] 4.1 Тесты: `refcount` считает `image_id` из `values`; экземпляр + персонаж на одном файле — delete персонажа файл не снимает; clear image + save / delete экземпляра → gc сироты; startup_gc не удаляет запись, на которую ссылается только экземпляр. Проверка: красные до 4.2.
- [ ] 4.2 `iter_instance_image_ids` + refcount / null / unused (D6). Проверка: тесты 4.1 зелёные.

## 5. Fill ViewModel

- [ ] 5.1 Тесты VM: set_text/toggle/set_number/set_dropdown/set_image/clear_image; number `,`→`.` и отказ вне min/max; нет move/place; dirty/save/reload values; `reload_layout` меняет геометрию шаблона, values не трогает; inherit нового поля без ключа; сирота не рисуется; undo стек 50, save не чистит, инлайн-коммит = один шаг. Проверка: `tests/presentation/test_character_sheet_fill_viewmodel.py` красные до 5.2.
- [ ] 5.2 `CharacterSheetFillViewModel` (D3, D7). Проверка: тесты 5.1 зелёные.

## 6. Канвас Fill и хром

- [ ] 6.1 Тесты: нет палитры; рейка без add/delete/reorder; drag не меняет геометрию; клик text → инлайн; клик checkbox → toggle; клик label — без инлайна; одно выделение; «Сохранить» пишет values; dirty-close confirm. Проверка: `tests/presentation/test_character_sheet_fill_dialog.py` красные до 6.2.
- [ ] 6.2 Окно Fill + канвас read-only геометрии. Проверка: тесты 6.1 зелёные.
- [ ] 6.3 Тесты: меню «Правка» только Отменить/Повторить на `QKeySequence.StandardKey`. Проверка: зелёный после 6.4.
- [ ] 6.4 Меню Правка Fill (D4). Проверка: тесты 6.3 зелёные.

## 7. Список, окна, персонаж

- [ ] 7.1 Тесты списка: вкладки Шаблоны|Листы; создать лист → строка и INSERT; конфликт имени; rename сразу; delete confirm; delete открытого Fill id недоступен; delete шаблона с листами недоступен. Проверка: `tests/presentation/test_character_sheet_list_dialog.py` дополнен, красные до 7.2.
- [ ] 7.2 Вкладки и CRUD листов в списке. Проверка: тесты 7.1 зелёные.
- [ ] 7.3 Тесты окон: Design + Fill одного шаблона вместе; второй Fill закрывает первый с dirty-prompt; повторное открытие того же id поднимает окно; Save Design → Fill.reload_layout, грязный Design не течёт. Проверка: красные до 7.4.
- [ ] 7.4 Wiring в `Application` (D4). Проверка: тесты 7.3 зелёные.
- [ ] 7.5 Тесты: bind/unbind в Fill; кнопка в карточке персонажа открывает Fill; delete персонажа SET NULL. Проверка: зелёные после реализации карточки.

## 8. Интеграция

- [ ] 8.1 E2E: создать шаблон → создать лист → заполнить поле → save → закрыть → открыть; `.nri` round-trip листов. Проверка: `tests/ui/test_e2e_char_sheets.py` (или рядом) зелёный.
- [ ] 8.2 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
- [ ] 8.3 `docs/CHANGELOG.md` (экземпляр, Fill, незавершено); в `docs/character-sheets-roadmap.md` B = план этого change. Проверка: `openspec validate add-character-sheet-b --strict` зелёный.
