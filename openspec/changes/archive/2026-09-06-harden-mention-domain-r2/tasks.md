## 1. Domain-тесты (падают)

- [x] 1.1 Юниты `parse`: `@[Алиса](character:42)` → display/type/id; несколько маркеров и хвост текста — `tests/domain/test_mentions.py` падает (модуля ещё нет)
- [x] 1.2 Юниты `strip_brackets` / `rewrite_display_name`: скобки вырезаются; пусто → `?`; rewrite по type+id при любом старом display; чужой id и не-маркеры нетронуты — тесты падают

## 2. Domain-реализация

- [x] 2.1 Добавить `app/domain/mentions.py` (`_MENTION_RE`, `parse`, `strip_brackets`, `rewrite_display_name`) без Qt/SQL — юниты 1.1–1.2 зелёные
- [x] 2.2 `mention_text_edit.py` импортирует regex/`parse` из domain, локальный `_MENTION_RE` убран; `tests/presentation/test_mention_text_edit.py` зелёный

## 3. Сервисные тесты (падают)

- [x] 3.1 `update_entity_with_relations` / `update_event_with_relations`: смена `name` переписывает маркер во всех шести колонках в том же commit — тест падает
- [x] 3.2 То же имя → скана/LIKE нет (spy/счётчик запросов или неизменный текст при «похожем» LIKE-мусоре) — тест падает
- [x] 3.3 Сбой `commit` после rewrite → rollback, маркеры старые; create/xlsx-путь не вызывает rewrite — тесты падают

## 4. Сервисная реализация

- [x] 4.1 Хелпер LIKE `'%(тип:id)%'` + `rewrite_display_name` на сессии без своего commit (`mention_rewrite.py` или эквивалент) — юнит хелпера на in-memory session зелёный
- [x] 4.2 Вызов из `update_entity_with_relations` и `update_event_with_relations` только при смене `name`, до commit — тесты 3.1–3.3 зелёные

## 5. Wiring-тесты (падают)

- [x] 5.1 Живой event-mention → `EventDialog` через существующий `on_edit_event` (`parent=window`) — тест падает
- [x] 5.2 Мёртвый id и неизвестный тип: ровно один `QMessageBox.warning`, один текст, 0 `critical`, statusBar не тронут — тесты падают
- [x] 5.3 Dblclick шкалы при пустом `get_event`: ни warning, ни critical — тест падает
- [x] 5.4 `_insert_mention` с именем со скобками: `getContent` без `[`/`]` в display — тест падает

## 6. Wiring и вставка

- [x] 6.1 Обёртка mention-клика в `_wire_mentions_for_dialog` / wiring (event → get+`on_edit_event` или бокс; сущность → get+`on_entity_click` или бокс); `on_edit_event` шкалы без изменений — тесты 5.1–5.3 зелёные
- [x] 6.2 `_insert_mention` собирает display через `strip_brackets` — тест 5.4 зелёный

## 7. Проверка

- [x] 7.1 `QT_QPA_PLATFORM=offscreen python -m pytest` зелёный; grep: `_MENTION_RE` только в `domain/mentions.py`; нет QML в diff
