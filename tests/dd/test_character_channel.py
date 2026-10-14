"""Канал персонажа: содержательная часть, склейки и разрешение ссылок
(add-dnd-lss-generation, task 6.1; spec dnd-generation «Генерация персонажа
с нуля», «Дозаполнение персонажа», «Числовая механика остаётся LSS»).

Канал проверяется с ЖИВЫМ ``CharacterValidatorService``: конверт достраивает
приложение, из ответа живёт только содержательная часть (числовые механики
отбрасываются до валидации, служебные ключи — тоже), пре-выборы соблюдаются
поверх ответа, неразрешимый slug — ошибка круга, уходящая в обратную связь;
круг на стаб-провайдере — та же поза группы 1 (``make_llm_answer`` +
``httpx.MockTransport``).
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.dd.application.character_channel import (
    CAPTION_LEVEL,
    CAPTION_NAME,
    CAPTION_SPELLS,
    CODE_CHAR_REF_UNRESOLVED,
    CODE_CHAR_SPELL_SLUG_UNRESOLVED,
    MECHANIC_KEYS,
    SLOT_CAPTIONS,
    TOP_UP_NOTHING_REFUSAL,
    CharacterChannel,
    CharacterContext,
    parse_top_up_current,
    top_up_missing_fields,
)
from app.dd.application.character_validator_service import CharacterValidatorService
from app.dd.application.generation_loop import make_llm_answer, run_rounds
from app.dd.application.prompt_composer import PromptComposer, SlugVocabularyEntry
from app.dd.domain.character import LEVEL_REFUSAL
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig
from app.infrastructure.llm.remote_provider import (
    OUTPUT_BUDGET_SHARE,
    PROBE_MAX_OUTPUT_TOKENS,
    RemoteLlmProvider,
)

# ── фикстуры словаря и ответа ─────────────────────────────────────────────────

_VOCABULARY = (
    SlugVocabularyEntry("srd", "Elf", "Эльф"),
    SlugVocabularyEntry("srd", "HighElf", "Высший эльф"),
    SlugVocabularyEntry("srd", "Fighter", "Воин"),
    SlugVocabularyEntry("srd", "BattleMaster", "Боевой мастер"),
    SlugVocabularyEntry("srd", "GuildArtisan", "Гильдейский ремесленник"),
)
_RECORD_IDS = tuple(entry.slug for entry in _VOCABULARY)
_SPELL_SLUGS = ("fire-ball", "mending")


def _context(**over) -> CharacterContext:
    kwargs: dict = dict(
        world="Мир пепла и ветров",
        concept="следопыт-разведчик",
        vocabulary=_VOCABULARY,
        record_ids=_RECORD_IDS,
        spell_slugs=_SPELL_SLUGS,
    )
    kwargs.update(over)
    return CharacterContext(**kwargs)


def _content(**over) -> dict:
    """Содержательная часть типового ответа: sample-подобный персонаж из
    few-shot-набора канала."""
    data = {
        "name": "Мариссель Тал",
        "level": 3,
        "info": {
            "race": {"id": "Elf", "name": "Эльф"},
            "charClass": {"id": "Fighter", "name": "Воин"},
        },
        "blocks": {"Внешность": "Прямая спина, седина рано тронула виски."},
        "spells": {"list": ["fire-ball"]},
    }
    data.update(over)
    return data


def _answer(**over) -> str:
    return json.dumps(_content(**over), ensure_ascii=False)


def _data_of(document: str) -> dict:
    envelope = json.loads(document)
    assert envelope["jsonType"] == "character"
    assert isinstance(envelope["version"], str) and envelope["version"]
    assert isinstance(envelope["data"], str)
    return json.loads(envelope["data"])


class _ScriptedAsk:
    """Стаб-ответ канала той же формы, что у группы 1."""

    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.users: list[str] = []

    async def __call__(self, system_prompt, user_prompt, on_phase=None):
        self.users.append(user_prompt)
        return self.answers.pop(0)


# ── промпт канала: слои Д3 + канал-специфичные входы ──────────────────────────


def test_prompt_scratch_adds_name_line_spell_shape_and_preselects():
    composer = PromptComposer()
    context = _context(level=3, race=_VOCABULARY[0], char_class=_VOCABULARY[2])
    channel = CharacterChannel(context)

    system, user = channel.build_prompt(context)

    base_system, base_user = composer.compose_character(
        context.world, context.concept, context.vocabulary
    )
    assert system == base_system  # слои Д3 нетронуты
    assert user.startswith(base_user)
    assert "Пре-выборы мастера, обязательные к соблюдению" in user
    assert "- Уровень: 3" in user
    assert "Вид: Elf («Эльф»)" in user
    assert "Класс: Fighter («Воин»)" in user
    assert "Имя персонажа обязательно" in user
    assert '"spells": {"list"' in user
    # без пре-выборов блок пре-выборов не печатается (spec: всё опционально)
    _, plain_user = CharacterChannel(_context()).build_prompt(_context())
    assert "Пре-выборы мастера" not in plain_user


def test_prompt_top_up_carries_current_document_and_missing_fields():
    current = json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": {"name": "Грог", "level": 5},
        },
        ensure_ascii=False,
    )
    context = _context(concept="", current_document=current)
    channel = CharacterChannel(context)

    _system, user = channel.build_prompt(context)

    assert "Текущий документ персонажа" in user
    assert '"level": 5' in user
    missing_line = user.split("Дозаполни только пустые поля: ")[1].split(".")[0]
    assert set(missing_line.split(", ")) == {
        SLOT_CAPTIONS["race"],
        SLOT_CAPTIONS["subrace"],
        SLOT_CAPTIONS["class"],
        SLOT_CAPTIONS["subclass"],
        SLOT_CAPTIONS["background"],
        CAPTION_SPELLS,
    }
    assert CAPTION_LEVEL not in missing_line  # заполненное в список не попало


# ── parse: конверт достраивает приложение, содержимое — из ответа ─────────────


def test_parse_builds_live_envelope_from_content_part():
    channel = CharacterChannel(_context())
    document = channel.parse("```json\n" + _answer() + "\n```")  # fence прощается
    data = _data_of(document)
    assert data["name"] == "Мариссель Тал"
    assert data["level"] == 3
    assert data["info"]["race"] == {"id": "Elf", "name": "Эльф"}
    assert data["blocks"]["Внешность"].startswith("Прямая спина")
    assert data["spells"] == {"list": ["fire-ball"]}
    report, parsed = CharacterValidatorService().validate(document)
    assert [f"{i.path}: {i.message}" for i in report.errors] == []
    assert parsed is not None


def test_mechanic_keys_never_reach_the_document_or_the_validator():
    """Spec «Числовая механика остаётся LSS» + дельта dd-card-redesign:
    модель протащила все механические ключи (восемь числовых + speed/
    alignment/feats) + счётчик spells.slots + служебные ключи — в документ и
    к валидатору не попадает ничего (ни ошибок, ни предупреждений)."""
    smuggled = _content(
        avatar="Портрет кисти мастера",
        stats={"str": {"value": 17}},
        skills={"stealth": {"proficient": True}},
        bonuses=[{"target": "ac", "value": 1}],
        bonusesSkills={"stealth": 2},
        bonusesStats={"str": 1},
        weaponsList=[{"name": "Короткий меч"}],
        resources=[{"name": "Стрелы", "value": 12}],
        coins={"gp": 25},
        speed=40,
        alignment="хаотично-злой",
        feats=[{"id": "lucky"}],
        wizardStep=4,
        choices={"feat": "Alert"},
    )
    smuggled["spells"]["slots"] = [{"level": 1, "value": 2}]
    assert set(MECHANIC_KEYS) <= set(smuggled)  # все одиннадцать действительно были

    document = CharacterChannel(_context()).parse(
        json.dumps(smuggled, ensure_ascii=False)
    )
    data = _data_of(document)

    for key in MECHANIC_KEYS:
        assert key not in data
    assert data["avatar"] == "Портрет кисти мастера"  # содержательное — живёт
    assert data["spells"] == {"list": ["fire-ball"]}  # slots отброшен
    assert "wizardStep" not in data and "choices" not in data
    report, _parsed = CharacterValidatorService().validate(document)
    assert report.issues == ()


def test_parse_drops_garbage_shapes_and_keeps_tolerable_drift():
    """Slug-строка вместо словаря терпится, level-3.0 и пустые значения — нет;
    голый массив слагами — законная форма раздела spells."""
    drift = {
        "name": "  Тал  ",
        "level": 3.0,
        "info": {"race": "Elf", "charClass": {"id": " ", "name": ""}, "feats": "мусор"},
        "blocks": {
            "Пусто": "   ",
            "Имя": "",
            "": "имя пустое",
            "Число": 42,
            "Живой": {"type": "doc", "content": []},
        },
        "spells": ["fire-ball", "fire-ball", "mending", 42, " "],
    }
    data = _data_of(
        CharacterChannel(_context()).parse(json.dumps(drift, ensure_ascii=False))
    )
    assert data == {
        "name": "Тал",
        "info": {"race": {"id": "Elf"}},
        "spells": {"list": ["fire-ball", "mending"]},
    }


def test_non_object_sections_are_dropped_wholesale():
    raw = {"name": "Тал", "info": "мусор", "blocks": 42, "spells": "слаг не строкой"}
    data = _data_of(
        CharacterChannel(_context()).parse(json.dumps(raw, ensure_ascii=False))
    )
    assert data == {"name": "Тал"}


def test_parse_refuses_non_object_answers():
    channel = CharacterChannel(_context())
    with pytest.raises(ValueError, match="не содержит JSON-документа"):
        channel.parse("извините, я не умею JSON")
    with pytest.raises(ValueError, match="не является JSON-объектом содержательной части"):
        channel.parse('[{"name": "список вместо объекта"}]')


def test_preselects_override_the_answer():
    """Spec scenario «Пре-выбор класса соблюдён»: что бы модель ни написала,
    в документ идут отмеченные мастером уровень/вид/класс."""
    context = _context(level=5, race=_VOCABULARY[0], char_class=_VOCABULARY[2])
    document = CharacterChannel(context).parse(
        _answer(level=7, info={"race": {"id": "HighElf", "name": "Высший эльф"}})
    )
    data = _data_of(document)
    assert data["level"] == 5
    assert data["info"]["race"] == {"id": "Elf", "name": "Эльф"}
    assert data["info"]["charClass"] == {"id": "Fighter", "name": "Воин"}


def test_preselect_name_snapshot_falls_back_to_the_slug():
    choice = SlugVocabularyEntry("srd", "Fighter", "")
    document = CharacterChannel(_context(char_class=choice)).parse(_answer())
    assert _data_of(document)["info"]["charClass"] == {
        "id": "Fighter",
        "name": "Fighter",
    }


# ── validate: живой валидатор + разрешение ссылок канала ──────────────────────


def _validate(answer: str, **over) -> tuple[CharacterChannel, str]:
    context = _context(**over)
    channel = CharacterChannel(context)
    return channel, channel.parse(answer)


def test_validate_hands_a_broken_document_straight_through():
    """Документ, который живой валидатор не смог разобрать, возвращается как
    есть — разрешать нечего."""
    report = CharacterChannel(_context()).validate("не json")
    assert [i.code for i in report.errors] == ["INVALID_JSON"]


def test_unresolvable_class_slug_is_an_error():
    channel, document = _validate(_answer())
    assert channel.validate(document).errors == ()

    broken = _content(
        info={"race": {"id": "Elf", "name": "Эльф"}, "charClass": {"id": "Necromancer"}}
    )
    channel, document = _validate(json.dumps(broken, ensure_ascii=False))
    errors = channel.validate(document).errors
    assert [i.code for i in errors] == [CODE_CHAR_REF_UNRESOLVED]
    assert "data.info.charClass.id" in errors[0].path
    assert "Necromancer" in errors[0].message


def test_unresolvable_spell_slug_is_an_error_and_none_is_silent():
    unknown = json.dumps(
        _content(spells={"list": ["power-word-kill"]}), ensure_ascii=False
    )
    channel, document = _validate(unknown)
    errors = channel.validate(document).errors
    assert [i.code for i in errors] == [CODE_CHAR_SPELL_SLUG_UNRESOLVED]
    assert "data.spells.list[0]" in errors[0].path

    silent = CharacterChannel(_context(spell_slugs=None))
    assert silent.validate(silent.parse(unknown)).errors == ()


def test_unresolvable_snapshot_with_empty_id_is_legal_and_bare_name_is_schema_error():
    """Пустой id — законный ответ «имя помним, ссылку подтвердить нечем»
    (датасет снят — не ошибка); name-без-id ловит живая схема (required id)."""
    snapshot = json.dumps(
        _content(info={"race": {"id": "", "name": "Драконид"}}), ensure_ascii=False
    )
    channel, document = _validate(snapshot)
    assert channel.validate(document).errors == ()

    nameless = json.dumps(
        _content(info={"race": {"name": "Драконид"}}), ensure_ascii=False
    )
    channel, document = _validate(nameless)
    assert [i.code for i in channel.validate(document).errors] == ["SCHEMA"]


# ── круг целиком: стаб-провайдер + живой валидатор (поза группы 1) ────────────


def _provider(handler):
    http = AppHttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    config = LlmConfig(base_url="https://llm.test/v1", model="test-model")
    return RemoteLlmProvider(config, http, backoffs=(0.0, 0.0)), http


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_round_on_stub_provider_fixes_unresolvable_slug_with_live_validator():
    """Spec «Неразрешимая ссылка — ошибка круга»: первый ответ с классом вне
    словаря отклонён живым валидатором, ошибка ушла в обратную связь, второй
    ответ проходит, документ — готовый конверт."""
    first = _content(info={"charClass": {"id": "Necromancer", "name": "Некромант"}})

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if payload["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS:
            return _ok("проба")  # дешёвая проба бюджета вывода принимается
        if len(calls) == 2:
            return _ok(json.dumps(first, ensure_ascii=False))
        return _ok("```json\n" + _answer() + "\n```")

    provider, http = _provider(handler)
    context = _context(level=3)
    try:
        result = await run_rounds(
            CharacterChannel(context), context, make_llm_answer(provider)
        )
    finally:
        await http.close()

    assert result.ok
    assert result.attempts == 2
    # вызовы штатные: сначала проба бюджета, живой запрос — с мышлением и бюджетом
    assert calls[0]["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS
    assert calls[1]["chat_template_kwargs"] == {"enable_thinking": True}
    assert calls[1]["max_tokens"] == int(PROBE_MAX_OUTPUT_TOKENS * OUTPUT_BUDGET_SHARE)
    feedback = calls[2]["messages"][1]["content"]
    assert CODE_CHAR_REF_UNRESOLVED in feedback
    assert "Necromancer" in feedback
    data = _data_of(result.document or "")
    assert data["level"] == 3  # пре-выбор дожил до финального документа
    assert data["info"]["charClass"] == {"id": "Fighter", "name": "Воин"}


# ── дозаполнение: гейт, текущий документ, склейка с защитой непустого ─────────


def _current_document(**over) -> str:
    """Полностью заполненный документ (эталон гейта «пусто дозаполнять»);
    ``over`` вырезает поля, оставляя что дозаполнить."""
    data = {
        "name": "Грог",
        "level": 5,
        "info": {
            "race": {"id": "Elf", "name": "Эльф"},
            "subrace": {"id": "HighElf", "name": "Высший эльф"},
            "charClass": {"id": "Fighter", "name": "Воин"},
            "subclass": {"id": "BattleMaster", "name": "Боевой мастер"},
            "background": {"id": "GuildArtisan", "name": "Гильдейский ремесленник"},
        },
        "blocks": {"Предыстория": "Своими словами мастера."},
        "spells": {"list": ["fire-ball"]},
    }
    for key, value in over.items():
        if value is None:
            data.pop(key)
        else:
            data[key] = value
    return json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": json.dumps(data, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


def test_missing_fields_lists_exactly_the_empty_slots():
    assert top_up_missing_fields(_current_document()) == ()
    missing = top_up_missing_fields(_current_document(level=None, spells=None))
    assert missing == (CAPTION_LEVEL, CAPTION_SPELLS)
    no_name = json.dumps(
        {"jsonType": "character", "version": "2", "data": {"name": "  "}},
        ensure_ascii=False,
    )
    assert top_up_missing_fields(no_name)[0] == CAPTION_NAME


def test_disconnected_snapshot_link_counts_as_filled():
    """Снят источник — карточка отвечает снимком: ``{"id": "", "name": …}``
    заполнен, дозаполнять нечего (spec «Снял чекбокс — карточка не немеет»)."""
    current = _current_document(
        spells=None,
        info={
            "race": {"id": "", "name": "Драконид"},
            "subrace": {"id": "HighElf", "name": "Высший эльф"},
            "charClass": {"id": "Fighter", "name": "Воин"},
            "subclass": {"id": "BattleMaster", "name": "Боевой мастер"},
            "background": {"id": "GuildArtisan", "name": "X"},
        },
    )
    assert top_up_missing_fields(current) == (CAPTION_SPELLS,)


def test_nothing_to_fill_refuses_before_any_request():
    """Spec scenario «Пусто дозаполнять»: генерация не запускается — контекст
    отказывает русским сообществом (лист по тому же списку гасит кнопку)."""
    current = _current_document()
    assert top_up_missing_fields(current) == ()
    with pytest.raises(ValueError, match=TOP_UP_NOTHING_REFUSAL):
        _context(current_document=current)


async def test_top_up_refusal_launches_no_request_at_all():
    ask = _ScriptedAsk(["недоходит"])
    with pytest.raises(ValueError, match=TOP_UP_NOTHING_REFUSAL):
        context = _context(current_document=_current_document())
        await run_rounds(CharacterChannel(context), context, ask)
    assert ask.users == []  # гейт гасит круг до канала LLM


def test_parse_top_up_current_refuses_garbage_in_russian():
    with pytest.raises(ValueError, match="не является корректным JSON"):
        parse_top_up_current("{битый")
    with pytest.raises(ValueError, match="обязан быть JSON-объектом"):
        parse_top_up_current("[1, 2]")
    with pytest.raises(ValueError, match="ключ data отсутствует"):
        parse_top_up_current('{"jsonType": "character", "version": "2"}')


def test_top_up_merge_protects_the_master_and_fills_the_empties():
    """Spec scenario «Написанное мастером цело»: непустое не перезаписывается,
    пустое (включая блок с пустым текстом и отсутствующие привязки)
    дозаполняется."""
    current = json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": {
                "name": "Грог",
                "info": {"charClass": {"id": "Fighter", "name": "Воин"}},
                "blocks": {"Предыстория": "Своими словами мастера.", "Внешность": "   "},
            },
        },
        ensure_ascii=False,
    )
    context = _context(concept="добавь внешность", current_document=current)
    addition = json.dumps(
        {
            "name": "Выдуманное Имя",
            "level": 9,
            "info": {
                "charClass": {"id": "Rogue", "name": "Плут"},  # защищено
                "background": {
                    "id": "GuildArtisan",
                    "name": "Гильдейский ремесленник",
                },
            },
            "blocks": {
                "Предыстория": "выдуманная биография",  # защищено
                "Внешность": "Шрам над бровью.",
                "Характер": "Сдержан в словах.",
            },
            "spells": {"list": ["mending"]},
        },
        ensure_ascii=False,
    )

    channel = CharacterChannel(context)
    document = channel.parse(addition)
    data = _data_of(document)

    assert data["name"] == "Грог"  # имя мастера цело
    assert data["level"] == 9  # уровень был пуст — дозаполнен
    assert data["info"]["charClass"] == {"id": "Fighter", "name": "Воин"}
    assert data["info"]["background"] == {
        "id": "GuildArtisan",
        "name": "Гильдейский ремесленник",
    }
    assert data["blocks"]["Предыстория"] == "Своими словами мастера."
    assert data["blocks"]["Внешность"] == "Шрам над бровью."
    assert data["blocks"]["Характер"] == "Сдержан в словах."
    assert data["spells"] == {"list": ["mending"]}  # пустой список — заполним
    report, parsed = CharacterValidatorService().validate(document)
    assert [f"{i.path}: {i.message}" for i in report.errors] == []
    assert parsed is not None


def test_top_up_fills_name_and_avatar_when_the_card_has_none():
    current = json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": {"level": 2, "blocks": {"Внешность": " "}},
        },
        ensure_ascii=False,
    )
    channel = CharacterChannel(_context(current_document=current))
    addition = json.dumps(
        {"name": "Первое имя", "avatar": "Портрет кисти мастера"},
        ensure_ascii=False,
    )
    data = _data_of(channel.parse(addition))
    assert data["name"] == "Первое имя"  # пустое имя дозаполняется, как и аватар
    assert data["avatar"] == "Портрет кисти мастера"
    assert data["level"] == 2


def test_top_up_keeps_filled_spell_list_and_level_never_overwrites():
    # три привязки заполнены, две пусты — круг легален, но заполненное защищено
    current = _current_document(
        info={
            "race": {"id": "Elf", "name": "Эльф"},
            "charClass": {"id": "Fighter", "name": "Воин"},
            "background": {"id": "GuildArtisan", "name": "X"},
        }
    )
    channel = CharacterChannel(_context(current_document=current))
    addition = json.dumps(
        {
            "level": 21,
            "spells": {"list": ["power-word-kill"]},
            "info": {"race": {"id": "Tiefling"}},
        },
        ensure_ascii=False,
    )
    data = _data_of(channel.parse(addition))
    assert data["level"] == 5  # заполненный уровень не тронут
    assert data["spells"] == {"list": ["fire-ball"]}
    assert data["info"]["race"] == {"id": "Elf", "name": "Эльф"}


def test_level_preselect_out_of_range_is_refused_in_russian():
    with pytest.raises(ValueError, match="целое от 1 до 20"):
        _context(level=42)
    with pytest.raises(ValueError, match=LEVEL_REFUSAL.replace("(", r"\(")):
        _context(level=True)  # булев притворства не проходит доменную гейту


# ── дозаполнение и механики (dd-card-redesign task 6.3; spec «Дозаполнение
# персонажа» — читает механики как состояние, числовых механик не пишет) ─────


_MECH_CURRENT = {
    "stats": {
        "str": {"value": 18, "save": True},
        "dex": {"value": 14},
        "con": {"value": 16},
        "int": {"value": 10},
        "wis": {"value": 12},
        "cha": {"value": 8},
    },
    "skills": {"athletics": {"proficient": True}},
    "speed": 25,
    "alignment": "хаотично-добрый",
    "feats": [{"id": "alert", "name": "Наблюдательность"}],
}


def _mech_current_document() -> str:
    """Документ с механиками из 6.2; одна привязка вырезана — гейт
    дозаполнения требует хоть одно пустое поле."""
    data = {
        "name": "Грог",
        "level": 5,
        "info": {
            "race": {"id": "Elf", "name": "Эльф"},
            "subrace": {"id": "HighElf", "name": "Высший эльф"},
            "charClass": {"id": "Fighter", "name": "Воин"},
            "subclass": {"id": "BattleMaster", "name": "Боевой мастер"},
        },
        "blocks": {"Предыстория": "Своими словами мастера."},
        "spells": {"list": ["fire-ball"], "slots": [{"level": 1, "value": 4}]},
    }
    data.update(_MECH_CURRENT)
    return json.dumps(
        {
            "jsonType": "character",
            "version": "2",
            "data": json.dumps(data, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


def test_top_up_prompt_shows_mechanics_as_part_of_the_state():
    """Спека «Дозаполнение персонажа»: механики — часть текущего состояния и
    достаются модели в разобранном текущем документе (сборщик кладёт их в
    документ с 6.2, дозаполнение читает документ как есть)."""
    current = _mech_current_document()
    context = _context(concept="", current_document=current)
    channel = CharacterChannel(context)
    _system, user = channel.build_prompt(context)
    assert '"speed": 25' in user
    assert "хаотично-добрый" in user
    assert '"alert"' in user
    # механики не поля дозаполнения — в список пустых не лезут
    missing_line = user.split("Дозаполни только пустые поля: ")[1].split(".")[0]
    assert missing_line == SLOT_CAPTIONS["background"]


def test_top_up_keeps_current_mechanics_and_drops_smuggled_numbers():
    """Spec «Числовая механика остаётся LSS» на пути дозаполнения: ответ
    модели протаскивает stats/speed/alignment/feats/slots — в склеенный
    документ попадают ТОЛЬКО текущие значения, числовые ключи ответа
    отсекаются структурно, валидатор молчит."""
    current = _mech_current_document()
    channel = CharacterChannel(_context(current_document=current))
    addition = json.dumps(
        {
            "blocks": {"Характер": "Сдержан в словах."},
            "stats": {"str": {"value": 3}},
            "speed": 1,
            "alignment": "законно-добрый",
            "feats": [{"id": "great-weapon-master"}],
            "skills": {"stealth": {"proficient": True}},
            "spells": {"list": ["mending"], "slots": [{"level": 9, "value": 1}]},
        },
        ensure_ascii=False,
    )
    data = _data_of(channel.parse(addition))
    assert data["stats"] == _MECH_CURRENT["stats"]  # только текущие значения
    assert data["speed"] == 25
    assert data["alignment"] == "хаотично-добрый"
    assert data["feats"] == _MECH_CURRENT["feats"]
    assert data["skills"] == {"athletics": {"proficient": True}}
    assert data["spells"] == {"list": ["fire-ball"], "slots": [{"level": 1, "value": 4}]}
    assert data["blocks"]["Характер"] == "Сдержан в словах."  # текст — можно
    document = channel.parse(addition)
    report, parsed = CharacterValidatorService().validate(document)
    assert [f"{i.path}: {i.message}" for i in report.errors] == []
    assert parsed is not None
