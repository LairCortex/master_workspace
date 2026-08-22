"""Global LLM connection configuration — ~/.nri_manager/llm_config.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".nri_manager"
CONFIG_FILE = CONFIG_DIR / "llm_config.json"

_CONFIG_KEYS = ("base_url", "model", "api_key")


@dataclass
class LlmConfig:
    """Connection to an OpenAI-compatible LLM endpoint.

    ``api_key`` is optional — local servers (Ollama, vLLM, LM Studio)
    work without authorization.
    """

    base_url: str = ""
    model: str = ""
    api_key: str = ""

    @property
    def is_complete(self) -> bool:
        """Config is valid with non-empty base_url and model; key is optional."""
        return bool(self.base_url.strip()) and bool(self.model.strip())


class LlmConfigManager:
    """Reads and writes the global connection config file.

    The file is created with 0600 permissions so only the current
    user can read or write it (best-effort on non-POSIX systems).
    """

    def __init__(self, config_file: Path | None = None) -> None:
        self._config_file = config_file or CONFIG_FILE

    @property
    def config_file(self) -> Path:
        return self._config_file

    def load(self) -> LlmConfig | None:
        """Return the stored config or None when absent/invalid.

        A file in the legacy model-download format (``repo``/``filename``)
        is treated as "config does not exist".
        """
        try:
            raw = self._config_file.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        if not any(key in _CONFIG_KEYS for key in data):
            return None
        return LlmConfig(
            base_url=str(data.get("base_url", "")),
            model=str(data.get("model", "")),
            api_key=str(data.get("api_key", "")),
        )

    def save(self, config: LlmConfig) -> None:
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n"
        self._config_file.write_text(payload, encoding="utf-8")
        os.chmod(self._config_file, 0o600)
