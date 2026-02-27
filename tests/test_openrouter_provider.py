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


@patch("limitwatch.providers.openrouter.requests.get")
def test_login_explicit_name_kwarg_overrides_label(mock_get):
    """A `name` kwarg takes priority over the API-returned label."""
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": {"label": "sk-or-v1-5f2...aaa"}}

    result = provider.login(api_key="sk-or-v1-abc", name="limitwatch_work_laptop")
    assert result["email"] == "limitwatch_work_laptop"


@patch("limitwatch.providers.openrouter.requests.get")
def test_login_uses_non_redacted_label(mock_get):
    """When the API returns a real name (no '...'), use it directly."""
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": {"label": "my-named-key"}}

    result = provider.login(api_key="sk-or-v1-abc")
    assert result["email"] == "my-named-key"


# ---------------------------------------------------------------------------
# interactive_login
# ---------------------------------------------------------------------------


@patch("click.prompt")
@patch("limitwatch.providers.openrouter.requests.get")
def test_interactive_login_prompts_friendly_name_when_redacted(mock_get, mock_prompt):
    """When the API label looks like a redacted key, user is prompted for a name."""
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": {"label": "sk-or-v1-5f2...aaa"}}
    # First prompt: API key, second: friendly name
    mock_prompt.side_effect = ["sk-or-v1-realkey", "limitwatch_work_laptop"]

    result = provider.interactive_login(MagicMock())

    assert result["email"] == "limitwatch_work_laptop"
    assert result["apiKey"] == "sk-or-v1-realkey"
    assert mock_prompt.call_count == 2


@patch("click.prompt")
@patch("limitwatch.providers.openrouter.requests.get")
def test_interactive_login_keeps_default_redacted_if_unchanged(mock_get, mock_prompt):
    """If user doesn't change the default name, the redacted label is stored."""
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": {"label": "sk-or-v1-5f2...aaa"}}
    # User accepts the default (returns the same redacted key string)
    mock_prompt.side_effect = ["sk-or-v1-realkey", "sk-or-v1-5f2...aaa"]

    result = provider.interactive_login(MagicMock())

    assert result["email"] == "sk-or-v1-5f2...aaa"


@patch("click.prompt")
@patch("limitwatch.providers.openrouter.requests.get")
def test_interactive_login_skips_name_prompt_for_real_label(mock_get, mock_prompt):
    """When API label is a real name (no '...'), skip the name prompt."""
    provider = OpenRouterProvider({})
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": {"label": "my-production-key"}}
    mock_prompt.return_value = "sk-or-v1-realkey"

    result = provider.interactive_login(MagicMock())

    assert result["email"] == "my-production-key"
    assert mock_prompt.call_count == 1  # only the API key prompt


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
    assert r["show_progress"] is False
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
    assert r["show_progress"] is False


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
    assert r["show_progress"] is False
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
