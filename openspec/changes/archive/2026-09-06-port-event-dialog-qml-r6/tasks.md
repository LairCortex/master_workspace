## 1. ThemeAiButton и RelatedSection (TDD)

- [x] 1.1 Красный пиксельный тест `ThemeAiButton`: активное состояние = производная `color.accent` (обе темы), off-skin без выдуманного hex, без golden PNG; `python -m pytest` на этот файл красный.
- [x] 1.2 `ThemeAiButton.qml` + qmldir; контракт `generate_requested` / `current_text` / `aiState`; тест 1.1 зелёный.
- [x] 1.3 Красный семантический тест библиотечной `RelatedSection`: список имён + три кнопки по `objectName`; «Создать» эмитит сигнал; «Отвязать» снимает выбранное; клик «Привязать» эмитит запрос наружу (пикера в QML нет).
- [x] 1.4 `RelatedSection.qml` + qmldir; тест 1.3 зелёный.

## 2. VM и прокси (TDD)

- [x] 2.1 Красные юниты тонкой `eventDialogVm`: valid = имя + storage.strip() chars|backstory + порядок дат с «Бессрочно» и `save_locked`; `saveRequested`; `EventDialogViewModel.save()` нигде не вызывается.
- [x] 2.2 Реализация VM острова; тесты 2.1 зелёные.
- [x] 2.3 Красные юниты прокси mention/AI: duck-API `show_mention_results` / `mention_search_requested` / `generate_requested` / `current_text` (storage vs имя) / `aiState` / `is_generating`; `_wire_mentions` и `_wire_ai_buttons` вызываются без правок тел.
- [x] 2.4 Прокси на фасаде; тесты 2.3 зелёные.

## 3. Остров и фасад (TDD)

- [x] 3.1 Красный objectName-контракт `EventDialogRoot`: имя, два `MentionField`, два `ThemeDateField` + «Бессрочно», тип Combo+Swatch, четыре RelatedSection, AI×3 + сущность, Save=`defaultButton`, Отмена; min 700×620.
- [x] 3.2 Root из `nri.components`; context `eventDialogVm` + `islandPalette`; цвета только палитра; тест 3.1 зелёный.
- [x] 3.3 Красные тесты фасада: `saved` без `accept()`; `finish_saving(True)` закрывает; `finish_saving(False)` оставляет открытым без второго MessageBox; Esc/close при `_saving` и генерации; populate / set_event_types / set_available_entities / add_related_entity / get_data 1:1; пустые кандидаты пикера — no-op; нативный multi-select пикер.
- [x] 3.4 Фасад-остров: deferred `setSource`; ctor 1:1; wiring create/edit вызывает `finish_saving` после успеха/сбоя; `_wire_*` без переписи; тесты 3.3 зелёные.
- [x] 3.5 Если popup типа клипится островом — widgets-combo fallback (тот же набор, swatch/icon); иначе Combo+Swatch. Зафиксировать выбранный путь тестом.

## 4. Миграция тестов и удаление widgets-layout

- [x] 4.1 Красная миграция `test_views` / `test_widget_gaps` / `test_event_dialog_types` / e2e events/types/llm/save-failures/helpers на `objectName`/прокси; failure-сценарии assert диалог `isVisible()`; успех по-прежнему закрывает.
- [x] 4.2 Удалить widgets-вёрстку `event_dialog.py` без флага; `mention_text_edit.py` и widgets `related_section.py` / `ai_assist_button.py` оставить; тесты 4.1 зелёные; grep layout-полей старого диалога чистый.
- [x] 4.3 Снять «(with its QGraphicsScene)» в `app/main.py` и переходный комментарий canvas в `sheet_font.py`; тест на отсутствие этих фраз или ручная проверка diff.

## 5. Приёмка

- [x] 5.1 Один live-retheme острова события (ввод и выбранный тип живы); `test_no_chrome_hex` на новых qml.
- [x] 5.2 `nri_manager.spec` datas: `ThemeAiButton.qml`, `RelatedSection.qml`, `EventDialogRoot.qml`; бандл-тест qml проходит.
- [x] 5.3 `python -m pytest` зелёный, coverage-гейт Python 100%.
