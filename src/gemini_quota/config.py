import json
import os
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "gemini-quota"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
MANAGED_ACCOUNTS_FILE = DEFAULT_CONFIG_DIR / "accounts.json"


class Config:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.config_file = self.config_dir / "config.json"
        self.data = self._load()

    def _load(self):
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def save(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.data, f, indent=2)

    @property
    def auth_path(self) -> Path:
        return self.config_dir / "accounts.json"
