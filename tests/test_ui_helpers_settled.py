"""wait_until_settled: timeout must name the stuck app tasks (CI diagnosability)."""
from __future__ import annotations

import asyncio

import pytest

from tests.ui import helpers


async def test_wait_until_settled_reports_stuck_tasks():
    blocker = asyncio.ensure_future(asyncio.sleep(3600))
    try:
        with pytest.raises(TimeoutError) as exc_info:
            await helpers.wait_until_settled(timeout_s=0.2)
    finally:
        blocker.cancel()

    msg = str(exc_info.value)
    # Names the count and where the stuck coroutine is suspended
    assert "1 app task(s) still pending" in msg
    assert "sleep" in msg  # asyncio.sleep coroutine name
    assert "stuck at" in msg
