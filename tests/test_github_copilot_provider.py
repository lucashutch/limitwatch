import pytest
from unittest.mock import patch, Mock, MagicMock
from gemini_quota.providers.github_copilot import GitHubCopilotProvider


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_login(mock_get):
    """Test GitHub Copilot provider login with token."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"login": "testuser"}

    provider = GitHubCopilotProvider({})
    account_data = provider.login(token="fake-token")

    assert account_data["type"] == "github_copilot"
    assert account_data["email"] == "testuser"
    assert account_data["githubToken"] == "fake-token"
    assert "GITHUB_COPILOT" in account_data["services"]


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_login_with_org(mock_get):
    """Test GitHub Copilot provider login with organization."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"login": "testuser"}

    provider = GitHubCopilotProvider({})
    account_data = provider.login(token="fake-token", organization="myorg")

    assert account_data["organization"] == "myorg"


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_login_failure(mock_get):
    """Test GitHub Copilot provider login failure."""
    mock_get.return_value.status_code = 401

    provider = GitHubCopilotProvider({})
    with pytest.raises(Exception, match="Failed to authenticate"):
        provider.login(token="invalid-token")


def test_github_copilot_provider_login_no_token():
    """Test GitHub Copilot provider login without token."""
    provider = GitHubCopilotProvider({})
    with pytest.raises(Exception, match="GitHub token is required"):
        provider.login()


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_personal_quota(mock_get):
    """Test fetching personal Copilot quota from user endpoint."""
    account_data = {
        "type": "github_copilot",
        "email": "testuser",
        "githubToken": "fake-token",
    }
    provider = GitHubCopilotProvider(account_data)

    # Mock user endpoint returning quota data
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "seat_breakdown": {
            "total": 100,
            "active_this_cycle": 1,
        }
    }

    quotas = provider.fetch_quotas()

    # Should have personal quota with usage shown
    personal_quotas = [q for q in quotas if "Personal" in q.get("display_name", "")]
    assert len(personal_quotas) > 0
    assert personal_quotas[0]["display_name"] == "Personal"
    assert personal_quotas[0]["remaining_pct"] == 99.0


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_quota(mock_get):
    """Test fetching org Copilot quota."""
    account_data = {
        "type": "github_copilot",
        "email": "testuser",
        "githubToken": "fake-token",
        "organization": "myorg",
    }
    provider = GitHubCopilotProvider(account_data)

    # Mock responses for personal and org
    def mock_get_side_effect(*args, **kwargs):
        mock_resp = Mock()
        url = args[0] if args else ""
        if "copilot/billing" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "seat_breakdown": {
                    "total": 10,
                    "active_this_cycle": 7,
                }
            }
        else:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
        return mock_resp

    mock_get.side_effect = mock_get_side_effect

    quotas = provider.fetch_quotas()

    # Should have both personal and org quota
    assert len(quotas) == 2
    org_quota = [q for q in quotas if "myorg" in q.get("display_name", "")][0]
    assert org_quota["remaining_pct"] == 30.0  # (10 - 7) / 10 = 0.3 = 30%
    assert org_quota["remaining"] == 3
    assert org_quota["limit"] == 10


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_quota_error(mock_get):
    """Test org quota fetch error handling."""
    account_data = {
        "type": "github_copilot",
        "email": "testuser",
        "githubToken": "fake-token",
        "organization": "myorg",
    }
    provider = GitHubCopilotProvider(account_data)

    def mock_get_side_effect(*args, **kwargs):
        mock_resp = Mock()
        url = args[0] if args else ""
        if "copilot/billing" in url:
            mock_resp.status_code = 403
        else:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
        return mock_resp

    mock_get.side_effect = mock_get_side_effect

    quotas = provider.fetch_quotas()

    # Should include error quota
    error_quotas = [q for q in quotas if q.get("is_error")]
    assert len(error_quotas) > 0
    assert "myorg" in error_quotas[0].get("display_name", "")


