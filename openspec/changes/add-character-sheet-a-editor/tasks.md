# Tasks: add-character-sheet-a-editor

Делать **после** A1 и A-playable. TDD. `QT_QPA_PLATFORM=offscreen python -m pytest`. Без сети. Типы/страницы/schema не расширять.

## 1. ViewModel: undo и выделение

- [ ] 1.1 Тесты VM: стек 50, redo чистится новой операцией, save не чистит стек, закрытие/новый шаблон — стек пуст; undo после move; инлайн-коммит = один шаг, Esc инлайна не оставляет лишний undo. Проверка: `tests/presentation/test_character_sheet_viewmodel.py` красные до 1.2.
- [ ] 1.2 Снапшот-undo в VM (D1). Проверка: тесты 1.1 зелёные.
- [ ] 1.3 Тесты мультиселекта: click replace, Shift toggle, selected_ids; move набора одним delta + clamp/relocate; delete набора; ресайз запрещён при len≠1. Проверка: красные до 1.4.
- [ ] 1.4 `selected_ids` и операции набора (D2). Проверка: тесты 1.3 зелёные.

## 2. Snap и z-order

- [ ] 2.1 Тесты: snap выкл по умолчанию; вкл → координаты кратны 4 после place/move; Shift на жесте без snap; флаг не пишется в JSON шаблона. Проверка: красные до 2.2.
- [ ] 2.2 Snap + отрисовка сетки при флаге (D3). Проверка: тесты 2.1 зелёные.
- [ ] 2.3 Тесты: bring to front / send to back меняют порядок массива страницы; набор — каждое на своей странице; один undo-шаг. Проверка: красные до 2.4.
- [ ] 2.4 Z-order в VM (D4). Проверка: тесты 2.3 зелёные.

## 3. Duplicate и буфер

- [ ] 3.1 Тесты: duplicate новый id, +8,+8, та же страница, image_id тот же; paste на текущую страницу рейки; набор сохраняет смещения; в системный clipboard ничего не кладём (нет `QClipboard.setText` макета). Проверка: красные до 3.2.
- [ ] 3.2 Clipboard в VM (D5). Проверка: тесты 3.1 зелёные.

## 4. Жесты канваса и меню

- [ ] 4.1 Тесты view: рамка с пустого выделяет пересечения; рамка без Shift заменяет; Shift+рамка добавляет; press на выбранном поле начинает move, не рамку. Проверка: `tests/presentation/test_character_sheet_canvas.py` красные до 4.2.
- [ ] 4.2 Rubber band + жесты (D2). Проверка: тесты 4.1 зелёные.
- [ ] 4.3 Тесты: меню «Правка» с пятью пунктами; Undo/Redo/Copy/Paste завязаны на `QKeySequence.StandardKey`; Duplicate — `Ctrl+D` (Qt Cmd+D на mac). Проверка: `tests/presentation/test_character_sheet_editor_dialog.py` зелёный после 4.4.
- [ ] 4.4 Меню + панель: тумблер snap, кнопки z-order (D6). Проверка: тесты 4.3 зелёные.

## 5. Интеграция

- [ ] 5.1 E2E: выделить два поля рамкой → duplicate → undo → save. Проверка: `tests/ui/test_e2e_char_sheets.py` дополнен, зелёный.
- [ ] 5.2 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь набор зелёный.
- [ ] 5.3 `docs/CHANGELOG.md` (undo, мультиселект, snap, z-order, duplicate; незавершено); в `docs/character-sheets-roadmap.md` A-editor = план этого change, A для эпика закрыт. Проверка: `openspec validate add-character-sheet-a-editor --strict` зелёный.
