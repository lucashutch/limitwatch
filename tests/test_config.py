import json
from gemini_quota.config import Config


def test_config_load_empty(tmp_path):
    config = Config(config_dir=tmp_path)
    assert config.data == {}
    expected_path = tmp_path / "accounts.json"
    assert config.auth_path == expected_path


def test_config_save(tmp_path):
    config = Config(config_dir=tmp_path)
    config.data["test_key"] = "test_value"
    config.save()

    config_file = tmp_path / "config.json"
    assert config_file.exists()

    with open(config_file, "r") as f:
        data = json.load(f)
    assert data["test_key"] == "test_value"
