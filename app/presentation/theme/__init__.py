"""Design-token theme runtime (W1, catalog roles in W2a)."""
from app.presentation.theme.compiler import (
    REQUIRED_TOKEN_KEYS,
    THEMES,
    accent_rgba,
    compile_css_root,
    compile_popup_qss,
    compile_qss,
    css_var_name,
    load_tokens,
    tokens_file_path,
)
from app.presentation.theme.runtime import APP_CSS_PATH, ThemeRuntime

__all__ = [
    "APP_CSS_PATH",
    "REQUIRED_TOKEN_KEYS",
    "THEMES",
    "ThemeRuntime",
    "accent_rgba",
    "compile_css_root",
    "compile_popup_qss",
    "compile_qss",
    "css_var_name",
    "get_default_theme",
    "load_tokens",
    "reset_default_theme",
    "tokens_file_path",
]

_default_theme: ThemeRuntime | None = None


def get_default_theme() -> ThemeRuntime:
    """Process-wide theme runtime used by main.py and the table host."""
    global _default_theme
    if _default_theme is None:
        _default_theme = ThemeRuntime()
    return _default_theme


def reset_default_theme() -> None:
    """Drop the singleton (tests)."""
    global _default_theme
    _default_theme = None
