# Proposal: Диалог события на QML-остров (R6)

## Why

Эпик R закрывает mention-стек после запланированных R3–R5. R6 переносит `EventDialog` на остров с `MentionField` и `finish_saving`, чтобы снять гибрид widgets-вёрстки с QML-полями и закрыть отложенное «не закрывать диалог при провале сохранения».

## What Changes

- `EventDialog` становится QML-островом в прежней `QDialog`-обёртке (рамка/Esc системные, `defaultButton`=Save, minSize 700×620). Widgets-вёрстка содержимого удаляется без флага.
- Поля: `MentionField` ×2 (характеристики, предыстория); `ThemeDateField` ×2 + «Бессрочно»; тип — `ThemeComboBox`+`ThemeSwatch` (widgets-combo только если clip на приёмке принят).
- `RelatedSection` в `nri.components` (список + три кнопки). «Привязать» — нативный `QDialog`+multi-select; пустые кандидаты → no-op.
- `ThemeAiButton` + Python-прокси с API `AiAssistButton` (`generate_requested`, `current_text` из storage/имени, `aiState`). `_wire_mentions` / `_wire_ai_buttons` не переписываются: фасад отдаёт `get_mention_edits` / `get_ai_buttons` / `get_entity_button` / `set_save_locked` / `set_close_guard` / `show_mention_results`.
- Context: `eventDialogVm` + `islandPalette`. Valid = имя + `storage.strip()` chars|backstory + порядок дат с учётом «Бессрочно» и `save_locked`.
- `saveRequested` + `finish_saving`; публичный Python API фасада 1:1 (`populate` / `set_event_types` / `set_available_entities` / `add_related_entity` / `get_data` / сигналы `saved` / `create_related_requested` / `mention_clicked`). Провал save — диалог открыт. Esc/close глушатся при `_saving` и при генерации (close_guard 1:1).
- `EventDialogViewModel.save()` не оживляем.
- Docstring `main.py` (`QGraphicsScene`) и устаревший комментарий `sheet_font.py` снимаются. `mention_text_edit.py` жив (карточка сущности — R7).
- Приёмка: семантика + e2e `objectName` + live-retheme; hex у `ThemeAiButton`; TDD. Roadmap/CHANGELOG — на apply, не в этом planning.

## Capabilities

### New Capabilities

_(нет)_

### Modified Capabilities

- `qml-shell`: остров диалога события; context `eventDialogVm`; `finish_saving` и блок close; в «ещё widgets» остаётся карточка сущности.
- `qml-components`: в библиотеку — `RelatedSection` и `ThemeAiButton` с пиксельной приёмкой кнопки.
- `save-error-reporting`: после сбоя сохранения события диалог остаётся открытым.
- `related-entity-creation`: секция related на острове из библиотеки; пикер — нативный `QDialog`.
- `entity-generation`: AI через прокси/`ThemeAiButton`; close также при `_saving`.
- `event-types`: селектор типа в диалоге события — combo+swatch на острове.

## Impact

- `app/presentation/views/event_dialog.py` — фасад-остров; widgets-layout удалён.
- `app/presentation/viewmodels/` — тонкая sync-VM острова (существующий `EventDialogViewModel.save()` не используется).
- `app/presentation/qml/` — `EventDialogRoot.qml`; `nri.components`: `RelatedSection`, `ThemeAiButton`; qmldir + `.spec` datas.
- Прокси mention/AI на Python-стороне фасада; wiring пяти вызовов API без переписи `_wire_*`.
- `app/main.py` / `sheet_font.py` — только снятие просроченных комментариев.
- Тесты диалога события, e2e save-failure, AI, types — `objectName` / прокси; `mention_text_edit.py` и карточка не в скоупе.
- Не входит: R7 карточка, удаление widgets-related/AI/MentionTextEdit, chip шкалы, `CustomDateEdit`.
