import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from src.auth import AuthManager


def test_auth_manager_load_save(tmp_path):
    auth_file = tmp_path / "accounts.json"

    # Test loading empty
    auth_mgr = AuthManager(auth_file)
    assert auth_mgr.accounts == []

    # Test saving
    auth_mgr.accounts = [{"email": "test@example.com", "refreshToken": "abc"}]
    auth_mgr.save_accounts()

    assert auth_file.exists()

    # Test reloading
    new_mgr = AuthManager(auth_file)
    assert len(new_mgr.accounts) == 1
    assert new_mgr.accounts[0]["email"] == "test@example.com"


def test_auth_manager_logout(tmp_path):
    auth_file = tmp_path / "accounts.json"
    auth_mgr = AuthManager(auth_file)
    auth_mgr.accounts = [
        {"email": "user1@example.com", "refreshToken": "abc"},
        {"email": "user2@example.com", "refreshToken": "def"},
    ]

    assert auth_mgr.logout("user1@example.com") is True
    assert len(auth_mgr.accounts) == 1
    assert auth_mgr.accounts[0]["email"] == "user2@example.com"

    assert auth_mgr.logout("nonexistent@example.com") is False


@patch("src.auth.InstalledAppFlow")
@patch("google.auth.transport.requests.AuthorizedSession")
def test_auth_manager_login(mock_session_cls, mock_flow_cls, tmp_path):
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

    # Mock project ID call
    mock_session.post.return_value.status_code = 200
    mock_session.post.return_value.json.return_value = {"projectId": "test-project-123"}

    email = auth_mgr.login(services=["AG", "CLI"])

    assert email == "new@example.com"
    assert len(auth_mgr.accounts) == 1
    assert auth_mgr.accounts[0]["email"] == "new@example.com"
    assert auth_mgr.accounts[0]["refreshToken"] == "new_refresh_token"
    assert auth_mgr.accounts[0]["projectId"] == "test-project-123"
