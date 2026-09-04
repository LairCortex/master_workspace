# Tasks: fix-silent-dialog-save-debt

## 1. Тесты на желаемое поведение (падают первыми)

- [x] 1.1 Юниты сервисов: `create_event_with_relations` / `update_event_with_relations` (`tests/` тесты EventService) — сбой commit'а: исключение пробрасывается, `rollback` ровно один; `update_event_with_relations` с отсутствующим событием — `ValueError`, без `AttributeError`.
- [x] 1.2 Юнит `update_entity_with_relations` (EntityService) — та же тройка ожиданий.
- [x] 1.3 Wiring-тесты четырёх путей (create-событие, edit-событие, update-сущности, solo-create): фейковый сервис с `RuntimeError`, spy на `QMessageBox.critical` — ровно один вызов, в тексте причина; существующие success-тесты не сломаны.
- [x] 1.4 Тест «сессия жива после сбоя»: провальное сохранение → успешное сохранение другой записи (in-memory fixture).

## 2. Сервисы перестают молчать

- [x] 2.1 `EventService.create_event_with_relations`: `except` → rollback + `raise`; убрать `return None`, обновить docstring (проброс вместо silent None).
- [x] 2.2 `EventService.update_event_with_relations`: то же; явная проверка `updated_event is None` → `ValueError(f"событие {event_id} не найдено")` до `refresh`.
- [x] 2.3 `EntityService.update_entity_with_relations`: то же; docstring синхронно.

## 3. Wiring показывает ошибку

- [x] 3.1 `on_saved` (создание события): try/except вокруг `create_event_with_relations`; в except — `_reload_timeline()` + `QMessageBox.critical("Ошибка", "Не удалось сохранить событие: {exc}")` (перезагрузка до модалки, как в `on_event_dates_moved`).
- [x] 3.2 `on_event_updated` (правка события): аналогично; вexcept — перезагрузка ленты, без показа «обновлённой» детали в панель.
- [x] 3.3 `on_entity_saved` в `on_entity_click` (обновление сущности): аналогично, текст «Не удалось сохранить сущность».
- [x] 3.4 `on_entity_saved` в `on_add_entity` (создание из «+»): вместо голого `except: rollback` — тот же паттерн, текст «Не удалось создать сущность»; внешний except-«диалог не открылся» (:327-328) остаётся Rollback+лог без модалки, комментарием зафиксировать отличие путей.

## 4. Проверка и фиксация

- [x] 4.1 Полный `python -m pytest` зелёный (offscreen); гейт покрытия 100% не просел.
- [x] 4.2 Ручная сверка формулировок: тексты модалок совпадают со специкой `save-error-reporting`; ни один из четырёх путей не молчит (grep-инспекция final-кода трёх `*_with_relations`).
- [x] 4.3 CHANGELOG: запись о закрытии долга W5 по диалог-пути (пометка: эпик Q открыт). Текст Q2.5 в `docs/design-system-roadmap.md` правит change переезда шкалы (одно переписывание секции, не два).
