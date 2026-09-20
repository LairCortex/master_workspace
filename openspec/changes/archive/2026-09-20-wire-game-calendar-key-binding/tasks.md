# Tasks: wire-game-calendar-key-binding

Решения grill 2026-09-19. Реальный запуск = «Стандартный», ветка кастома проверяется подменой accessor; колонки БД, миграции и `main.py` не трогаем.

Порядок правки 2026-09-19 (до apply): группа 1 не выполнима без дефолтного accessor, а `era_key` из группы 1 ломает импорт `game_calendar` (модульные `_AD_FIRST_KEY`/`_AD_LAST_KEY`). Поэтому дефолтный `_current_calendar` + `current_calendar()` перенесены в 1.1, переключение `_AD_*` — в 1.2, а `set/reset` остались в 2.2. Гейты pytest для 1.1 и 1.2 прогоняются один раз после обеих правок (на промежуточном шаге `era_key` рекурсивно зовёт саму себя).

## 1. Приватная формула, диспетчер ключа и дефолтный accessor

- [x] 1.1 `app/domain/date_era.py`: действующую формулу вынести в приватную `_gregorian_key(d, is_bc)`; `era_key(d, is_bc)` оставить публичной с прежней сигнатурой, тело — ленивый импорт `current_calendar` из `app.domain.game_calendar` и возврат `to_key(MonthDay(d.year, d.month, d.day), is_bc)`. `cmp_era_dates`/`assert_range` не трогать. В `app/domain/game_calendar.py` добавить модульный `_current_calendar: GameCalendar = StandardCalendar()` и `current_calendar()` ВЫШЕ модульных констант `_AD_FIRST_KEY`/`_AD_LAST_KEY` (`set_current_calendar`/`reset_current_calendar` — задача 2.2). Правки 1.1 и 1.2 проверяются одним прогоном: `python -m pytest tests/domain/test_date_era.py tests/domain/test_game_calendar.py -q` — зелёный (дефолт-Стандартный даёт прежние числа).
- [x] 1.2 `app/domain/game_calendar.py`: `StandardCalendar.to_key`/`from_key` переключить на импорт `_gregorian_key` вместо `era_key`, убрав взаимную рекурсию; там же модульные `_AD_FIRST_KEY`/`_AD_LAST_KEY` вычислять через `_gregorian_key`, иначе импорт модуля падает на частично инициализированном `game_calendar`. Тот же прогон что в 1.1 — зелёный, золото «Стандартного» (`test_std_matches_era_key` и др.) не сдвинулось.
- [x] 1.3 Проверить отсутствие цикла загрузки: `python -c "import app.domain.date_era, app.domain.game_calendar"` без ошибок.

## 2. Accessor активного календаря

- [x] 2.1 Тесты: дефолт accessor == Стандартный и `era_key(d)` == `_gregorian_key(d)`; после `set_current_calendar(CustomCalendar(spec))` ключ меняется по кастому (сверка с `CustomCalendar` напрямую); после `reset_current_calendar()` — снова Стандартный. (Красные.)
- [x] 2.2 Реализовать `_current_calendar` + `current_calendar`/`set_current_calendar`/`reset_current_calendar` (без блокировок, комментарий про единый цикл событий qasync). Зелёные 2.1; `python -m pytest tests/domain -q` зелёный.

## 3. Чистый предикат и сдвиг невалидных координат

- [x] 3.1 Табличные тесты предиката/сдвига: переполнение дня, месяц вне числа месяцев, номер вставного дня вне списка (clamp) — ожидаемая координата и код причины. (Красные.)
- [x] 3.2 Реализовать `classify`/`shift_invalid` поверх протокола по D4 (ровно три причины; валидная на входе → без изменения; год вне диапазона — не причина сдвига, остаётся `InvalidGameDateError` из ядра). Зелёные 3.1.
- [x] 3.3 Свойства: идемпотентность (повтор не двигает, пустой результат); допустимость столкновения (две координаты → одна); эра сохраняется и не влияет валидность/сдвиг. Зелёные.

## 4. Форма отчёта о переносе

- [x] 4.1 Тест: пустой отчёт на валидных координатах (ноль записей, нулевой счётчик); форма записи (`table`/`row_id`/`field`/`old`/`new`/`reason`) сдвинутого `start`; отсутствие имён/подписей в записи. (Красные.)
- [x] 4.2 Реализовать frozen-датакласс записи отчёта + стабильные коды причин; чистые функции могут возвращать список записей для вызывающего обхода (БД не читают). Зелёные 4.1.

## 5. Проверка отсутствия побочных эффектов и приёмка

- [x] 5.1 Вызывающие `era_key` файлы не правились; ключ на реальном запуске совпадает: `python -m pytest tests/infrastructure/test_migrations.py tests/infrastructure/test_models.py tests/infrastructure/test_repositories.py -q` (сверка `julianday == era_key`, round-trip ключей хука — без изменений). Полный `QT_QPA_PLATFORM=offscreen python -m pytest -q` зелёный.
- [x] 5.2 Ревью дельта-спека: у каждого сценария секции ADDED в `specs/game-calendar-core/spec.md` есть зелёный тест (таблица «сценарий → тест» в описании коммита). Проверить `openspec validate "wire-game-calendar-key-binding" --strict`. Статус куска C1 в `docs/custom-calendar-roadmap.md` обновить по закрытию (после применения).
