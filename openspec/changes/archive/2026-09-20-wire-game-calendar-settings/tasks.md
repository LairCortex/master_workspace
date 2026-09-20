## 1. Домен: имена месяцев и кодек хранения

- [x] 1.1 Перенести словарь григорианских имён месяцев в `app/domain/game_calendar.py` (`DEFAULT_MONTH_NAMES`) и добавить в протокол `GameCalendar` свойство `month_names`; реализовать у `CustomCalendar` (из спеки) и у `StandardCalendar` (переопределение в конструкторе, иначе дефолт); тесты: имена пресета с переопределением, имена кастома из спеки, ключи при переопределении побитово равны ключам без него (spec «Источник имён месяцев»)
- [x] 1.2 Реализовать в `game_calendar.py` кодек `encode_calendar`/`decode_calendar` формата `{"v": 1, "kind": ...}` (custom — поля `CalendarSpec`; standard — опциональные `month_names`; пустой словарь имён нормализуется в «нет поля»); round-trip-тест: сохранённая↔прочитанная спека равны, ключи совпадают; тесты битого JSON, неизвестного `v`, невалидной спеки с причинами (spec «Календарь-настройки хранятся в базе игры», grill D1)
- [x] 1.3 Прогнать `python -m pytest tests/domain` — зелёно, gold-тесты C0/C1 не задеты

## 2. Сервис настроек календаря

- [x] 2.1 Создать `app/application/services/calendar_settings_service.py` с `load_and_apply(session) -> LoadOutcome`: чтение `game_calendar` + миграция `custom_months` по правилам D3 (перенос с удалением старого, эквивалент григорианским именам — не писать, битый старый — удалить без нового, оба ключа — новый побеждает); установка активного календаря через `set_current_calendar`; DB-тесты на все пять сценариев spec «Перенос устаревшей настройки названий месяцев» + «Старая игра без ключа» + «Повторное открытие не переносит»
- [x] 2.2 В `load_and_apply` добавить обработку битого значения: декод не прошёл → активен «Стандартный», в результате — причины для предупреждения, запись в базе не изменена (тест читает строку после загрузки); тест неизвестного `v` идёт тем же путём (spec «Повреждённое значение календарь-ключа», сценарии «Битая кастомная спека» и «Неизвестная версия формата»)
- [x] 2.3 Реализовать `reconcile_era_keys(session)`: по шести `_ERA_TABLES` select всех датированных строк, пересчёт `era_key`, запись только расхождений, один commit; тесты: идемпотентность (второй проход — ноль изменений), починка внешнего вмешательства, совпадение чисел со старой схемой на «Стандарте» (spec «Ключи записей в согласии», три сценария)
- [x] 2.4 Реализовать `apply_to_records(session, calendar, dry_run=True) -> ShiftReport` поверх доменного `build_shift_report` (обход шести таблиц → `ShiftCheck`-ы; применение — сдвиг координат + пересчёт ключей одним commit); тесты: preview не меняет базу и перечисляет ровно невалидные, применение совпадает с preview сценария, ошибка в середине откатывает всё (spec «Применение календаря к записям игры»)

## 3. Пересчёт ключей: удаление SQL-формулы

- [x] 3.1 Удалить `_backfill_era_keys` (и его `julianday/strftime`-формулу) из `app/infrastructure/db/migrations.py`; в `start()` вызывать `reconcile_era_keys` сразу после загрузки календаря; тесты миграции из `test_migrations.py` перевести на python-пересчёт; проверка: `grep -r julianday app/` — пусто

## 4. Представление: имена из календаря

- [x] 4.1 Переписать `app/presentation/utils/date_utils.py`: удалить `_current_months`, `set/get_custom_months`, `months_to_json`, `months_from_json`, `SETTINGS_KEY`; `DEFAULT_MONTHS` — реэкспорт доменного; `month_name` и `format_game_date` читают `current_calendar().month_names`; тесты форматирования: стандарт, переопределение через `set_current_calendar(StandardCalendar(month_names=...))`, эра «г. до н.э.», `fallback`
- [x] 4.2 Перевести `theme_date_popup` (комбо месяцев) на делегат/`current_calendar().month_names`; прогнать `tests/presentation/test_theme_date_popup.py` — зелёно
- [x] 4.3 Заменить подпись ремоделинга в `timeline_viewmodel.py:268` на объект `current_calendar()`; тест: смена календаря-объекта вызывает ремоделинг, повторная раскладка с тем же объектом — нет

## 5. Жизненный цикл приложения

- [x] 5.1 В `Application.start()` заменить `_load_month_settings` на `CalendarSettingsService.load_and_apply` (после `init_db`, до построения VM и `load_events`); при `LoadOutcome` с причинами — ровно одно `QMessageBox.warning`; словарь маппинга кодов → русские фразы + общая фраза для неизвестного кода/версии (тесты маппинга — чистые функции, без Qt)
- [x] 5.2 В `Application.shutdown()` вызывать `reset_current_calendar()`; удалить `_save_month_settings` и `_on_month_settings`; тест-проверка через `grep`: ни одного обращения к `_load_month_settings|_save_month_settings|_on_month_settings` в `app/`
- [x] 5.3 Ручная/e2e-проверка переключения двух игр: у второй — свои имена и порядок, после закрытия активной остаётся пресет (временной тест с двумя БД; spec «Активный календарь в жизненном цикле игры», оба сценария)

## 6. Удаление диалога «Названия месяцев…»

- [x] 6.1 Удалить `month_settings_dialog.py`, `month_settings_view_model.py`, `qml/MonthSettingsRoot.qml`, QAction/пункт «Названия месяцев…», сигнал `month_settings_requested` и его проводку; проверка: `grep -ri "monthsettings\|Названия месяцев" app/` — пусто, окно главного приложения собирается в offscreen-тесте

## 7. Миграция тестов и гейты

- [x] 7.1 Перевести обращения к глобалу в тестах (`test_timeline_rows.py`, `test_application_settings_errors.py`, хелперы `tests/ui/`) на `set_current_calendar(StandardCalendar(month_names=...))`/`reset_current_calendar()`; `test_custom_months.py` переписать на новый API (хранение, миграция, формат) либо удалить вместе с удалённым диалогом; `tests/ui/test_e2e_months.py` — переработать в e2e миграции ключа (открытие игры с `custom_months` → имена в таймлайне) без UI-настройки
- [x] 7.2 `QT_QPA_PLATFORM=offscreen python -m pytest` — весь прогон зелёный; обновить статус C2 в `docs/custom-calendar-roadmap.md` и запись в `docs/CHANGELOG.md` (миграция «через start()», удаление диалога, удаление SQL-бэкфилла)
