import json
import base64
import pytest
from unittest.mock import patch, Mock
from gemini_quota.providers.openai import (
    OpenAIProvider,
    _discover_opencode_token,
    _discover_codex_cli_token,
    _refresh_access_token,
    _format_reset_time,
    _build_quota,
    _fetch_user_email_from_api,
    _extract_identity_from_token_claims,
)


# --- Provider properties ---


def test_provider_name():
    provider = OpenAIProvider({})
    assert provider.provider_name == "OpenAI Codex"


def test_source_priority():
    provider = OpenAIProvider({})
    assert provider.source_priority == 3


def test_primary_color():
    provider = OpenAIProvider({})
    assert provider.primary_color == "green"


def test_short_indicator():
    provider = OpenAIProvider({})
    assert provider.short_indicator == "O"


def test_get_color():
    provider = OpenAIProvider({})
    assert provider.get_color({}) == "green"


# --- Token discovery ---


def test_discover_opencode_token_direct(tmp_path):
    """Discover token from flat auth.json with access_token."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"access_token": "tok-123"}))
    assert _discover_opencode_token(auth_file) == "tok-123"


def test_discover_opencode_token_nested(tmp_path):
    """Discover token from nested accounts structure."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps({"accounts": {"openai": {"access_token": "nested-tok"}}})
    )
    assert _discover_opencode_token(auth_file) == "nested-tok"


def test_discover_opencode_token_missing(tmp_path):
    """Return None when auth file doesn't exist."""
    assert _discover_opencode_token(tmp_path / "nonexistent.json") is None


def test_discover_opencode_token_empty(tmp_path):
    """Return None when auth file has no token."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"other": "data"}))
    assert _discover_opencode_token(auth_file) is None


def test_discover_codex_cli_token(tmp_path):
    """Discover tokens from Codex CLI auth.json."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "codex-tok",
                    "refresh_token": "codex-refresh",
                }
            }
        )
    )
    result = _discover_codex_cli_token(auth_file)
    assert result == {"access_token": "codex-tok", "refresh_token": "codex-refresh"}


def test_discover_codex_cli_token_no_refresh(tmp_path):
    """Discover access token without refresh token."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"tokens": {"access_token": "codex-tok"}}))
    result = _discover_codex_cli_token(auth_file)
    assert result == {"access_token": "codex-tok"}


def test_discover_codex_cli_token_missing(tmp_path):
    assert _discover_codex_cli_token(tmp_path / "nonexistent.json") is None


def test_discover_codex_cli_token_flat(tmp_path):
    """Discover tokens when not nested under 'tokens' key."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps({"access_token": "flat-tok", "refresh_token": "flat-refresh"})
    )
    result = _discover_codex_cli_token(auth_file)
    assert result == {"access_token": "flat-tok", "refresh_token": "flat-refresh"}


# --- Token refresh ---


@patch("gemini_quota.providers.openai.requests.post")
def test_refresh_access_token_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "new-tok",
        "refresh_token": "new-refresh",
    }
    result = _refresh_access_token("old-refresh")
    assert result == {"access_token": "new-tok", "refresh_token": "new-refresh"}


@patch("gemini_quota.providers.openai.requests.post")
def test_refresh_access_token_failure(mock_post):
    mock_post.return_value.status_code = 401
    result = _refresh_access_token("bad-refresh")
    assert result is None


@patch("gemini_quota.providers.openai.requests.post")
def test_refresh_access_token_keeps_old_refresh(mock_post):
    """If response doesn't include refresh_token, keep the old one."""
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"access_token": "new-tok"}
    result = _refresh_access_token("old-refresh")
    assert result == {"access_token": "new-tok", "refresh_token": "old-refresh"}


# --- Format reset time ---


def test_format_reset_time_epoch():
    result = _format_reset_time(1700000000)
    assert result == "2023-11-14T22:13:20Z"


def test_format_reset_time_iso():
    result = _format_reset_time("2024-01-15T10:00:00Z")
    assert result == "2024-01-15T10:00:00Z"


def test_format_reset_time_fallback():
    result = _format_reset_time("not-a-date")
    assert result == "not-a-date"


