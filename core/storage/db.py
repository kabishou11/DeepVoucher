from pathlib import Path

from core.config.settings import get_settings


def sqlite_path() -> Path:
    return Path(get_settings().sqlite_path)
