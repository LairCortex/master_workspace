## Context

См. proposal.md — Why. Предшественники R3–R5 считаются запланированными: библиотека уже имеет `ThemeComboBox`, `ThemeSwatch`, `ThemeDateField`, `MentionField`; попаверы даты и mention — widgets-мосты. Текущий `event_dialog.py` (~385) сам валидирует, сразу `accept()` после `saved`, widgets `MentionTextEdit`/`CustomDateEdit`/`RelatedSection`/`AiAssistButton`. `EventDialogViewModel.save()` мёртвый относительно фасада (другая валидность дат). Q2.5c уже показывает critical на сбое, но диалог закрывается. `mention_text_edit.py` нужен карточке (R7).

## Goals / Non-Goals

**Goals:**
- Остров события 1:1 UX кроме «диалог жив при провале save».
- Прокси, чтобы `_wire_mentions` / `_wire_ai_buttons` не ветвились.
- `finish_saving`; widgets-layout события удалён.
- Снять просроченные комментарии `main.py` / `sheet_font.py`.

**Non-Goals:**
- Карточка сущности, удаление `mention_text_edit.py` / widgets `related_section.py` / `ai_assist_button.py` / `CustomDateEdit`.
- Оживление `EventDialogViewModel.save()`.
- Смена формата упоминаний, chip шкалы, roadmap/CHANGELOG в planning.

## Decisions

### D1. Фасад-остров, context `eventDialogVm`

`QDialog` + `QQuickWidget` + общий engine, deferred `setSource(QUrl())`. Context: `eventDialogVm` + `islandPalette`. Ctor `(event_dialog_vm, parent, theme)` 1:1; тонкая sync-VM острова принадлежит фасаду (поля, valid, types, related-модели, `saveRequested`). Переданный `EventDialogViewModel` не путь записи.

### D2. `saved` + `finish_saving`, не двойная модалка

QML Save → `saveRequested` → фасад эмитит `saved(get_data())` без `accept()`, ставит `_saving`. Проводка как сейчас (critical + reload) и вызывает `finish_saving(ok)`. `True` → `accept()`. `False` → снять `_saving`, диалог открыт; **без** warning фасада (critical уже в wiring). Альтернатива переименовать сигнал в `saveRequested` публично отклонена: API 1:1.

### D3. Прокси mention и AI

`get_mention_edits()` / `get_ai_buttons()` / `get_entity_button()` возвращают Python-объекты с прежними сигналами/методами (`mention_search_requested`, `show_mention_results`, `generate_requested`, `current_text` из storage/имени, `aiState`, `is_generating`). Хосты R5 `MentionField` живут за прокси. Альтернатива переписать `_wire_*` отклонена.

### D4. Related: библиотека + нативный пикер на фасаде

`RelatedSection.qml` — список + три кнопки; `linkRequested` / `createRequested` / unlink в VM. Пикер — существующий widgets `QDialog` (можно вынести helper из `related_section.py`, файл widgets-секции не удалять — R7). Пустые кандидаты — no-op до `exec`.

### D5. Тип: Combo+Swatch, fallback clip

Сначала `ThemeComboBox` + `ThemeSwatch` в делегате. Если popup обрезается `QQuickWidget` на приёмке — widgets `QComboBox` мост (как дата-поповер), набор типов тот же. Colorpicker нет.

### D6. Valid на VM острова

`valid` = `name.strip()` и (`chars.storage.strip()` или `backstory.storage.strip()`) и (бессрочно или end ≥ start) и not `save_locked`. Не использовать `EventDialogViewModel.is_valid` (требует оба конца).

### D7. TDD

Красные: hex `ThemeAiButton`; objectName острова; `finish_saving(false)` оставляет диалог; прокси проходят существующие `_wire_*`. Затем реализация. Существующие suites события/e2e/AI/types — `objectName`/прокси, смыслы 1:1 плюс «диалог жив». Coverage Python 100%.

### D8. Комментарии Q3b

`_forget_editor`: убрать «with its QGraphicsScene». `sheet_font.py`: убрать «still present until Q3b 3.4» / переходный widgets-canvas.

## Risks / Trade-offs

- [Clip combo] → D5 fallback только после зафиксированной обрезки.
- [Двойной QMessageBox] → D2: фасад молчит на failure.
- [e2e ждут закрытия после Save] → ждать `finished`/`not visible` только после успеха; failure-тесты assert `isVisible()`.
- [Прокси drift vs карточка] → узкий duck-тип; R7 сойдётся на тех же именах.

## Migration Plan

Один merge после R5. Откат — revert. R7 зависит от RelatedSection / ThemeAiButton / finish_saving.

## Open Questions

_(нет)_
