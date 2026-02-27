from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from limitwatch.cli import main


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.QuotaClient")
def test_cli_set_alias_and_group(
    mock_quota_client_cls, mock_auth_mgr_cls, mock_config_cls
):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    accounts = [{"email": "test@example.com", "type": "google"}]
    mock_auth_mgr.load_accounts.return_value = accounts
    mock_auth_mgr.update_account_metadata.return_value = True

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--account", "test@example.com", "--alias", "work", "--group", "professional"],
    )

    assert result.exit_code == 0
    assert "Updated metadata for test@example.com" in result.output

    mock_auth_mgr.update_account_metadata.assert_called_once_with(
        "test@example.com", {"alias": "work", "group": "professional"}
    )


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.fetch_account_data")
def test_cli_filter_by_group(mock_fetch, mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [
        {"email": "work@example.com", "group": "work"},
        {"email": "home@example.com", "group": "home"},
    ]

    mock_fetch.return_value = ("test", [], MagicMock(), None)

    runner = CliRunner()
    result = runner.invoke(main, ["-g", "work"])

    assert result.exit_code == 0
    # Check that fetch_account_data was only called once for the "work" account
    assert mock_fetch.call_count == 1
    args, kwargs = mock_fetch.call_args
    assert args[1]["email"] == "work@example.com"


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.fetch_account_data")
def test_cli_display_alias_and_group(mock_fetch, mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.load_accounts.return_value = [
        {"email": "test@example.com", "alias": "MyAccount", "group": "MyGroup"}
    ]

    mock_client = MagicMock()
    mock_client.provider.provider_name = "Google"
    mock_fetch.return_value = ("test@example.com", [], mock_client, None)

    runner = CliRunner()
    result = runner.invoke(main)

    assert result.exit_code == 0
    assert "MyAccount" in result.output
    assert "(test@example.com|MyGroup)" in result.output


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
def test_cli_clear_metadata(mock_auth_mgr_cls, mock_config_cls):
    mock_config = mock_config_cls.return_value
    mock_config.auth_path.exists.return_value = True

    mock_auth_mgr = mock_auth_mgr_cls.return_value
    accounts = [{"email": "test@example.com", "alias": "work", "group": "home"}]
    mock_auth_mgr.load_accounts.return_value = accounts
    mock_auth_mgr.update_account_metadata.return_value = True

    runner = CliRunner()
    # Clear alias with empty string and group with "none"
    result = runner.invoke(
        main, ["--account", "test@example.com", "--alias", "", "--group", "none"]
    )

    assert result.exit_code == 0
    mock_auth_mgr.update_account_metadata.assert_called_once_with(
        "test@example.com", {"alias": "", "group": "none"}
    )


@patch("limitwatch.cli.Config")
@patch("limitwatch.cli.AuthManager")
@patch("limitwatch.cli.QuotaClient")
def test_cli_logout_shows_alias(
    mock_quota_client_cls, mock_auth_mgr_cls, mock_config_cls
):
    """Interactive logout should display and use the account alias as the label."""
    mock_auth_mgr = mock_auth_mgr_cls.return_value
    mock_auth_mgr.accounts = [
        {"email": "test@example.com", "alias": "myalias", "type": "google"}
    ]
    mock_quota_client_cls.get_available_providers.return_value = {"google": "Google"}

    runner = CliRunner()
    # Provider 1 (Google), single account (skip account menu), confirm yes
    result = runner.invoke(main, ["--logout"], input="1\ny\n")
    assert result.exit_code == 0
    assert "myalias" in result.output
    mock_auth_mgr.logout.assert_called_once_with("test@example.com")
