import json
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from gemini_quota.cli import main


@patch("gemini_quota.cli.Config")
@patch("gemini_quota.cli.AuthManager")
@patch("gemini_quota.cli.QuotaClient")
def test_cli_query_matching(mock_quota_client_cls, mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [
        {"email": "test@example.com", "type": "google"}
    ]
    mock_auth_mgr.get_credentials.return_value = MagicMock()

    mock_client = mock_quota_client_cls.return_value
    mock_client.fetch_quotas.return_value = [
        {"name": "gemini-3-pro", "display_name": "Gemini 3 Pro", "remaining_pct": 85.2},
        {
            "name": "claude-3-sonnet",
            "display_name": "Claude 3 Sonnet",
            "remaining_pct": 40.0,
        },
    ]
    mock_client.provider.provider_name = "Google"
    mock_client.get_color.return_value = "cyan"
    mock_client.get_sort_key.return_value = (0, 0, "a")
    # Mock display.filter_quotas to return what we want
    with patch("gemini_quota.cli.DisplayManager.filter_quotas") as mock_filter:
        mock_filter.return_value = mock_client.fetch_quotas.return_value

        runner = CliRunner()
        # Case insensitive match
        result = runner.invoke(main, ["--query", "GEMINI"])
        assert result.exit_code == 0
        assert "Gemini 3 Pro" in result.output
        assert "Claude 3 Sonnet" not in result.output
        assert "85.2%" in result.output
        assert "test@example.com" in result.output  # Should show account header
        assert "━" in result.output  # Should show separator


def test_cli_query_no_match_exit_code():
    with (
        patch("gemini_quota.cli.Config") as mock_config_cls,
        patch("gemini_quota.cli.AuthManager") as mock_auth_mgr_cls,
        patch("gemini_quota.cli.QuotaClient") as mock_quota_client_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.auth_path.exists.return_value = True
        mock_auth_mgr = mock_auth_mgr_cls.return_value
        mock_auth_mgr.load_accounts.return_value = [{"email": "test@example.com"}]

        mock_client = mock_quota_client_cls.return_value
        mock_client.fetch_quotas.return_value = [
            {"name": "other", "remaining_pct": 100}
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["--query", "nonexistent"])
        assert result.exit_code == 1


@patch("gemini_quota.cli.Config")
@patch("gemini_quota.cli.AuthManager")
@patch("gemini_quota.cli.QuotaClient")
def test_cli_multiple_queries_and_match(
    mock_quota_client_cls, mock_auth_mgr_cls, mock_config_cls
):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [
        {"email": "test@example.com", "type": "google"}
    ]
    mock_auth_mgr.get_credentials.return_value = MagicMock()

    mock_client = mock_quota_client_cls.return_value
    mock_client.fetch_quotas.return_value = [
        {"name": "gemini-3-pro", "display_name": "Gemini 3 Pro", "remaining_pct": 85.2},
        {
            "name": "gemini-3-flash",
            "display_name": "Gemini 3 Flash",
            "remaining_pct": 90.0,
        },
        {
            "name": "claude-3-sonnet",
            "display_name": "Claude 3 Sonnet",
            "remaining_pct": 40.0,
        },
    ]
    mock_client.provider.provider_name = "Google"
    mock_client.get_color.return_value = "cyan"
    mock_client.get_sort_key.return_value = (0, 0, "a")

    with patch("gemini_quota.cli.DisplayManager.filter_quotas") as mock_filter:
        mock_filter.return_value = mock_client.fetch_quotas.return_value

        runner = CliRunner()
        # AND match: "gemini" and "pro"
        result = runner.invoke(main, ["-q", "gemini", "-q", "pro"])
        assert result.exit_code == 0
        assert "Gemini 3 Pro" in result.output
        assert "Gemini 3 Flash" not in result.output
        assert "Claude 3 Sonnet" not in result.output


@patch("gemini_quota.cli.Config")
@patch("gemini_quota.cli.AuthManager")
def test_cli_provider_filter(mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [
        {"email": "google@test.com", "type": "google"},
        {"email": "chutes@test.com", "type": "chutes"},
    ]

    with patch("gemini_quota.cli.fetch_account_data") as mock_fetch:
        mock_fetch.return_value = ("test", [], MagicMock(), None)

        runner = CliRunner()
        runner.invoke(main, ["--provider", "chutes"])

        # Check that fetch_account_data was only called once for chutes
        assert mock_fetch.call_count == 1
        args, kwargs = mock_fetch.call_args
        assert args[1]["type"] == "chutes"