def test_github_copilot_provider_properties():
    """Test provider metadata properties."""
    provider = GitHubCopilotProvider({})

    assert provider.provider_name == "GitHub Copilot"
    assert provider.short_indicator == "H"
    assert provider.primary_color == "white"
    assert provider.source_priority == 2


def test_github_copilot_provider_filter_quotas():
    """Test quota filtering."""
    provider = GitHubCopilotProvider({})
    quotas = [
        {"display_name": "Copilot: Personal (Available)"},
        {"display_name": "Copilot: myorg (active)"},
    ]

    filtered = provider.filter_quotas(quotas, show_all=False)
    assert len(filtered) == 2  # All quotas shown


def test_github_copilot_provider_sort_key():
    """Test sort key generation."""
    provider = GitHubCopilotProvider({})

    personal_quota = {"display_name": "Copilot: Personal (Available)"}
    org_quota = {"display_name": "Copilot: myorg (active)"}

    personal_key = provider.get_sort_key(personal_quota)
    org_key = provider.get_sort_key(org_quota)

    # Personal should sort before org (lower priority number)
    assert personal_key[1] < org_key[1]


@patch("gemini_quota.providers.github_copilot.subprocess.run")
def test_github_copilot_provider_get_gh_token(mock_run):
    """Test retrieving token from gh CLI."""
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "gh-secret-token\n"

    provider = GitHubCopilotProvider({})
    token = provider._get_gh_token()

    assert token == "gh-secret-token"
    mock_run.assert_called_with(
        ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
    )


@patch("gemini_quota.providers.github_copilot.subprocess.run")
def test_github_copilot_provider_get_gh_token_failure(mock_run):
    """Test gh token retrieval when gh is not installed."""
    mock_run.side_effect = FileNotFoundError()

    provider = GitHubCopilotProvider({})
    token = provider._get_gh_token()

    assert token is None


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_404_error(mock_get):
    """Test org quota fetch 404 error (Copilot not enabled)."""
    account_data = {
        "type": "github_copilot",
        "email": "testuser",
        "githubToken": "fake-token",
        "organization": "myorg",
    }
    provider = GitHubCopilotProvider(account_data)

    def mock_get_side_effect(*args, **kwargs):
        mock_resp = Mock()
        url = args[0] if args else ""
        if "copilot/billing" in url:
            mock_resp.status_code = 404
        else:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
        return mock_resp

    mock_get.side_effect = mock_get_side_effect

    quotas = provider.fetch_quotas()

    # Should include 404 error quota
    error_quotas = [q for q in quotas if q.get("is_error")]
    assert len(error_quotas) > 0
    assert "not found or disabled" in error_quotas[0].get("message", "").lower()


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_discover_orgs(mock_get):
    """Test organization auto-discovery."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [
        {"login": "org-a"},
        {"login": "org-b"},
        {"login": "org-c"},
    ]

    provider = GitHubCopilotProvider({})
    orgs = provider._discover_organizations("fake-token")

    assert len(orgs) == 3
    assert "org-a" in orgs
    assert "org-b" in orgs
    assert "org-c" in orgs
    # Check they're sorted
    assert orgs == sorted(orgs)


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_discover_orgs_empty(mock_get):
    """Test organization discovery with no orgs."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = []

    provider = GitHubCopilotProvider({})
    orgs = provider._discover_organizations("fake-token")

    assert len(orgs) == 0


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_discover_orgs_failure(mock_get):
    """Test organization discovery failure."""
    mock_get.return_value.status_code = 401

    provider = GitHubCopilotProvider({})
    orgs = provider._discover_organizations("invalid-token")

    assert len(orgs) == 0


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_personal_via_user_endpoint(mock_get):
    """Test personal quota via user endpoint."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "seat_breakdown": {
            "total": 50,
            "active_this_cycle": 1,
        }
    }

    quota = provider._fetch_personal_copilot_quota(headers)

    assert quota is not None
    assert quota["display_name"] == "Personal"
    assert quota["remaining_pct"] == 98.0
    assert quota["used_pct"] == 2.0


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_personal_via_copilot_internal(mock_get):
    """Test personal quota via copilot_internal user endpoint (individual plan)."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({"githubToken": "fake-token"})

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "copilot_plan": "individual",
        "quota_reset_date": "2026-03-01T00:00:00Z",
        "quota_snapshots": {
            "premium_interactions": {
                "entitlement": 100,
                "remaining": 98.8,
                "percent_remaining": 98.8,
                "overage_count": 0,
                "overage_permitted": False,
            }
        },
    }

    quota = provider._fetch_personal_copilot_quota(headers)

    assert quota is not None
    assert "Personal" in quota["display_name"]
    assert abs(quota["used_pct"] - 1.2) < 0.01
    assert abs(quota["remaining_pct"] - 98.8) < 0.01
    assert quota["reset"] == "2026-03-01T00:00:00Z"


