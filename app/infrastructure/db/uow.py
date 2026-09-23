"""GameSessionUoW — the single transaction finish point of a user operation.

One game runs on one shared ``AsyncSession`` (``main.Application.start``) and
the wiring's lock serializes every task touching it; before this unit, the
finish of that session — commit or rollback — was spread over four layers, and
the audit (docs/refactoring-audit.md, Q14 scenarios 1/3/5) showed the damage:
double commits reporting failure over committed data, cancelled work riding
some later commit, dirty sessions after a failed commit.

The unit is the discipline layer over the SAME session and the SAME lock, not
a second mechanism (design D4):

* ``.transaction()`` commits on clean exit and rolls back + re-raises on any
  exception — a mid-operation error leaves no partial result;
* reentry is refused: opening a second transaction on an active unit raises
  ``RuntimeError``, so the double finish of scenario 3 is a loud caller bug
  instead of a silent partial commit;
* :meth:`after_write` registers post-write hooks that run after the commit
  succeeded (the D6 image-GC contract: files may only be touched once the
  reference mutation is committed). A failing hook is logged, never raised —
  the data is already written, and surfacing the failure as "could not save"
  was exactly the false alarm scenario 3 described; session work a hook leaves
  behind (deleted rows) is committed once by this unit, the hook never commits
  itself. On rollback the pending hooks are dropped: nothing was written.

The lock is NOT acquired here — serialization stays where it always was (the
``ApplicationWiring._spawn`` / ``run_locked`` contract, non-reentrant by
design); the reference carries the single-owner idea the unit is named after.
:meth:`session` lets read-side holders (the calendar wizard view model, audit
A2) keep the unit instead of a raw session, so the session leaves the
presentation package entirely.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.db.uow")

#: A zero-argument awaitable registered through :meth:`GameSessionUoW.after_write`.
PostWriteHook = Callable[[], Awaitable[None]]


class GameSessionUoW:
    """Session + lock reference + post-write hook registry, one finish point."""

    def __init__(
        self, session: AsyncSession, lock: Optional[asyncio.Lock] = None
    ) -> None:
        self._session = session
        # With no lock handed in, the unit owns one: the wiring serializes
        # through the SAME lock object (``uow.lock``), so the unit and the
        # task serializer never diverge into two locks.
        self._lock = lock if lock is not None else asyncio.Lock()
        self._in_transaction = False
        self._hooks: list[PostWriteHook] = []

    @property
    def session(self) -> AsyncSession:
        """The single game session this unit finalizes."""
        return self._session

    @property
    def lock(self) -> asyncio.Lock:
        """The serialization lock owned by (or handed to) this unit."""
        return self._lock

    def after_write(self, hook: PostWriteHook) -> None:
        """Run ``hook`` after this transaction commits; never report its failure.

        Only callable while a transaction is open — a hook registered outside
        would fire onto the NEXT commit, which may have nothing to do with the
        work that registered it.
        """
        if not self._in_transaction:
            raise RuntimeError(
                "GameSessionUoW.after_write() requires an open transaction()"
            )
        self._hooks.append(hook)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """One transaction: commit on clean exit, rollback + re-raise on error."""
        if self._in_transaction:
            raise RuntimeError(
                "GameSessionUoW.transaction() is not reentrant; the active "
                "transaction owns this session's finish"
            )
        self._in_transaction = True
        self._hooks = []  # the previous transaction owns its hooks; start clean
        try:
            yield
        except BaseException:
            # BaseException, not Exception: the wiring runs every operation as
            # a task that can be cancelled, and CancelledError is a BaseException.
            # Rolling back here (and re-clearing in ``finally``) guarantees the
            # session and this flag never stay poisoned after a cancelled task.
            self._hooks.clear()
            await self._session.rollback()
            raise
        finally:
            # Runs on every exit path (clean, Exception, CancelledError): the
            # unit is free to open its next transaction once this one unwinds.
            self._in_transaction = False

        # Only reached on a clean block exit — this is the single commit point.
        hooks, self._hooks = self._hooks, []
        try:
            await self._session.commit()
        except BaseException:
            # Hooks were already popped above, so a failed commit cannot leak
            # them onto the next transaction (they belong to this, now-aborted,
            # one — dropping them is what the docstring promises).
            await self._session.rollback()
            raise
        await self._run_hooks(hooks)

    async def _run_hooks(self, hooks: list[PostWriteHook]) -> None:
        if not hooks:
            return
        for hook in hooks:
            try:
                await hook()
            except Exception:
                # The write is committed already: a broken collector must never
                # turn the succeeded operation into a failure (scenarios 3/4).
                logger.exception("GameSessionUoW post-write hook failed")
        # Whatever the hooks did to the session (image-row deletes) finalizes
        # here — the hooks themselves never commit, so nothing commits through
        # any other door. If a hook died midway, this commit also clears the
        # half-done deletions from the pending state.
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            logger.exception("GameSessionUoW post-write commit failed")
