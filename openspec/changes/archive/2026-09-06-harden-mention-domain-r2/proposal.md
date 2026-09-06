## Why

Маркеры `@[Имя](тип:id)` разбираются только во views, display-имя не обновляется при rename, клик по событию и по мёртвому id молчит. Кусок R2 (grill 2026-09-05) закрывает Python-гигиену сразу перед R5: грамматика в domain, rewrite в том же commit, что смена имени, живой event-mention открывает EventDialog тем же путём, что dblclick шкалы.

## What Changes

- Qt-нулевой модуль `app/domain/mentions.py`: regex-грамматика, `parse`, `strip_brackets`, `rewrite_display_name(text, type, id, new_name)`. `_MENTION_RE` живёт там; views (и позже R5) импортируют domain, не наоборот. Формат хранения `@[Имя](тип:id)` не меняется.
- Смена `name` у сущности и события: в том же commit LIKE-префильтр `'%(тип:id)%'` по шести колонкам, затем Python-rewrite (id авторитетен). Имя не менялось — скана нет. Rollback save — маркеры не тронуты.
- Вне rewrite: create, delete, xlsx-insert, чар-листы, `music_url`.
- Strip `[`/`]` только при сборке маркера (попавер + rewrite); колонка `name` не чистится; пусто после strip → display `"?"`.
- Живой event-mention → существующий `on_edit_event` (`parent=window`, стек как у карточек). Нет сервиса / нет строки на mention-клике → ровно один `QMessageBox` (один текст, не critical, не statusBar). Шкала при пустом `get_event` остаётся silent.
- QML нет.

## Capabilities

### New Capabilities

- `mentions`: грамматика маркеров, rewrite display при rename, сборка маркера со strip скобок, маршрутизация клика (живой event / живая сущность / мёртвый id).

### Modified Capabilities

_(нет — `ui-testing` уже требует открытия карточки по клику mention сущности; R2 добавляет event/мёртвые id и domain-контракт, не меняя это требование.)_

## Impact

- `app/domain/mentions.py` (новый), `app/presentation/views/mention_text_edit.py` (импорт domain, insert со strip).
- `EventService` / `EntityService` (и при необходимости общий helper) — rewrite в том же commit, что смена `name` на update-with-relations.
- `app/application/wiring.py` + `_wire_mentions_for_dialog` — клик event vs entity vs dead.
- Тесты: юниты domain; сервисный commit/rollback; wiring бокс + event-open; insert без скобок.
- Без QML, без миграций, без правок roadmap/CHANGELOG в этом change.