@patch("gemini_quota.providers.github_copilot.subprocess.run")
@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_personal_not_shown_for_business_plan(
    mock_get, mock_subprocess
):
    """Business/enterprise plan: internal snapshot is org-pool data, not personal."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({"githubToken": "fake-token"})

    # First call: copilot_internal/user → business plan (plan-gated, skipped)
    internal_resp = MagicMock()
    internal_resp.status_code = 200
    internal_resp.json.return_value = {
        "copilot_plan": "business",
        "organization_login_list": ["myorg"],
        "quota_reset_date": "2026-03-01T00:00:00Z",
        "quota_snapshots": {
            "premium_interactions": {
                "entitlement": 300,
                "remaining": 295,
                "percent_remaining": 98.3,
                "overage_count": 0,
                "overage_permitted": False,
            }
        },
    }
    # Subsequent calls (Try 2 billing endpoint) → 403 so fallback also fails
    billing_resp = MagicMock()
    billing_resp.status_code = 403
    mock_get.side_effect = [internal_resp, billing_resp]
    mock_subprocess.side_effect = FileNotFoundError()

    # _fetch_personal_copilot_quota must return None for business users
    quota = provider._fetch_personal_copilot_quota(headers)
    assert quota is None


@patch("gemini_quota.providers.github_copilot.subprocess.run")
@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_personal_not_shown_when_plan_unknown_org_present(
    mock_get, mock_subprocess
):
    """Unknown internal plan with org membership should not be shown as personal usage."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider(
        {"githubToken": "fake-token", "organization": "myorg"}
    )

    internal_resp = MagicMock()
    internal_resp.status_code = 200
    internal_resp.json.return_value = {
        "organization_login_list": ["myorg"],
        "quota_reset_date": "2026-03-01T00:00:00Z",
        "quota_snapshots": {
            "premium_interactions": {
                "entitlement": 300,
                "remaining": 293,
                "percent_remaining": 97.7,
            }
        },
    }
    billing_resp = MagicMock()
    billing_resp.status_code = 403
    mock_get.side_effect = [internal_resp, billing_resp]
    mock_subprocess.side_effect = FileNotFoundError()

    quota = provider._fetch_personal_copilot_quota(headers)
    assert quota is None


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_personal_free_plan_shows_tier_label(mock_get):
    """Free plan: show 'Personal' label with zero usage."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({"githubToken": "fake-token"})

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "copilot_plan": "free",
        "quota_reset_date": "2026-03-01T00:00:00Z",
        "quota_snapshots": {
            "premium_interactions": {
                "entitlement": 50,
                "remaining": 40,
                "percent_remaining": 80.0,
            }
        },
    }

    quota = provider._fetch_personal_copilot_quota(headers)

    assert quota is not None
    assert quota["display_name"] == "Personal"
    assert quota["used_pct"] == 0.0
    assert quota["remaining_pct"] == 100.0


@patch("gemini_quota.providers.github_copilot.subprocess.run")
@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_personal_fallback_to_none(
    mock_get, mock_subprocess
):
    """Test personal quota fallback when endpoint fails."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    mock_get.return_value.status_code = 401
    mock_subprocess.side_effect = FileNotFoundError()

    quota = provider._fetch_personal_copilot_quota(headers)

    # Should return None and let caller handle fallback
    assert quota is None


