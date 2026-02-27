import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import jsonschema

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "limitwatch"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
MANAGED_ACCOUNTS_FILE = DEFAULT_CONFIG_DIR / "accounts.json"

ACCOUNTS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "accounts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "email"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "google",
                            "chutes",
                            "github_copilot",
                            "openai",
                            "openrouter",
                        ],
                    },
                    "email": {"type": "string"},
                    "refreshToken": {"type": "string"},
                    "apiKey": {"type": "string"},
                    "services": {"type": "array", "items": {"type": "string"}},
                    "projectId": {"type": "string"},
                    "managedProjectId": {"type": "string"},
                    "alias": {"type": "string"},
                    "group": {"type": "string"},
                },
            },
        },
        "activeIndex": {"type": "integer", "minimum": 0},
    },
}

CONFIG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "alertThreshold": {"type": "number", "minimum": 0, "maximum": 100},
        "cacheTtl": {"type": "integer", "minimum": 0},
        "theme": {"type": "string", "enum": ["default", "dark", "light"]},
        "historyDbPath": {"type": "string"},
        "enableHistory": {"type": "boolean"},
    },
}


def validate_schema(
    data: Dict[str, Any], schema: Dict[str, Any], filename: str
) -> bool:
    """Validate data against schema. Returns True if valid, logs warning if invalid."""
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True
    except jsonschema.ValidationError as e:
        logger.warning(f"Schema validation failed for {filename}: {e.message}")
        return False
    except jsonschema.SchemaError as e:
        logger.error(f"Invalid schema for {filename}: {e.message}")
        return False


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
                data = json.load(f)
            validate_schema(data, CONFIG_SCHEMA, "config.json")
            return data
        except Exception:
            return {}

    def save(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.data, f, indent=2)

    @property
    def auth_path(self) -> Path:
        return self.config_dir / "accounts.json"

    @property
    def history_db_path(self) -> Path:
        """Get the path to the history database."""
        custom_path = self.data.get("historyDbPath")
        if custom_path:
            return Path(custom_path).expanduser()
        return self.config_dir / "history.db"

    @property
    def history_enabled(self) -> bool:
        """Check if history tracking is enabled."""
        return self.data.get("enableHistory", True)

    @property
    def cache_ttl(self) -> int:
        """Get cache TTL in seconds (default: 60)."""
        value = self.data.get("cacheTtl")
        if value is None:
            return 60
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 60
