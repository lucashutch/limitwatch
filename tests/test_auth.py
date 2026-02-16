from unittest.mock import MagicMock, patch
from gemini_quota.auth import AuthManager


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
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
