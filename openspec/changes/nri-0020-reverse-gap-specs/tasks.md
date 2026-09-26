# Tasks: nri-0020-reverse-gap-specs

Реверс-спеки: код не меняется; задачи проверяют, что каждая треба отражает фактическое поведение и закреплена тестами.

## 1. Сверка глобального поиска

- [x] 1.1 Область и поля поиска (реестр типов; название/характеристики/предысторию; lower()) соответствуют `app/application/services/search_service.py` и `BaseRepository.search` — закреплено `tests/application/test_search_service.py`
- [x] 1.2 Порог двух символов, пауза 300 мс, немедленный запуск — соответствуют `SearchViewModel` — закреплено `tests/presentation/test_search_view_model.py`, `tests/presentation/test_search_bar_island.py`
- [x] 1.3 Группировка, заголовки, дата события, «Ничего не найдено», переход по клику — закреплено `tests/presentation/test_search_view_model.py`, `tests/ui/test_e2e_search.py`
- [x] 1.4 Поиск имён для завершения упоминаний — `SearchService.search_names`, потребитель `app/main.py` (упоминания)

## 2. Сверка снимка мира

- [x] 2.1 Дата/эра, «Показать», «Показать всё», «Сброс», исходная подсказка — соответствуют `WorldSnapshotViewModel`
- [x] 2.2 Секции (порядок реестра, счётчики, дефолтное раскрытие), состав (объединение связей, пустые состояния), сортировка — закреплено `tests/presentation/test_world_snapshot_view_model.py`
- [x] 2.3 Видимость статуса (пометка, тонировка, полужирный, превью 24 px, подсказка, «∞»), переход в карточку, статистика, перекраска при смене темы и отписка слушателя — закреплено `tests/presentation/test_world_snapshot_view_model.py`, `tests/presentation/test_world_snapshot_island.py`, `tests/presentation/test_r4_panel_lifecycle.py`

## 3. Сверка сериализации сессии

- [x] 3.1 Замок принадлежит `GameSessionUoW`, все сигнальные задачи идут через `_spawn`/`run_locked`, вложенные `await` замок не берут — соответствуют `app/presentation/wiring.py` — закреплено `tests/infrastructure/test_uow.py`, `tests/ui/test_char_sheets_wiring.py`, `tests/ui/test_e2e_llm.py`

## 4. Приёмка

- [x] 4.1 `openspec validate nri-0020-reverse-gap-specs --strict` зелёная
- [x] 4.2 Это изменение не правит код: из файлов затронуты только `openspec/changes/nri-0020-reverse-gap-specs/**` (в рабочем дереве присутствуют незакоммиченные правки другого не заархивированного изменения — к этому они отношения не имеют); перечисленные закрепляющие тесты прогнаны зелёными (82 passed)