# --- API-based email fetching ---


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_user_email_from_api_success(mock_get):
    """Fetch email from /me endpoint."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"email": "user@example.com"}

    result = _fetch_user_email_from_api("test-token")
    assert result == "user@example.com"


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_user_email_from_api_nested_user(mock_get):
    """Fetch email from nested user object."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"user": {"email": "nested@example.com"}}

    result = _fetch_user_email_from_api("test-token")
    assert result == "nested@example.com"


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_user_email_from_api_not_found(mock_get):
    """Return None when email not found in response."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"other": "data"}

    result = _fetch_user_email_from_api("test-token")
    assert result is None


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_user_email_from_api_username_fallback(mock_get):
    """Use username when email is not present in /me response."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"username": "codex-user"}

    result = _fetch_user_email_from_api("test-token")
    assert result == "codex-user"


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_user_email_from_api_deeply_nested_name(mock_get):
    """Find identity in deeply nested profile payload."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "account": {"profile": {"name": "Nested Name"}}
    }

    result = _fetch_user_email_from_api("test-token")
    assert result == "Nested Name"


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_user_email_from_api_error(mock_get):
    """Return None on API error."""
    mock_get.return_value.status_code = 401

    result = _fetch_user_email_from_api("bad-token")
    assert result is None


def test_extract_identity_from_token_claims_email():
    """Extract email from JWT-like token claims."""
    payload = json.dumps({"email": "claims@example.com"}).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
    token = f"header.{payload_b64}.sig"

    result = _extract_identity_from_token_claims(token)
    assert result == "claims@example.com"


def test_extract_identity_from_token_claims_rejects_oauth_subject():
    """Reject opaque auth-provider subject IDs like google-oauth2|..."""
    payload = json.dumps({"sub": "google-oauth2|100853288500469058968"}).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
    token = f"header.{payload_b64}.sig"

    result = _extract_identity_from_token_claims(token)
    assert result is None


@patch("gemini_quota.providers.openai.requests.get")
def test_validate_token_falls_back_to_token_claims(mock_get):
    """Use token claims when /me lacks account identity fields."""

    payload = json.dumps({"preferred_username": "claims-user"}).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
    token = f"header.{payload_b64}.sig"

    def get_side_effect(url, **kwargs):
        mock_resp = Mock()
        if "/wham/usage" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"plan_type": "plus"}
        elif "/me" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
        return mock_resp

    mock_get.side_effect = get_side_effect
    provider = OpenAIProvider({})

    identity = provider._validate_token(token)
    assert identity == "claims-user"


@patch("gemini_quota.providers.openai.requests.get")
def test_validate_token_ignores_oauth_subject_and_uses_default(mock_get):
    """If only opaque subject exists, fallback to default account label."""

    payload = json.dumps({"sub": "google-oauth2|100853288500469058968"}).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
    token = f"header.{payload_b64}.sig"

    def get_side_effect(url, **kwargs):
        mock_resp = Mock()
        if "/wham/usage" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"plan_type": "plus"}
        elif "/me" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
        return mock_resp

    mock_get.side_effect = get_side_effect
    provider = OpenAIProvider({})

    identity = provider._validate_token(token)
    assert identity == "OpenAI User"


# --- Login ---


@patch("gemini_quota.providers.openai.requests.get")
def test_login_success(mock_get):
    """Test login with email fetched from /me API endpoint."""

    def get_side_effect(url, **kwargs):
        mock_resp = Mock()
        if "/me" in url:
            # API call for user email
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"email": "test@example.com"}
        else:
            # Quota API call
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"plan_type": "plus"}
        return mock_resp

    mock_get.side_effect = get_side_effect

    provider = OpenAIProvider({})
    account = provider.login(access_token="test-token", refresh_token="ref-456")

    assert account["type"] == "openai"
    assert account["email"] == "test@example.com"
    assert account["accessToken"] == "test-token"
    assert account["refreshToken"] == "ref-456"
    assert "OPENAI_CODEX" in account["services"]


def test_login_no_token():
    provider = OpenAIProvider({})
    with pytest.raises(Exception, match="access token is required"):
        provider.login()


@patch("gemini_quota.providers.openai.requests.get")
def test_login_invalid_token(mock_get):
    mock_get.return_value.status_code = 401
    provider = OpenAIProvider({})
    with pytest.raises(Exception, match="Token validation failed"):
        provider.login(access_token="bad-token")


@patch("gemini_quota.providers.openai.requests.get")
def test_login_with_token_refresh(mock_get):
    """Login refreshes token on 401 and retries."""
    call_count = [0]

    def side_effect(url, **kwargs):
        mock_resp = Mock()
        call_count[0] += 1

        if "/me" in url:
            # API call for user email (succeeds immediately)
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"email": "refreshed@example.com"}
        else:
            # Quota API call (fails first, then succeeds after refresh)
            if call_count[0] == 1:
                mock_resp.status_code = 401
            else:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"plan_type": "pro"}
        return mock_resp

    mock_get.side_effect = side_effect

    with patch("gemini_quota.providers.openai._refresh_access_token") as mock_refresh:
        mock_refresh.return_value = {
            "access_token": "refreshed-token",
            "refresh_token": "new-refresh",
        }
        provider = OpenAIProvider({})
        account = provider.login(access_token="old-tok", refresh_token="old-refresh")
        assert account["email"] == "refreshed@example.com"
        assert account["accessToken"] == "refreshed-token"


# --- Fetch quotas ---


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_primary_and_secondary(mock_get):
    """Parse a full usage response with primary and secondary windows."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {
                "used_percent": 30.0,
                "limit_window_seconds": 18000,
                "reset_at": 1700000000,
            },
            "secondary_window": {
                "used_percent": 10.0,
                "limit_window_seconds": 604800,
                "reset_at": 1700500000,
            },
        },
    }

    provider = OpenAIProvider({"accessToken": "tok", "email": "user"})
    quotas = provider.fetch_quotas()

    assert len(quotas) == 2

    primary = quotas[0]
    assert "Primary" in primary["display_name"]
    assert "5h" in primary["display_name"]
    assert primary["used_pct"] == 30.0
    assert primary["remaining_pct"] == 70.0
    assert primary["source_type"] == "OpenAI Codex"

    secondary = quotas[1]
    assert "Secondary" in secondary["display_name"]
    assert secondary["used_pct"] == 10.0


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_with_credits(mock_get):
    """Parse usage response with credits."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_type": "pro",
        "rate_limit": {},
        "credits": {
            "has_credits": True,
            "unlimited": False,
            "balance": 75.5,
        },
    }

    provider = OpenAIProvider({"accessToken": "tok", "email": "user"})
    quotas = provider.fetch_quotas()

    credits = [q for q in quotas if "Credits" in q.get("display_name", "")]
    assert len(credits) == 1
    assert credits[0]["balance"] == 75.5


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_empty_response(mock_get):
    """Empty rate_limit still returns a generic entry."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_type": "plus",
        "rate_limit": {},
    }

    provider = OpenAIProvider({"accessToken": "tok", "email": "user"})
    quotas = provider.fetch_quotas()

    assert len(quotas) == 1
    assert quotas[0]["remaining_pct"] == 100.0


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_no_token(mock_get):
    """No token returns empty list."""
    provider = OpenAIProvider({"email": "user"})
    quotas = provider.fetch_quotas()
    assert quotas == []
    mock_get.assert_not_called()


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_http_error(mock_get):
    """Non-200 response returns error quota."""
    mock_get.return_value.status_code = 500

    provider = OpenAIProvider({"accessToken": "tok", "email": "user"})
    quotas = provider.fetch_quotas()

    assert len(quotas) == 1
    assert quotas[0].get("is_error") is True


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_network_error(mock_get):
    """Network error returns error quota."""
    import requests as req

    mock_get.side_effect = req.ConnectionError("Network unreachable")

    provider = OpenAIProvider({"accessToken": "tok", "email": "user"})
    quotas = provider.fetch_quotas()

    assert len(quotas) == 1
    assert quotas[0].get("is_error") is True


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_token_refresh_on_401(mock_get):
    """Fetch retries with refreshed token on 401."""
    call_count = [0]

    def side_effect(*args, **kwargs):
        mock_resp = Mock()
        call_count[0] += 1
        if call_count[0] == 1:
            mock_resp.status_code = 401
        else:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "plan_type": "plus",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 50.0,
                        "limit_window_seconds": 18000,
                    }
                },
            }
        return mock_resp

    mock_get.side_effect = side_effect

    with patch("gemini_quota.providers.openai._refresh_access_token") as mock_refresh:
        mock_refresh.return_value = {
            "access_token": "new-tok",
            "refresh_token": "new-ref",
        }
        provider = OpenAIProvider(
            {"accessToken": "old-tok", "refreshToken": "old-ref", "email": "user"}
        )
        quotas = provider.fetch_quotas()

        assert len(quotas) == 1
        assert quotas[0]["used_pct"] == 50.0
        assert provider.access_token == "new-tok"


