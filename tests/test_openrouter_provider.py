import pytest
from unittest.mock import MagicMock, patch
from limitwatch.providers.openrouter import OpenRouterProvider


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@patch("limitwatch.providers.openrouter.requests.get")
def test_login_success(mock_get):
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "data": {"label": "My Key", "usage": 1.5, "limit": None}
    }

    result = provider.login(api_key="sk-or-v1-abc123")

    assert result["type"] == "openrouter"
    assert result["apiKey"] == "sk-or-v1-abc123"
    assert result["email"] == "My Key"
    assert "OPENROUTER" in result["services"]


@patch("limitwatch.providers.openrouter.requests.get")
def test_login_strips_whitespace(mock_get):
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": {"label": "k"}}

    result = provider.login(api_key="  sk-or-v1-abc  ")
    assert result["apiKey"] == "sk-or-v1-abc"


@patch("limitwatch.providers.openrouter.requests.get")
def test_login_invalid_key_raises(mock_get):
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 401
    mock_get.return_value.text = "Unauthorized"

    with pytest.raises(ValueError, match="Invalid OpenRouter API key"):
        provider.login(api_key="bad-key")


def test_login_missing_key_raises():
    provider = OpenRouterProvider({})
    with pytest.raises(ValueError, match="API key is required"):
        provider.login(api_key="")


# ---------------------------------------------------------------------------
# fetch_quotas – credits endpoint (management key)
# ---------------------------------------------------------------------------


@patch("limitwatch.providers.openrouter.requests.get")
def test_fetch_quotas_credits_endpoint(mock_get):
    account_data = {"type": "openrouter", "apiKey": "sk-or-v1-mgmt", "email": "user"}
    provider = OpenRouterProvider(account_data)

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "data": {"total_credits": 100.0, "total_usage": 25.75}
    }

    results = provider.fetch_quotas()

    assert len(results) == 1
    r = results[0]
    assert r["name"] == "OpenRouter Credits"
    assert r["endpoint"] == "credits"
    assert abs(r["remaining"] - 74.25) < 0.001
    assert abs(r["used"] - 25.75) < 0.001
    assert r["limit"] == 100.0
    assert abs(r["remaining_pct"] - 74.25) < 0.1
    assert r["source_type"] == "OpenRouter"


@patch("limitwatch.providers.openrouter.requests.get")
def test_fetch_quotas_credits_zero_remaining(mock_get):
    account_data = {"type": "openrouter", "apiKey": "sk-or-v1-mgmt", "email": "user"}
    provider = OpenRouterProvider(account_data)

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "data": {"total_credits": 10.0, "total_usage": 10.0}
    }

    results = provider.fetch_quotas()
    assert results[0]["remaining_pct"] == 0.0
    assert results[0]["remaining"] == 0.0


# ---------------------------------------------------------------------------
# fetch_quotas – auth/key fallback (regular API key)
# ---------------------------------------------------------------------------


@patch("limitwatch.providers.openrouter.requests.get")
def test_fetch_quotas_key_info_fallback_with_limit(mock_get):
    account_data = {"type": "openrouter", "apiKey": "sk-or-v1-regular", "email": "user"}
    provider = OpenRouterProvider(account_data)

    def side_effect(url, **kwargs):
        m = MagicMock()
        if "/credits" in url:
            m.status_code = 403
        else:
            m.status_code = 200
            m.json.return_value = {
                "data": {
                    "label": "dev-key",
                    "usage": 5.0,
                    "limit": 50.0,
                    "is_free_tier": False,
                }
            }
        return m

    mock_get.side_effect = side_effect

    results = provider.fetch_quotas()

    assert len(results) == 1
    r = results[0]
    assert r["name"] == "OpenRouter Key"
    assert r["endpoint"] == "auth/key"
    assert abs(r["remaining"] - 45.0) < 0.001
    assert abs(r["remaining_pct"] - 90.0) < 0.1


@patch("limitwatch.providers.openrouter.requests.get")
def test_fetch_quotas_key_info_no_limit(mock_get):
    """When limit is None, remaining_pct is 100 and display shows spend."""
    account_data = {"type": "openrouter", "apiKey": "sk-or-v1-regular", "email": "user"}
    provider = OpenRouterProvider(account_data)

    def side_effect(url, **kwargs):
        m = MagicMock()
        if "/credits" in url:
            m.status_code = 403
        else:
            m.status_code = 200
            m.json.return_value = {
                "data": {"label": "unlimited", "usage": 3.14, "limit": None}
            }
        return m

    mock_get.side_effect = side_effect

    results = provider.fetch_quotas()
    r = results[0]
    assert r["remaining_pct"] == 100.0
    assert "spent" in r["display_name"]


@patch("limitwatch.providers.openrouter.requests.get")
def test_fetch_quotas_unauthorized_raises(mock_get):
    account_data = {"type": "openrouter", "apiKey": "bad", "email": "user"}
    provider = OpenRouterProvider(account_data)

    def side_effect(url, **kwargs):
        m = MagicMock()
        m.status_code = 401
        return m

    mock_get.side_effect = side_effect

    with pytest.raises(ValueError, match="Unauthorized"):
        provider.fetch_quotas()


def test_fetch_quotas_no_key_returns_empty():
    provider = OpenRouterProvider({})
    assert provider.fetch_quotas() == []


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------


def test_provider_metadata():
    provider = OpenRouterProvider({})
    assert provider.provider_name == "OpenRouter"
    assert provider.short_indicator == "R"
    assert provider.primary_color == "cyan"
    assert provider.source_priority == 0


def test_get_color_thresholds():
    provider = OpenRouterProvider({})
    assert provider.get_color({"remaining_pct": 80}) == "cyan"
    assert provider.get_color({"remaining_pct": 30}) == "yellow"
    assert provider.get_color({"remaining_pct": 10}) == "red"


def test_get_sort_key():
    provider = OpenRouterProvider({})
    assert provider.get_sort_key({"name": "A"}) == (0, 0, "A")


def test_filter_quotas_passthrough():
    provider = OpenRouterProvider({})
    quotas = [{"name": "x"}, {"name": "y"}]
    assert provider.filter_quotas(quotas, show_all=False) == quotas
