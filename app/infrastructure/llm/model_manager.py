"""Model download and lifecycle management."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import shutil
import site
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

LLM_PACKAGES = ["llama-cpp-python", "huggingface-hub", "tqdm"]


_PREFERRED_PYTHON_PATHS = [
    "/opt/homebrew/bin/python3",
    "/opt/homebrew/bin/python3.11",
    "/opt/homebrew/bin/python3.12",
    "/opt/homebrew/bin/python3.13",
    "/usr/local/bin/python3",
]

_APPLE_SHIM_PREFIXES = ("/usr/bin/", "/Library/Developer/CommandLineTools/")


def _is_apple_shim(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _APPLE_SHIM_PREFIXES)


def _get_python_executable() -> str:
    """Return path to the Python interpreter (not the frozen app binary)."""
    if getattr(sys, "frozen", False):
        for p in _PREFERRED_PYTHON_PATHS:
            if Path(p).is_file():
                log.info("Frozen app: using preferred Python: %s", p)
                return p
        for name in ("python3", "python"):
            path = shutil.which(name)
            if path and not _is_apple_shim(path):
                log.info("Frozen app: using system Python: %s", path)
                return path
        raise RuntimeError(
            "Не найден Python 3.10+ с pip.\n\n"
            "Установите через Homebrew:\n"
            "  brew install python\n\n"
            "Или скачайте с python.org."
        )
    return sys.executable

class DownloadCancelled(Exception):
    pass


DEFAULT_REPO = "bartowski/Qwen2.5-14B-Instruct-GGUF"
DEFAULT_FILENAME = "Qwen2.5-14B-Instruct-Q4_K_M.gguf"

_CONFIG_DIR = Path.home() / ".nri_manager"
_MODELS_DIR = _CONFIG_DIR / "models"
_CONFIG_FILE = _CONFIG_DIR / "llm_config.json"
VENV_DIR = Path.home() / ".nri_manager_venv"


class ModelManager:
    """Handles downloading, locating and removing GGUF model files."""

    VENV_DIR = Path.home() / ".nri_manager_venv"

    def __init__(
        self,
        repo_id: str = DEFAULT_REPO,
        filename: str = DEFAULT_FILENAME,
        models_dir: Path | None = None,
    ) -> None:
        self._repo_id = repo_id
        self._filename = filename
        self._models_dir = models_dir or _MODELS_DIR
        self._cancel_event = threading.Event()

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    def get_model_path(self) -> Path | None:
        path = self._models_dir / self._filename
        return path if path.exists() else None

    def cancel_download(self) -> None:
        self._cancel_event.set()

    def cleanup_partial(self) -> None:
        if not self._models_dir.exists():
            return
        for f in self._models_dir.iterdir():
            if f.is_file():
                log.info("Cleaning up partial file: %s", f)
                f.unlink()
        if self._models_dir.exists() and not any(self._models_dir.iterdir()):
            self._models_dir.rmdir()
            log.info("Removed empty models dir: %s", self._models_dir)

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
    def _ensure_venv(base_python: str) -> str:
        venv_python = ModelManager.VENV_DIR / "bin" / "python"

        if not venv_python.exists():
            log.info("Creating virtual environment at %s", ModelManager.VENV_DIR)
            subprocess.run(
                [base_python, "-m", "venv", str(ModelManager.VENV_DIR)],
                check=True,
                capture_output=True,
                text=True,
            )

        return str(venv_python)

    @staticmethod
    def _install_packages_sync() -> None:
        base_python = _get_python_executable()

        python = ModelManager._ensure_venv(base_python)

        log.info("Installing LLM packages via venv python: %s", python)
        log.info("Packages: %s", LLM_PACKAGES)

        log.info("Upgrading pip in venv…")
        subprocess.run(
            [python, "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            [python, "-m", "pip", "install", "--prefer-binary", *LLM_PACKAGES],
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

        log.info("Refreshing sys.path with venv site-packages")

        site_packages = subprocess.run(
            [python, "-c", "import site; print(site.getsitepackages()[0])"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        if site_packages and site_packages not in sys.path:
            log.info("Adding to sys.path: %s", site_packages)
            sys.path.insert(0, site_packages)

        importlib.invalidate_caches()

        stale = [
            k for k in sys.modules
            if k in ("llama_cpp", "huggingface_hub", "tqdm")
            or k.startswith(("llama_cpp.", "huggingface_hub.", "tqdm."))
        ]
        for k in stale:
            del sys.modules[k]

        log.info("Cleared %d stale module entries from sys.modules", len(stale))

        for mod in ("huggingface_hub", "tqdm"):
            spec = importlib.util.find_spec(mod)
            log.info("find_spec(%s) = %s", mod, spec)
            if spec is None:
                raise RuntimeError(
                    f"Пакет {mod} установлен, но не найден в текущем процессе. "
                    f"Перезапустите приложение."
                )