# --- Filtering / Sorting ---


def test_filter_quotas_returns_all():
    provider = OpenAIProvider({})
    quotas = [{"name": "a"}, {"name": "b"}]
    assert provider.filter_quotas(quotas, show_all=False) == quotas


def test_sort_key_primary_first():
    provider = OpenAIProvider({})
    primary = {"display_name": "Primary (5h)"}
    secondary = {"display_name": "Secondary (168h)"}
    credits = {"display_name": "Credits"}
    other = {"display_name": "Something"}

    keys = [provider.get_sort_key(q) for q in [other, credits, secondary, primary]]
    sorted_quotas = [
        q
        for _, q in sorted(
            zip(keys, [other, credits, secondary, primary]), key=lambda x: x[0]
        )
    ]
    assert sorted_quotas[0] == primary
    assert sorted_quotas[1] == secondary
    assert sorted_quotas[2] == credits
    assert sorted_quotas[3] == other


# --- Build quota helper ---


def test_build_quota():
    q = _build_quota("Name", "Display", 80.0, 20.0, "2024-01-01", extra_key="val")
    assert q["name"] == "Name"
    assert q["display_name"] == "Display"
    assert q["remaining_pct"] == 80.0
    assert q["used_pct"] == 20.0
    assert q["reset"] == "2024-01-01"
    assert q["source_type"] == "OpenAI Codex"
    assert q["extra_key"] == "val"