@patch("gemini_quota.providers.github_copilot.subprocess.run")
def test_github_copilot_provider_get_usage_via_gh(mock_run):
    """Test fetching usage via gh CLI."""
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = '{"copilot_plan":"individual","quota_snapshots":{"premium_interactions":{"percent_remaining":95.0}}}'

    provider = GitHubCopilotProvider({})
    usage = provider._get_copilot_usage_via_gh()

    assert usage is not None
    assert usage["usage_percentage"] == 5.0


@patch("gemini_quota.providers.github_copilot.subprocess.run")
def test_github_copilot_provider_get_usage_via_gh_failure(mock_run):
    """Test gh CLI usage fetch when gh is not available."""
    mock_run.side_effect = FileNotFoundError()

    provider = GitHubCopilotProvider({})
    usage = provider._get_copilot_usage_via_gh()

    assert usage is None


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_member_copilot_quota(mock_get):
    """Test member-level Copilot quota fetch."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    def mock_get_side_effect(*args, **kwargs):
        mock_resp = Mock()
        url = args[0] if args else ""
        if "/user" in url and "members" not in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"login": "testuser"}
        elif "members/testuser/copilot" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "plan_type": "business",
                "last_activity_at": "2026-02-24T10:30:00Z",
            }
        else:
            mock_resp.status_code = 404
        return mock_resp

    mock_get.side_effect = mock_get_side_effect

    quota = provider._fetch_member_copilot_quota(headers, "myorg")

    assert quota is not None
    assert quota["display_name"] == "myorg"
    assert quota["remaining_pct"] == 100.0


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_member_quota_user_lookup_fails(mock_get):
    """Test member quota when user lookup fails."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    mock_get.return_value.status_code = 401

    quota = provider._fetch_member_copilot_quota(headers, "myorg")

    assert quota is None


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_success(mock_get):
    """Test organization quota fetch success."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "seat_breakdown": {
            "total": 25,
            "active_this_cycle": 18,
        }
    }

    quota = provider._fetch_org_copilot_quota(headers, "myorg")

    assert quota is not None
    assert "myorg" in quota["display_name"]
    # display_name now shows only the org name; seat usage is reflected via used_pct
    assert "active" not in quota["display_name"]
    assert abs(quota["used_pct"] - 72.0) < 0.01  # 18/25 = 72%
    assert (
        abs(quota["remaining_pct"] - 28.0) < 0.01
    )  # Account for floating point precision


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_403_error(mock_get):
    """Test organization quota fetch 403 (permission denied)."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    mock_get.return_value.status_code = 403

    quota = provider._fetch_org_copilot_quota(headers, "myorg")

    assert quota is not None
    assert quota.get("is_error") is True
    assert "Insufficient permissions" in quota["message"]


@patch("gemini_quota.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_fallback_to_internal_org(mock_get):
    """Test org fallback to copilot_internal org list when billing/member fail."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({"githubToken": "fake-token"})

    def mock_get_side_effect(*args, **kwargs):
        mock_resp = Mock()
        url = args[0] if args else ""
        if "orgs/myorg/copilot/billing" in url:
            mock_resp.status_code = 403
            return mock_resp
        if "orgs/myorg/members/" in url:
            mock_resp.status_code = 404
            return mock_resp
        if "copilot_internal/user" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "organization_login_list": ["myorg"],
                "quota_reset_date": "2026-03-01T00:00:00Z",
                "quota_snapshots": {
                    "premium_interactions": {
                        "percent_remaining": 98.8,
                    }
                },
            }
            return mock_resp
        if url.endswith("/user"):
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"login": "testuser"}
            return mock_resp

        mock_resp.status_code = 404
        return mock_resp

    mock_get.side_effect = mock_get_side_effect

    quota = provider._fetch_org_copilot_quota(headers, "myorg")

    assert quota is not None
    assert quota.get("is_error") is not True
    assert quota["display_name"] == "myorg"
    assert abs(quota["used_pct"] - 1.2) < 0.01
