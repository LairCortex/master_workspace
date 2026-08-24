"""E2E boot stub: full Application start with an injected mock HTTP client.

Verifies the DI seam (task 1.1) on the boot fixtures (task 1.2): one LLM
request answered by the canned ``httpx.MockTransport`` response — no real
network, all paths in tmp.
"""
from __future__ import annotations

from app.infrastructure.llm.config import LlmConfig


async def test_boot_with_injected_mock_client(app, llm_client, tmp_llm_config):
    application, window = app
    llm_vm = application._llm_vm
    llm_vm.apply_config(LlmConfig(base_url="http://mock-llm/v1", model="test-model"))
    assert llm_vm.status == llm_vm.STATUS_READY

    finished: list[tuple[str, str]] = []
    llm_vm.generation_finished.connect(lambda owner, fid, text: finished.append((fid, text)))
    await llm_vm.request_generation("event.name", "event", "name", "Название", "")
    assert finished == [("event.name", "Сгенерированный текст из mock-LLM")]

    # The LLM request went through the injected emulated client
    assert len(llm_client.requests) == 1
    assert llm_client.requests[0].url.path.endswith("/chat/completions")
    # Config file stayed inside the tmp path
    assert application._config_manager.config_file == tmp_llm_config


async def test_boot_without_client_creates_default(qapp, tmp_path, tmp_llm_config):
    """Back-compat: no client passed → the app creates its own default client."""
    from app.main import Application

    application = Application(qapp)
    window = await application.start(str(tmp_path / "default.db"))
    try:
        assert application._http is not None
        assert application._http.client is not None
    finally:
        window.close()
        await application.shutdown()
