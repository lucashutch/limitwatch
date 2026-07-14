"""Tests for shell completion functionality."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from click.testing import CliRunner

from limitwatch import completions


class TestCompletions:
    """Test the completions module."""

    @pytest.fixture
    def mock_accounts_data(self):
        """Sample accounts data for testing."""
        return {
            "accounts": [
                {
                    "email": "test@example.com",
                    "type": "google",
                    "alias": "work",
                    "group": "production",
                    "cachedQuotas": [
                        {"name": "gemini-pro", "display_name": "Gemini Pro"},
                        {"name": "gemini-flash", "display_name": "Gemini Flash"},
                    ],
                },
                {
                    "email": "personal@gmail.com",
                    "type": "chutes",
                    "group": "personal",
                    "cachedQuotas": [
                        {"name": "chutes-credits", "display_name": "Chutes Credits"},
                    ],
                },
                {
                    "email": "dev@company.com",
                    "type": "openai",
                    "alias": "dev",
                    "cachedQuotas": [],
                },
            ]
        }

    def test_get_config_dir_from_env(self):
        """Test getting config dir from environment variable."""
        with patch.dict("os.environ", {"LIMITWATCH_CONFIG_DIR": "/custom/config"}):
            config_dir = completions.get_config_dir()
            assert config_dir == Path("/custom/config")

    def test_get_config_dir_xdg(self):
        """Test getting config dir from XDG_CONFIG_HOME."""
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": "/xdg/config"}, clear=True):
            with patch.dict("os.environ", {"LIMITWATCH_CONFIG_DIR": ""}):
                config_dir = completions.get_config_dir()
                assert config_dir == Path("/xdg/config/limitwatch")

    def test_get_config_dir_default(self):
        """Test getting default config dir."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("pathlib.Path.home", return_value=Path("/home/user")):
                config_dir = completions.get_config_dir()
                assert config_dir == Path("/home/user/.config/limitwatch")

    def test_load_accounts_data_success(self, mock_accounts_data):
        """Test loading accounts data successfully."""
        with patch(
            "builtins.open", mock_open(read_data=json.dumps(mock_accounts_data))
        ):
            with patch.object(Path, "exists", return_value=True):
                with patch(
                    "limitwatch.completions.get_config_dir",
                    return_value=Path("/config"),
                ):
                    data = completions.load_accounts_data()
                    assert data == mock_accounts_data

    def test_load_accounts_data_file_not_found(self):
        """Test loading accounts data when file doesn't exist."""
        with patch.object(Path, "exists", return_value=False):
            with patch(
                "limitwatch.completions.get_config_dir", return_value=Path("/config")
            ):
                data = completions.load_accounts_data()
                assert data == {"accounts": []}

    def test_load_accounts_data_invalid_json(self):
        """Test loading accounts data with invalid JSON."""
        with patch("builtins.open", mock_open(read_data="invalid json")):
            with patch.object(Path, "exists", return_value=True):
                with patch(
                    "limitwatch.completions.get_config_dir",
                    return_value=Path("/config"),
                ):
                    data = completions.load_accounts_data()
                    assert data == {"accounts": []}

    def test_complete_accounts(self, mock_accounts_data):
        """Test completing account emails and aliases."""
        with patch(
            "limitwatch.completions.load_accounts_data", return_value=mock_accounts_data
        ):
            ctx = None
            param = None

            # Complete "test" - should match test@example.com
            results = list(completions.complete_accounts(ctx, param, "test"))
            assert "test@example.com" in results
            assert "personal@gmail.com" not in results

            # Complete "work" - should match alias
            results = list(completions.complete_accounts(ctx, param, "work"))
            assert "work" in results

            # Complete empty - should return all emails and aliases
            results = list(completions.complete_accounts(ctx, param, ""))
            assert "test@example.com" in results
            assert "personal@gmail.com" in results
            assert "dev@company.com" in results
            assert "work" in results
            assert "dev" in results

    def test_complete_providers(self, mock_accounts_data):
        """Test completing provider types."""
        with patch(
            "limitwatch.completions.load_accounts_data", return_value=mock_accounts_data
        ):
            ctx = None
            param = None

            # Complete "g" - should match google
            results = list(completions.complete_providers(ctx, param, "g"))
            assert "google" in results
            assert "chutes" not in results

            # Complete empty - should return all providers
            results = list(completions.complete_providers(ctx, param, ""))
            assert "google" in results
            assert "chutes" in results
            assert "openai" in results
            assert "github_copilot" in results
            assert "openrouter" in results

    def test_complete_groups(self, mock_accounts_data):
        """Test completing group names."""
        with patch(
            "limitwatch.completions.load_accounts_data", return_value=mock_accounts_data
        ):
            ctx = None
            param = None

            # Complete "prod" - should match production
            results = list(completions.complete_groups(ctx, param, "prod"))
            assert "production" in results
            assert "personal" not in results

            # Complete empty - should return all groups
            results = list(completions.complete_groups(ctx, param, ""))
            assert "production" in results
            assert "personal" in results

    def test_complete_quota_names(self, mock_accounts_data):
        """Test completing quota names."""
        with patch(
            "limitwatch.completions.load_accounts_data", return_value=mock_accounts_data
        ):
            ctx = None
            param = None

            # Complete "gemini" - should match gemini quotas
            results = list(completions.complete_quota_names(ctx, param, "gemini"))
            assert "gemini-pro" in results
            assert "gemini-flash" in results
            assert "chutes-credits" not in results

            # Complete empty - should return all quota names and display names
            results = list(completions.complete_quota_names(ctx, param, ""))
            assert "gemini-pro" in results
            assert "gemini-flash" in results
            assert "chutes-credits" in results
            assert "Gemini Pro" in results
            assert "Gemini Flash" in results
            assert "Chutes Credits" in results

    def test_complete_preset_ranges(self):
        """Test completing preset time ranges."""
        ctx = None
        param = None

        # Complete "2" - should match 24h
        results = list(completions.complete_preset_ranges(ctx, param, "2"))
        assert "24h" in results
        assert "7d" not in results

        # Complete empty - should return all presets
        results = list(completions.complete_preset_ranges(ctx, param, ""))
        assert "24h" in results
        assert "7d" in results
        assert "30d" in results
        assert "90d" in results

    def test_complete_export_formats(self):
        """Test completing export formats."""
        ctx = None
        param = None

        # Complete "c" - should match csv
        results = list(completions.complete_export_formats(ctx, param, "c"))
        assert "csv" in results
        assert "markdown" not in results

        # Complete empty - should return all formats
        results = list(completions.complete_export_formats(ctx, param, ""))
        assert "csv" in results
        assert "markdown" in results

    def test_complete_history_view_types(self):
        """Test completing history view types."""
        ctx = None
        param = None

        # Complete "h" - should match heatmap
        results = list(completions.complete_history_view_types(ctx, param, "h"))
        assert "heatmap" in results
        assert "chart" not in results

        # Complete empty - should return all view types
        results = list(completions.complete_history_view_types(ctx, param, ""))
        assert "heatmap" in results
        assert "chart" in results
        assert "calendar" in results
        assert "bars" in results
        assert "stats" in results


class TestCompletionCommand:
    """Test the completion CLI command."""

    def test_completion_command_bash(self):
        """Test completion command for bash."""
        from limitwatch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "bash"])
        assert result.exit_code == 0
        # Should contain bash completion script content
        assert "limitwatch" in result.output.lower() or "_LIMITWATCH" in result.output

    def test_completion_command_zsh(self):
        """Test completion command for zsh."""
        from limitwatch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "zsh"])
        assert result.exit_code == 0
        # Should contain zsh completion script content
        assert "limitwatch" in result.output.lower() or "#compdef" in result.output

    def test_completion_command_fish(self):
        """Test completion command for fish."""
        from limitwatch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "fish"])
        assert result.exit_code == 0
        # Should contain fish completion script content
        assert "limitwatch" in result.output.lower() or "complete" in result.output

    def test_completion_command_invalid_shell(self):
        """Test completion command with invalid shell."""
        from limitwatch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "invalid"])
        assert result.exit_code != 0
