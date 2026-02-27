from unittest.mock import MagicMock, patch
from limitwatch.providers.chutes import ChutesProvider


@patch("limitwatch.providers.chutes.requests.get")
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


@patch("limitwatch.providers.chutes.requests.get")
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
@patch("limitwatch.providers.chutes.requests.get")
def test_chutes_interactive_login_strip(mock_get, mock_prompt):
    provider = ChutesProvider({})
    mock_prompt.return_value = "  padded_key  "
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"email": "test@example.com"}

    result = provider.interactive_login(MagicMock())

    assert result["apiKey"] == "padded_key"
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "padded_key"


@patch("limitwatch.providers.chutes.requests.get")
def test_chutes_fetch_quotas_no_list_fallback(mock_get):
    provider = ChutesProvider({"apiKey": "fake_key"})

    def side_effect(url, **kwargs):
        m = MagicMock()
        if "/users/me/quotas" in url:
            m.status_code = 404  # List fails
        elif "/users/me/quota_usage/me" in url:
            m.status_code = 200
            m.json.return_value = {"quota": 100, "used": 20, "chute_id": "me"}
        elif "/users/me" in url:
            m.status_code = 200
            m.json.return_value = {"balance": 0.0}  # No balance item
        return m

    mock_get.side_effect = side_effect

    results = provider.fetch_quotas()
    assert len(results) == 1
    assert "(80/100)" in results[0]["display_name"]


def test_chutes_provider_metadata():
    provider = ChutesProvider({"apiKey": "k"})
    assert provider.provider_name == "Chutes"
    assert provider.source_priority == 0
    assert provider.primary_color == "yellow"
    assert provider.get_color({}) == "yellow"


@patch("limitwatch.providers.chutes.requests.get")
def test_chutes_fetch_quotas_no_quota_info(mock_get):
    provider = ChutesProvider({"apiKey": "fake_key"})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = []  # Empty list of quotas

    # Still should fetch balance if any
    results = provider.fetch_quotas()
    assert len(results) == 0  # no balance returned by default mock here


def test_chutes_provider_filter_quotas():
    provider = ChutesProvider({})
    quotas = [{"name": "q1"}]
    assert provider.filter_quotas(quotas, False) == quotas


def test_chutes_provider_sort_key():
    provider = ChutesProvider({})
    assert provider.get_sort_key({"name": "Balance"}) == (0, 0, "Balance")
    assert provider.get_sort_key({"name": "Quota"}) == (0, 1, "Quota")
