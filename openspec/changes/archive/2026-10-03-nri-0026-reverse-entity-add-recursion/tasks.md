# Tasks: nri-0026-reverse-entity-add-recursion

Реверс-спеки: код не меняется; задачи проверяют, что каждая треба отражает фактическое поведение и закреплена тестами.

## 1. Сверка одиночного добавления (entity-addition)

- [x] 1.1 Состав меню «+» (5 пунктов создания + «Типы событий…», типы — канонические ключи реестра) — соответствуют `ADD_MENU_ITEMS` в `app/presentation/views/timeline_island.py` — закреплено `tests/presentation/test_timeline_island.py`
- [x] 1.2 Карточка создания: сохранение одной транзакцией блока работы (`on_add_entity` + `EntityService.create_entity` через `uow.transaction()`), `load_available=False` — кандидаты и дочернее создание не подключаются, обе кнопки секций бездействуют — закреплено `tests/presentation/test_dialogs.py` (состав `get_data`, `test_get_data_includes_related_changes` при пустых секциях)
- [x] 1.3 Сбой записи одиночного создания — один модал, откат, карточка открыта — закреплено `tests/ui/test_e2e_wiring_gaps.py::test_entity_create_failure_rolls_back` (сообщение закрывает `save-error-reporting`)
- [x] 1.4 Неудачное открытие карточки — только журнал, без модала — закреплено `tests/ui/test_e2e_wiring_gaps.py::test_entity_dialog_construction_failure_rolls_back`

## 2. Сверка рекурсивного добавления через связи (related-entity-creation)

- [x] 2.1 Попап «Создать нового» из секций диалога события и карточки; запись попап-сущности сразу при её сохранении — `wiring._open_related_create_dialog`: `create_entity` + `apply_related_changes` в одной `uow.transaction()` — закреплено `tests/ui/test_e2e_events.py::test_create_character_from_event_dialog`, `tests/ui/test_e2e_wiring_gaps.py::test_create_related_entity_from_card`, `tests/presentation/test_sheet_stack_scrim.py` (попап поверх родителя/листа)
- [x] 2.2 Связи самой попап-сущности живут с её сохранения (привязка локации в попапе до сохранения события) — закреплено `tests/ui/test_e2e_events.py::test_link_location_in_character_popup`
- [x] 2.3 Сбой записи в попапе: модал «Ошибка создания сущности», попап открыт, база чиста — закреплено `tests/ui/test_e2e_wiring_gaps.py::test_popup_create_failure_rolls_back_and_notifies`; отсутствие сервиса типа — no-op с `finish_saving(False)` (`test_create_related_without_service_is_noop`)
- [x] 2.4 Отмена родителя удаляет созданные в попапах сущности компенсирующей транзакцией (`_cleanup_popup_entities`, список `_popup_created`) — закреплено `tests/ui/test_e2e_events.py::test_cancel_parent_dialog_after_popup_create`, `tests/ui/test_e2e_wiring_gaps.py::test_popup_cleanup_after_external_rollback`, `test_popup_entity_committed_by_foreign_task_does_not_survive_cancel`
- [x] 2.5 Принятие родителя оставляет всё созданное, в том числе отвязанное (`accepted → _popup_created.pop`) — закреплено `tests/ui/test_e2e_events.py::test_unlink_popup_entity_keeps_entity`
- [x] 2.6 Глубина рекурсии один уровень: попап-карточка строится без подключения `create_related_requested`, привязка существующих в ней доступна (`load_available=True` по умолчанию) — соответствует `wiring._open_related_create_dialog` (комментарий «depth = 1»); прямого теста на бездействие вложенной кнопки нет — зафиксировано в proposal как кандидат на охранник

## 3. Приёмка

- [x] 3.1 `openspec validate nri-0026-reverse-entity-add-recursion --strict` зелёная
- [x] 3.2 Это изменение не правит код: из файлов затронуты только `openspec/changes/nri-0026-reverse-entity-add-recursion/**`; перечисленные закрепляющие тесты прогнаны зелёными
