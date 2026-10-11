"""Рубильник «показывать справочные записи в поиске» (add-dnd-game-face,
task 3.3; spec dnd-reference-records «Справочные сущности участвуют в поиске
под одним переключателем»).

DB-контур на штатной ``uow`` (in-memory aiosqlite): отсутствие строки —
дефолт спеки «показывать»; каждая смена — одна транзакция единицы работы;
значение переживает перезапуск сервиса (тот же файл — та же строка);
испорченная строка читается дефолтом через кодек-запись в журнал.
"""
from __future__ import annotations

from app.dd.application.reference_visibility_service import (
    ReferenceVisibilityService,
)
from app.infrastructure.repositories.game_settings_repository import (
    DND_SEARCH_SHOW_REFERENCE_KEY,
    GameSettingsRepository,
)


async def test_absent_row_defaults_to_show(uow):
    """Справка обнаруживается с первого включения модуля: ключа нет —
    «показывать», ни в свойствах, ни в load."""
    service = ReferenceVisibilityService(uow)
    assert service.visible is True
    assert await service.load() is True
    assert service.visible is True


async def test_set_visible_writes_once_and_survives_restart(uow):
    """Каждый клик — одна транзакция; перезапуск (новый сервис поверх той же
    базы) читает сохранённое состояние — специальная ветка «перезапуск
    сохраняет»."""
    service = ReferenceVisibilityService(uow)
    await service.set_visible(False)
    assert service.visible is False
    restarted = ReferenceVisibilityService(uow)
    assert restarted.visible is True  # до чтения — честный дефолт
    assert await restarted.load() is False
    assert restarted.visible is False
    await restarted.set_visible(True)
    assert await ReferenceVisibilityService(uow).load() is True


async def test_failed_write_leaves_holder_and_row_untouched(uow, monkeypatch):
    """Принцип 3 в миниатюре: бросок транзакции не переворачивает держатель
    (чекбокс листа по этому же держателю шагает назад честно)."""
    service = ReferenceVisibilityService(uow)

    class _Boom:
        def __aenter__(self):
            raise RuntimeError("диск отказал")

        def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(uow, "transaction", lambda: _Boom())
    try:
        await service.set_visible(False)
    except RuntimeError:
        pass
    assert service.visible is True


async def test_corrupt_row_reads_default_show(uow):
    """Битое значение ключа — «показывать» с одной записью в журнал (кодек
    типизированного ключа), строка дожидается явной перезаписи."""
    async with uow.transaction():
        await GameSettingsRepository(uow.session).upsert(
            DND_SEARCH_SHOW_REFERENCE_KEY, "{не bool"
        )
    service = ReferenceVisibilityService(uow)
    assert await service.load() is True
    await service.set_visible(False)
    assert await service.load() is False  # чистая строка после явной записи
