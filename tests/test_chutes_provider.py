import pytest
from unittest.mock import MagicMock, patch
from gemini_quota.providers.chutes import ChutesProvider


@patch("gemini_quota.providers.chutes.requests.get")
def test_chutes_login_success(mock_get):
    provider = ChutesProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "email": "test@example.com",
        "id": "user-123",
    }

    result = provider.login(api_key="  secret_key  ")

    assert result["email"] == "test@example.com"
    assert (
        result["apiKey"] == "  secret_key  "
    )  # login doesn't strip, interactive_login does
    assert result["type"] == "chutes"

    # Verify headers
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == "  secret_key  "
    assert kwargs["headers"]["Content-Type"] == "application/json"


@patch("gemini_quota.providers.chutes.requests.get")
def test_chutes_fetch_quotas_success(mock_get):
    account_data = {"type": "chutes", "apiKey": "fake_key"}
    provider = ChutesProvider(account_data)

    def side_effect(url, **kwargs):
        m = MagicMock()
        m.status_code = 200
        if "/users/me/quotas" in url:
            m.json.return_value = [
                {"chute_id": "*", "quota": 300},
                {"chute_id": "other-uuid", "quota": 100},
            ]
        elif "/users/me/quota_usage/*" in url:
            m.json.return_value = {"quota": 300, "used": 50, "chute_id": "*"}
        elif "/users/me/quota_usage/other-uuid" in url:
            m.json.return_value = {"quota": 100, "used": 10, "chute_id": "other-uuid"}
        elif "/users/me" in url:
            m.json.return_value = {"balance": 5.0}
        else:
            m.status_code = 404
        return m

    mock_get.side_effect = side_effect

    results = provider.fetch_quotas()

    # Balance + 2 Quotas
    assert len(results) == 3
    assert any("Balance: $5.00" in r["display_name"] for r in results)
    assert any("Quota (250/300)" in r["display_name"] for r in results)
    assert any("Quota: other-uu... (90/100)" in r["display_name"] for r in results)

    # Verify headers were sent correctly in all calls
    for call in mock_get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "fake_key"
        assert call.kwargs["headers"]["Content-Type"] == "application/json"


@patch("click.prompt")
@patch("gemini_quota.providers.chutes.requests.get")
def test_chutes_interactive_login_strip(mock_get, mock_prompt):
    provider = ChutesProvider({})
    mock_prompt.return_value = "  padded_key  "
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"email": "test@example.com"}

    result = provider.interactive_login(MagicMock())

    assert result["apiKey"] == "padded_key"
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "padded_key"


@patch("gemini_quota.providers.chutes.requests.get")
def test_chutes_fetch_quotas_auth_error(mock_get):
    provider = ChutesProvider({"apiKey": "wrong_key"})
    mock_get.return_value.status_code = 401
    mock_get.return_value.text = "Unauthorized"

    with pytest.raises(Exception) as excinfo:
        provider.fetch_quotas()

    assert "Unauthorized" in str(excinfo.value)