# --- Parse window ---


def test_parse_window_5h():
    result = OpenAIProvider._parse_window(
        {
            "used_percent": 42.5,
            "limit_window_seconds": 18000,
            "reset_at": 1700000000,
        },
        "plus",
        "Primary",
    )
    assert result["used_pct"] == 42.5
    assert result["remaining_pct"] == 57.5
    assert "5h" in result["display_name"]
    assert result["window_seconds"] == 18000


def test_parse_window_weekly():
    result = OpenAIProvider._parse_window(
        {
            "used_percent": 5.0,
            "limit_window_seconds": 604800,
        },
        "pro",
        "Secondary",
    )
    assert result["used_pct"] == 5.0
    assert result["remaining_pct"] == 95.0
    assert "7d" in result["display_name"]


def test_parse_window_minutes():
    result = OpenAIProvider._parse_window(
        {"used_percent": 0.0, "limit_window_seconds": 1800},
        "plus",
        "Test",
    )
    assert "30m" in result["display_name"]


def test_parse_window_no_duration():
    result = OpenAIProvider._parse_window(
        {"used_percent": 10.0},
        "plus",
        "Label",
    )
    assert result["display_name"] == "Label"


# --- Additional rate limits ---


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_additional_rate_limits(mock_get):
    """Parse additional rate limits from response."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_type": "pro",
        "rate_limit": {
            "primary_window": {
                "used_percent": 20.0,
                "limit_window_seconds": 18000,
            },
        },
        "additional_rate_limits": [
            {
                "name": "Cloud Tasks",
                "primary_window": {
                    "used_percent": 60.0,
                    "limit_window_seconds": 18000,
                },
            }
        ],
    }

    provider = OpenAIProvider({"accessToken": "tok", "email": "user"})
    quotas = provider.fetch_quotas()

    assert len(quotas) == 2
    cloud = [q for q in quotas if "Cloud Tasks" in q.get("display_name", "")]
    assert len(cloud) == 1
    assert cloud[0]["used_pct"] == 60.0


@patch("gemini_quota.providers.openai.requests.get")
def test_fetch_quotas_free_tier_with_none_values(mock_get):
    """Handle free tier response with None values for rate limits."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_type": "free",
        "rate_limit": None,
        "credits": None,
        "additional_rate_limits": None,
    }

    provider = OpenAIProvider({"accessToken": "tok", "email": "user"})
    quotas = provider.fetch_quotas()

    assert len(quotas) == 1
    assert quotas[0]["plan_type"] == "free"
    assert "Plan: Free" in quotas[0]["display_name"]
    assert quotas[0]["remaining_pct"] == 100.0
    assert quotas[0]["reset"] == "No quota limits"
