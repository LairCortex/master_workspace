"""Model download and lifecycle management."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import site
import subprocess
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

LLM_PACKAGES = ["llama-cpp-python", "huggingface-hub", "tqdm"]

DEFAULT_REPO = "bartowski/Qwen2.5-14B-Instruct-GGUF"
DEFAULT_FILENAME = "Qwen2.5-14B-Instruct-Q4_K_M.gguf"

_CONFIG_DIR = Path.home() / ".nri_manager"
_MODELS_DIR = _CONFIG_DIR / "models"
_CONFIG_FILE = _CONFIG_DIR / "llm_config.json"


class ModelManager:
    """Handles downloading, locating and removing GGUF model files."""

    def __init__(
        self,
        repo_id: str = DEFAULT_REPO,
        filename: str = DEFAULT_FILENAME,
        models_dir: Path | None = None,
    ) -> None:
        self._repo_id = repo_id
        self._filename = filename
        self._models_dir = models_dir or _MODELS_DIR

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    def get_model_path(self) -> Path | None:
        path = self._models_dir / self._filename
        return path if path.exists() else None

    @staticmethod
    def are_llm_packages_installed() -> bool:
        for mod in ("llama_cpp", "huggingface_hub", "tqdm"):
            if importlib.util.find_spec(mod) is None:
                return False
        return True

    async def install_llm_packages(
        self,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        if self.are_llm_packages_installed():
            return
        if status_callback:
            status_callback("Установка необходимых пакетов…")
        await asyncio.to_thread(self._install_packages_sync)

    @staticmethod
    def _install_packages_sync() -> None:
        log.info("Installing LLM packages: %s", LLM_PACKAGES)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *LLM_PACKAGES],
            capture_output=True,
            text=True,
        )
        log.info("pip stdout: %s", result.stdout[-500:] if result.stdout else "")
        if result.returncode != 0:
            log.error("pip stderr: %s", result.stderr[-1000:] if result.stderr else "")
            raise RuntimeError(
                f"Не удалось установить пакеты (код {result.returncode}):\n"
                f"{result.stderr[-500:] if result.stderr else 'unknown error'}"
            )

        # Refresh sys.path so the running process sees newly installed packages
        importlib.invalidate_caches()
        known = set(sys.path)
        for d in site.getsitepackages() + [site.getusersitepackages()]:
            if d not in known:
                log.info("Adding to sys.path: %s", d)
                sys.path.insert(0, d)
        importlib.invalidate_caches()

        stale = [
            k for k in sys.modules
            if k in ("llama_cpp", "huggingface_hub", "tqdm")
            or k.startswith(("llama_cpp.", "huggingface_hub.", "tqdm."))
        ]
        for k in stale:
            del sys.modules[k]
        log.info("Cleared %d stale module entries from sys.modules", len(stale))

        # Verify packages are importable
        for mod in ("huggingface_hub", "tqdm"):
            spec = importlib.util.find_spec(mod)
            log.info("find_spec(%s) = %s", mod, spec)
            if spec is None:
                raise RuntimeError(
                    f"Пакет {mod} установлен, но не найден в текущем процессе. "
                    f"Перезапустите приложение."
                )

    async def download_model(
        self,
        progress_callback: Callable[[float], None] | None = None,
    ) -> Path:
        return await asyncio.to_thread(
            self._download_sync, progress_callback
        )

    def _download_sync(
        self,
        progress_callback: Callable[[float], None] | None = None,
    ) -> Path:
        log.info("Importing huggingface_hub…")
        from huggingface_hub import hf_hub_download
        from tqdm import tqdm as _tqdm_cls
        log.info("huggingface_hub imported OK")

        self._models_dir.mkdir(parents=True, exist_ok=True)
        log.info("Starting download to %s", self._models_dir)

        class _ProgressTqdm(_tqdm_cls):
            """tqdm subclass that forwards progress to our callback."""

            def update(self, n=1):
                super().update(n)
                if progress_callback and self.total and self.total > 0:
                    progress_callback(min(self.n / self.total, 0.99))

        import os
        token = os.environ.get("HF_TOKEN", "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")

        path = hf_hub_download(
            repo_id=self._repo_id,
            filename=self._filename,
            local_dir=str(self._models_dir),
            tqdm_class=_ProgressTqdm,
            token=token,
        )

        if progress_callback:
            progress_callback(1.0)
        return Path(path)

    def delete_model(self) -> bool:
        path = self._models_dir / self._filename
        if path.exists():
            path.unlink()
            return True
        return False

    def save_config(self, provider_type: str = "local") -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "repo_id": self._repo_id,
            "filename": self._filename,
            "model_path": str(self._models_dir / self._filename),
            "provider_type": provider_type,
        }
        _CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def load_config() -> dict | None:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        return None
