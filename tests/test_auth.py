import pytest
from unittest.mock import MagicMock, patch
from limitwatch.auth import AuthManager


@patch("limitwatch.providers.google.InstalledAppFlow")
@patch("limitwatch.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_auth_manager_login_google(mock_session_cls, mock_flow_cls, tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)

    # Mock OAuth flow
    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_creds.refresh_token = "new_refresh_token"
    mock_flow.run_local_server.return_value = mock_creds

    # Mock userinfo session
    mock_session = mock_session_cls.return_value
    mock_session.get.return_value.json.return_value = {"email": "new@example.com"}

    # Mock project ID call (loadCodeAssist)
    mock_session.post.return_value.status_code = 200
    mock_session.post.return_value.json.return_value = {
        "cloudaicompanionProject": "test-project-123"
    }

    # Simulate provider login result
    account_data = {
        "type": "google",
        "email": "new@example.com",
        "refreshToken": "new_refresh_token",
        "projectId": "test-project-123",
    }

    email = auth_mgr.login(account_data)

    assert email == "new@example.com"
    assert len(auth_mgr.accounts) == 1
    assert auth_mgr.accounts[0]["type"] == "google"
    assert auth_mgr.accounts[0]["email"] == "new@example.com"
    assert auth_mgr.accounts[0]["refreshToken"] == "new_refresh_token"
    assert auth_mgr.accounts[0]["projectId"] == "test-project-123"


@patch("requests.get")
def test_auth_manager_login_chutes(mock_get, tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"email": "chutes@example.com"}

    # Simulate provider login result
    account_data = {
        "type": "chutes",
        "email": "chutes@example.com",
        "apiKey": "fake_api_key",
    }

    email = auth_mgr.login(account_data)

    assert email == "chutes@example.com"
    assert len(auth_mgr.accounts) == 1
    assert auth_mgr.accounts[0]["type"] == "chutes"
    assert auth_mgr.accounts[0]["apiKey"] == "fake_api_key"


def test_auth_manager_save_load(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)

    auth_mgr.accounts = [{"email": "test@example.com", "type": "google"}]
    auth_mgr.active_index = 0
    auth_mgr.save_accounts()

    assert auth_file.exists()

    new_mgr = AuthManager(auth_file)
    assert len(new_mgr.accounts) == 1
    assert new_mgr.accounts[0]["email"] == "test@example.com"


def test_auth_manager_logout(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [{"email": "test@example.com"}, {"email": "other@example.com"}]

    assert auth_mgr.logout("test@example.com") is True
    assert len(auth_mgr.accounts) == 1
    assert auth_mgr.accounts[0]["email"] == "other@example.com"

    assert auth_mgr.logout("nonexistent@example.com") is False


def test_auth_manager_logout_all(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [{"email": "test@example.com"}]

    auth_mgr.logout_all()
    assert len(auth_mgr.accounts) == 0


def test_auth_manager_get_credentials(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [
        {"email": "test@example.com", "refreshToken": "token1", "type": "google"},
        {"email": "no-token@example.com", "type": "google"},
    ]

    creds = auth_mgr.get_credentials(0)
    assert creds is not None
    assert creds.refresh_token == "token1"

    assert auth_mgr.get_credentials(1) is None
    assert auth_mgr.get_credentials(99) is None


def test_auth_manager_load_accounts_error(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_file.write_text("invalid json")

    auth_mgr = AuthManager(auth_file)
    assert auth_mgr.accounts == []


def test_auth_manager_login_missing_data(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    with pytest.raises(Exception, match="Account data missing"):
        auth_mgr.login({})


def test_auth_manager_refresh_credentials_success(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)

    mock_creds = MagicMock()
    mock_creds.refresh.return_value = None  # refresh doesn't raise

    result = auth_mgr.refresh_credentials(mock_creds)
    assert result is True
    mock_creds.refresh.assert_called_once()


def test_auth_manager_refresh_credentials_failure(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)

    mock_creds = MagicMock()
    mock_creds.refresh.side_effect = Exception("Token expired")

    result = auth_mgr.refresh_credentials(mock_creds)
    assert result is False


def test_auth_manager_login_update_existing(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)

    # First login
    auth_mgr.login(
        {"email": "test@example.com", "type": "google", "refreshToken": "old"}
    )
    assert len(auth_mgr.accounts) == 1

    # Same email+type → update, not add
    auth_mgr.login(
        {"email": "test@example.com", "type": "google", "refreshToken": "new"}
    )
    assert len(auth_mgr.accounts) == 1
    assert auth_mgr.accounts[0]["refreshToken"] == "new"


def test_auth_manager_update_metadata(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [{"email": "test@example.com", "type": "google"}]

    # Set alias and group
    result = auth_mgr.update_account_metadata(
        "test@example.com", {"alias": "my-alias", "group": "work"}
    )
    assert result is True
    assert auth_mgr.accounts[0]["alias"] == "my-alias"
    assert auth_mgr.accounts[0]["group"] == "work"


def test_auth_manager_update_metadata_clear(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [
        {"email": "test@example.com", "type": "google", "alias": "old-alias"}
    ]

    # Clear alias with None
    result = auth_mgr.update_account_metadata("test@example.com", {"alias": None})
    assert result is True
    assert "alias" not in auth_mgr.accounts[0]


def test_auth_manager_update_metadata_clear_with_empty(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [
        {"email": "test@example.com", "type": "google", "alias": "old"}
    ]

    # Clear with empty string
    result = auth_mgr.update_account_metadata("test@example.com", {"alias": ""})
    assert result is True
    assert "alias" not in auth_mgr.accounts[0]


def test_auth_manager_update_metadata_clear_with_none_string(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [
        {"email": "test@example.com", "type": "google", "alias": "old"}
    ]

    # Clear with "none" string
    result = auth_mgr.update_account_metadata("test@example.com", {"alias": "none"})
    assert result is True
    assert "alias" not in auth_mgr.accounts[0]


def test_auth_manager_update_metadata_not_found(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [{"email": "test@example.com", "type": "google"}]

    result = auth_mgr.update_account_metadata("other@example.com", {"alias": "x"})
    assert result is False


def test_auth_manager_update_metadata_clear_nonexistent_key(tmp_path):
    """Clearing a key that doesn't exist should not raise."""
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [{"email": "test@example.com", "type": "google"}]

    result = auth_mgr.update_account_metadata("test@example.com", {"alias": None})
    assert result is True
    assert "alias" not in auth_mgr.accounts[0]


def test_auth_manager_logout_by_alias(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [{"email": "test@example.com", "alias": "my-alias"}]

    assert auth_mgr.logout("my-alias") is True
    assert len(auth_mgr.accounts) == 0
