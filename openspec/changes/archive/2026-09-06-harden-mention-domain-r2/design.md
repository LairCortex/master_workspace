## Context

См. proposal.md — Why. Формат `@[Имя](тип:id)` остаётся. Сейчас `_MENTION_RE` и конвертеры живут в `mention_text_edit.py`; `html_to_mentions` собирает display из фрагмента без strip; `_insert_mention` вставляет `data["name"]` как есть. `on_entity_click` для неизвестного типа и пустой строки молча `return`. Event-mention идёт туда же (`_get_entity_service("event")` → None → тишина). `on_edit_event` при пустом `get_event` уже silent — это путь шкалы, его не меняем. Update имени: `update_event_with_relations` / `update_entity_with_relations` (create/xlsx/delete не трогаем). Шесть колонок — `descriptions.characteristics`/`backstory`, `characters.personality`, `tasks` у character/organization/location. QML в R2 нет.

## Goals / Non-Goals

**Goals:**
- Одна qt-нулевая грамматика в domain; views импортируют её.
- Rewrite display в том же commit, что смена `name`; rollback откатывает и маркеры.
- Клик: живой event → существующий `on_edit_event`; живая сущность → существующий `on_entity_click`; мёртвый — один warning-бокс.

**Non-Goals:**
- Смена формата, QML/`MentionField` (R5), чистка сырого storage в поиске/detail/LLM.
- Rewrite при create/delete/xlsx/чар-листах/`music_url`.
- Чистка колонки `name`. Снятие «не закрывать диалог при провале» (R6/R7).
- Roadmap/CHANGELOG (планирование отдельно от apply-доков эпика).

## Decisions

### D1. Domain-модуль без Qt и без SQL

`app/domain/mentions.py`: `_MENTION_RE` (тот же шаблон `r"@\[([^\]]+)\]\((\w+):(\d+)\)"`), `parse(text)` → последовательность совпадений (display, type, id, span), `strip_brackets(name) -> str`, `rewrite_display_name(text, type, id, new_name) -> str`.

`strip_brackets`: удалить все `[` и `]`, затем `strip()`; пусто → `"?"`. Вызывается только при сборке маркера: попавер (`_insert_mention`) и rewrite (новый display). `html_to_mentions` по-прежнему берёт видимый текст якоря — это не сборка из `name`.

`rewrite_display_name`: для каждого parse-совпадения с данным type+id подставить `@[{strip_brackets(new_name)}]({type}:{id})`; остальные куски текста байт-в-байт. Id авторитетен: старый display любой, в том числе рассинхрон и `"?"`.

`mentions_to_html` / клик-href остаются во views; итерация маркеров — через `parse`, не второй regex. Views импортируют domain; domain не импортирует presentation.

Альтернатива «оставить regex во views, domain только rewrite» отклонена: R5 должен брать ranges из того же модуля.

### D2. Rewrite-хелпер в application, вызов из двух update-with-relations

Отдельный async-хелпер на сессии (например `app/application/services/mention_rewrite.py`), не метод domain: SQL не должен течь в domain. Сигнатура: `(session, entity_type: str, entity_id: int, new_name: str) -> None` — LIKE + Python rewrite in-place на найденных строках, без собственного commit.

Вызов: `EventService.update_event_with_relations` и `EntityService.update_entity_with_relations` **после** мутации полей, **до** `commit`, только если новое `name` отличается от имени в базе на входе в update (снимок до `update_*`). Сравнение — точное равенство строк `name`, без дополнительной нормализации. Имя не менялось → хелпер не звать (скана нет).

LIKE-префильтр: `'%(' + type + ':' + str(id) + ')%'` по шести колонкам (четыре запроса достаточно: `DescriptionModel` OR по двум полям; `CharacterModel` personality/tasks; `OrganizationModel.tasks`; `LocationModel.tasks`). Затем `rewrite_display_name` на каждом ненулевом поле-кандидате и запись обратно. Ложные LIKE (подстрока в обычном тексте) безвредны: Python не тронет не-маркеры.

Create/`create_event_with_relations`/`xlsx`/`delete`/`update_event` без смены имени (drag дат) хелпер не вызывают. `music_url` не в списке колонок.

Альтернатива «триггер SQLite» отклонена: грамматика и `"?"` должны жить в Python. Альтернатива «скан всех колонок всегда» отклонена grill'ом.

### D3. Rollback = та же транзакция, что save

Хелпер не коммитит. Сбой `commit` / `raise` + `rollback` в `*_with_relations` откатывает и имя, и маркеры. Отдельный commit rewrite запрещён.

### D4. Маршрутизация клика в wiring, шкала не трогается

Обёртка вокруг нынешнего `dialog.mention_clicked` / `_wire_mentions_for_dialog`:

1. Тип `event`: `event_service.get_event(id)`; есть строка → `on_edit_event(id)` как есть (`parent=window`); нет → мёртвый бокс.
2. Иначе: сервис типа есть и `get_entity` вернул строку → `on_entity_click`; нет сервиса или нет строки → тот же бокс.

`on_edit_event` и dblclick шкалы не менять: пустой `get_event` остаётся silent. Не звать `on_edit_event` с мёртвым id с mention-пути — иначе бокс не покажется.

Бокс: ровно один `QMessageBox.warning` (не `critical`, не `information`+statusBar). Один общий текст на оба мёртвых случая (нет сервиса / нет строки), parent=`window`. Spy в тестах — `warning`, 0 вызовов `critical` на этом пути.

Альтернатива «прокинуть event в `on_entity_click`» отклонена: карточка события не существует, нужен уже принятый `on_edit_event`.

### D5. TDD-слои

Сначала падающие тесты, потом код.

- Domain: parse; rewrite по type+id при чужом display; strip/`?`; не-маркеры нетронуты.
- Сервис: смена имени → LIKE+rewrite в том же commit; то же имя → 0 LIKE; искусственный сбой commit после rewrite → rollback, маркеры старые.
- Wiring: живой event-mention открывает EventDialog через `on_edit_event`; мёртвый — один `warning`; dblclick шкалы при пустом `get_event` — без бокса.
- Insert: попавер/insert с именем со скобками → storage без `[`/`]` в display.

Существующие round-trip `test_mention_text_edit` остаются зелёными (импорт regex из domain).

## Risks / Trade-offs

- [LIKE ловит подстроки вне маркеров] → Python-rewrite идемпотентен на не-совпадениях parse; лишние чтения дешёвы на SQLite.
- [Warning на mention блокирует session lock, как critical на save] → тот же паттерн `_spawn`; пользователь не кликает параллельно.
- [Старые маркеры со скобками в display] → чистятся при следующем rewrite этой цели; insert новых — сразу без скобок.
- [Имя сменилось только пробелами] → точное сравнение не сканирует; принято (grill: «имя не менялось»).

## Migration Plan

Миграций схемы нет. Откат изменения — revert коммита; маркеры в уже переписанных играх остаются с новым display (формат тот же).

## Open Questions

_(нет)_
