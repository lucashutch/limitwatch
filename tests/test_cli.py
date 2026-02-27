import json
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from limitwatch.cli import main


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "limitwatch" in result.output


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
def test_cli_no_accounts_file(mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = False

    runner = CliRunner()
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "Accounts file not found" in result.output


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
def test_cli_empty_accounts(mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = []

    runner = CliRunner()
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "No accounts found in file" in result.output


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.QuotaClient")
def test_cli_list_quotas(mock_quota_client_cls, mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [
        {"email": "test@example.com", "type": "google"}
    ]
    mock_auth_mgr.get_credentials.return_value = MagicMock()

    mock_client = mock_quota_client_cls.return_value
    mock_client.fetch_quotas.return_value = [{"name": "quota1", "remaining_pct": 50}]
    mock_client.provider.provider_name = "Google"

    runner = CliRunner()
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "Quota Status" in result.output
    assert "test@example.com" in result.output


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
def test_cli_logout(mock_auth_mgr_cls, mock_config_cls):
    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.logout.return_value = True

    runner = CliRunner()
    result = runner.invoke(main, ["--logout", "test@example.com"])
    assert result.exit_code == 0
    assert "Successfully logged out test@example.com" in result.output
    mock_auth_mgr.logout.assert_called_with("test@example.com")


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.QuotaClient")
def test_cli_list_quotas_json(
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
        {"name": "quota1", "remaining_pct": 50, "display_name": "Q1"}
    ]
    mock_client.provider.provider_name = "Google"
    mock_client.filter_quotas.return_value = [
        {"name": "quota1", "remaining_pct": 50, "display_name": "Q1"}
    ]

    runner = CliRunner()
    result = runner.invoke(main, ["--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["email"] == "test@example.com"
    assert data[0]["quotas"][0]["name"] == "quota1"


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.QuotaClient")
def test_cli_login_interactive(
    mock_quota_client_cls, mock_auth_mgr_cls, mock_config_cls
):
    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.login.return_value = "test@example.com"

    mock_client = mock_quota_client_cls.return_value
    mock_client.provider.interactive_login.return_value = {
        "email": "test@example.com",
        "type": "google",
    }

    # Mock QuotaClient.get_available_providers
    mock_quota_client_cls.get_available_providers.return_value = {
        "google": "Google",
        "chutes": "Chutes",
    }

    runner = CliRunner()
    # Choice 1 for Google
    result = runner.invoke(main, ["--login"], input="1\n")
    assert result.exit_code == 0
    assert "Successfully logged in as test@example.com" in result.output


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
def test_cli_update_project_id(mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    accounts = [{"email": "test@example.com", "type": "google"}]
    mock_auth_mgr.load_accounts.return_value = accounts
    mock_auth_mgr.update_account_metadata.return_value = True

    runner = CliRunner()
    result = runner.invoke(
        main, ["--account", "test@example.com", "--project-id", "new-id"]
    )
    assert result.exit_code == 0
    assert "Updated metadata for test@example.com" in result.output
    mock_auth_mgr.update_account_metadata.assert_called_once_with(
        "test@example.com",
        {"projectId": "new-id", "managedProjectId": "new-id"},
    )


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.QuotaClient")
def test_cli_login_failure_json(
    mock_quota_client_cls, mock_auth_mgr_cls, mock_config_cls
):
    mock_client = mock_quota_client_cls.return_value
    mock_client.provider.login.side_effect = Exception("API Error")

    runner = CliRunner()
    result = runner.invoke(main, ["--login", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert "API Error" in data["message"]


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
def test_cli_fetch_errors(mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [
        {"email": "fail-creds@example.com", "type": "google"},
        {"email": "fail-refresh@example.com", "type": "google"},
    ]

    def get_creds_side_effect(idx):
        if idx == 0:
            return None
        return MagicMock()

    mock_auth_mgr.get_credentials.side_effect = get_creds_side_effect
    mock_auth_mgr.refresh_credentials.side_effect = Exception("Refresh Error")

    runner = CliRunner()
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "Could not load credentials for fail-creds@example.com" in result.output
    assert "Token refresh failed: Refresh Error" in result.output


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
def test_cli_account_not_found(mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [{"email": "other@example.com"}]

    runner = CliRunner()
    result = runner.invoke(main, ["--account", "missing@example.com"])
    assert result.exit_code == 0
    assert "Account missing@example.com not found" in result.output
