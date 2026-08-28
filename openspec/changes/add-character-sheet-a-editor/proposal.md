# Proposal: add-character-sheet-a-editor

## Why

После A-playable лист можно нарисовать, но без undo, мультиселекта, duplicate и z-order это пытка (20 чекбоксов по одному, закрытый слой не достать). Это последний редакторный срез эпика: инструмент автора. Типы, страницы и схема не расширяются. Дальше по карте — B.

Зависит от [`add-character-sheet-a1`](../add-character-sheet-a1/) и [`add-character-sheet-a-playable`](../add-character-sheet-a-playable/) (применять третьим).

## What Changes

- **BREAKING относительно A1/A-playable:** одновременно можно выделить несколько полей (Shift+клик, рамка мышью).
- Undo/redo: снапшот макета, стек 50; Save стек не чистит; закрытие редактора — стек пустой.
- Snap к сетке 4 pt, по умолчанию выкл; когда вкл — сетка видна; Shift на время жеста снимает snap.
- Z-order: на передний / на задний план в массиве своей страницы.
- Duplicate и copy/paste только внутри приложения.
- Один UI на macOS/Windows/Linux: меню «Правка», `QKeySequence.StandardKey`; snap и z-order — кнопки в панели свойств.
- `schema_version` остаётся 2.

Не входит: JSON импорт/экспорт шаблона, выравнивание, дубль шаблона в списке, группы, новые типы/страницы, PDF, экземпляр, хост.

## Capabilities

### New Capabilities

- (нет)

### Modified Capabilities

- `character-sheet-editor`: мультиселект и жесты рамки; undo/redo; snap; z-order; duplicate и внутренний буфер; меню «Правка» и стандартные клавиши ОС. Требование «не больше одного выделенного поля» снимается.

## Impact

- ViewModel: набор id, стек undo, in-app clipboard, snap flag, z-order mutate array.
- Views: рамка выделения, меню «Правка», тумблер snap и две кнопки z-order в панели; `QAction`+StandardKey.
- Тесты offscreen (жесты, стек, мультиселект). Ручной smoke клавиш на трёх ОС не обязателен в CI — StandardKey.
- `docs/CHANGELOG.md`, `docs/character-sheets-roadmap.md`.
- Без новых runtime-зависимостей и без ALTER.
