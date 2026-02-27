import pytest
from unittest.mock import patch, Mock, MagicMock
from limitwatch.providers.github_copilot import (
    GitHubCopilotProvider,
    _make_github_headers,
    _next_month_reset_iso,
    _seat_percentages,
    _build_org_error,
    _build_personal_quota,
)


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
def test_github_copilot_provider_login_with_org(mock_get):
    """Test GitHub Copilot provider login with organization."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"login": "testuser"}

    provider = GitHubCopilotProvider({})
    account_data = provider.login(token="fake-token", organization="myorg")

    assert account_data["organization"] == "myorg"


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.subprocess.run")
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


@patch("limitwatch.providers.github_copilot.subprocess.run")
def test_github_copilot_provider_get_gh_token_failure(mock_run):
    """Test gh token retrieval when gh is not installed."""
    mock_run.side_effect = FileNotFoundError()

    provider = GitHubCopilotProvider({})
    token = provider._get_gh_token()

    assert token is None


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_404_uses_fallback_if_available(mock_get):
    """On 404 org billing, fallback endpoints should still be able to return org quota."""
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

        if "orgs/myorg/copilot/billing" in url:
            mock_resp.status_code = 404
            return mock_resp

        if "orgs/myorg/members/testuser/copilot" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
            return mock_resp

        if "/user" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"login": "testuser"}
            return mock_resp

        if "copilot_internal/user" in url:
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "organization_login_list": ["myorg"],
                "quota_reset_date": "2026-03-01T00:00:00Z",
                "quota_snapshots": {
                    "premium_interactions": {
                        "percent_remaining": 88.2,
                    }
                },
            }
            return mock_resp

        mock_resp.status_code = 404
        mock_resp.json.return_value = {}
        return mock_resp

    mock_get.side_effect = mock_get_side_effect

    quota = provider._fetch_org_copilot_quota(
        headers={"Authorization": "Bearer fake-token"},
        organization="myorg",
    )

    assert quota is not None
    assert not quota.get("is_error", False)
    assert quota["display_name"] == "myorg"


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
def test_github_copilot_provider_discover_orgs_empty(mock_get):
    """Test organization discovery with no orgs."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = []

    provider = GitHubCopilotProvider({})
    orgs = provider._discover_organizations("fake-token")

    assert len(orgs) == 0


@patch("limitwatch.providers.github_copilot.requests.get")
def test_github_copilot_provider_discover_orgs_failure(mock_get):
    """Test organization discovery failure."""
    mock_get.return_value.status_code = 401

    provider = GitHubCopilotProvider({})
    orgs = provider._discover_organizations("invalid-token")

    assert len(orgs) == 0


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.subprocess.run")
@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.subprocess.run")
@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.subprocess.run")
@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.subprocess.run")
def test_github_copilot_provider_get_usage_via_gh(mock_run):
    """Test fetching usage via gh CLI."""
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = '{"copilot_plan":"individual","quota_snapshots":{"premium_interactions":{"percent_remaining":95.0}}}'

    provider = GitHubCopilotProvider({})
    usage = provider._get_copilot_usage_via_gh()

    assert usage is not None
    assert usage["usage_percentage"] == 5.0


@patch("limitwatch.providers.github_copilot.subprocess.run")
def test_github_copilot_provider_get_usage_via_gh_failure(mock_run):
    """Test gh CLI usage fetch when gh is not available."""
    mock_run.side_effect = FileNotFoundError()

    provider = GitHubCopilotProvider({})
    usage = provider._get_copilot_usage_via_gh()

    assert usage is None


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_member_quota_user_lookup_fails(mock_get):
    """Test member quota when user lookup fails."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    mock_get.return_value.status_code = 401

    quota = provider._fetch_member_copilot_quota(headers, "myorg")

    assert quota is None


@patch("limitwatch.providers.github_copilot.requests.get")
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


@patch("limitwatch.providers.github_copilot.requests.get")
def test_github_copilot_provider_fetch_org_403_error(mock_get):
    """Test organization quota fetch 403 (permission denied)."""
    headers = {"Authorization": "Bearer fake-token"}
    provider = GitHubCopilotProvider({})

    mock_get.return_value.status_code = 403

    quota = provider._fetch_org_copilot_quota(headers, "myorg")

    assert quota is not None
    assert quota.get("is_error") is True
    assert "Insufficient permissions" in quota["message"]


@patch("limitwatch.providers.github_copilot.requests.get")
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


# --- Module-level helper function tests ---


class TestMakeGithubHeaders:
    def test_headers_structure(self):
        headers = _make_github_headers("my-token")
        assert headers["Authorization"] == "Bearer my-token"
        assert "X-GitHub-Api-Version" in headers
        assert "Accept" in headers


class TestNextMonthResetIso:
    def test_returns_iso_string(self):
        result = _next_month_reset_iso()
        assert "T" in result
        assert result.endswith("Z")


class TestSeatPercentages:
    def test_normal(self):
        remaining, used = _seat_percentages(100, 30)
        assert remaining == 70.0
        assert used == 30.0

    def test_zero_total(self):
        remaining, used = _seat_percentages(0, 0)
        assert remaining == 100.0
        assert used == 0.0

    def test_all_active(self):
        remaining, used = _seat_percentages(10, 10)
        assert remaining == 0.0
        assert used == 100.0


class TestBuildOrgError:
    def test_structure(self):
        err = _build_org_error("myorg", "Access denied")
        assert err["is_error"] is True
        assert "myorg" in err["display_name"]
        assert err["message"] == "Access denied"
        assert err["source_type"] == "GitHub Copilot"


class TestBuildPersonalQuota:
    def test_basic(self):
        q = _build_personal_quota(80.0, 20.0, "Monthly")
        assert q["display_name"] == "Personal"
        assert q["remaining_pct"] == 80.0
        assert q["used_pct"] == 20.0

    def test_with_extras(self):
        q = _build_personal_quota(50.0, 50.0, "Monthly", limit=100, remaining=50)
        assert q["limit"] == 100
        assert q["remaining"] == 50


# --- Interactive login tests ---


class TestInteractiveLogin:
    @patch("click.prompt")
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_interactive_login_with_gh_token(self, mock_get, mock_prompt):
        """Test interactive login when gh CLI token is found."""
        provider = GitHubCopilotProvider({})
        dm = MagicMock()

        # Mock _get_gh_token to return a token
        with patch.object(provider, "_get_gh_token", return_value="gh-token"):
            # No orgs discovered
            with patch.object(provider, "_discover_organizations", return_value=[]):
                mock_prompt.return_value = ""  # No manual org entry

                # Mock validate_token
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"login": "testuser"}

                result = provider.interactive_login(dm)
                assert result["email"] == "testuser"
                assert result["githubToken"] == "gh-token"

    @patch("click.prompt")
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_interactive_login_no_gh_token_manual(self, mock_get, mock_prompt):
        """Test interactive login when user enters token manually."""
        provider = GitHubCopilotProvider({})
        dm = MagicMock()

        with patch.object(provider, "_get_gh_token", return_value=None):
            with patch.object(provider, "_discover_organizations", return_value=[]):
                mock_prompt.side_effect = ["manual-token", ""]  # token, then no org
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"login": "testuser"}

                result = provider.interactive_login(dm)
                assert result["githubToken"] == "manual-token"

    @patch("click.prompt")
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_interactive_login_with_orgs(self, mock_get, mock_prompt):
        """Test interactive login with org selection."""
        provider = GitHubCopilotProvider({})
        dm = MagicMock()

        with patch.object(provider, "_get_gh_token", return_value="gh-token"):
            with patch.object(
                provider, "_discover_organizations", return_value=["org-a", "org-b"]
            ):
                mock_prompt.return_value = 1  # Select first org
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"login": "testuser"}

                result = provider.interactive_login(dm)
                assert result["organization"] == "org-a"

    @patch("click.prompt")
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_interactive_login_skip_org(self, mock_get, mock_prompt):
        """Test interactive login skipping org."""
        provider = GitHubCopilotProvider({})
        dm = MagicMock()

        with patch.object(provider, "_get_gh_token", return_value="gh-token"):
            with patch.object(
                provider, "_discover_organizations", return_value=["org-a"]
            ):
                mock_prompt.return_value = 0  # Skip org
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"login": "testuser"}

                result = provider.interactive_login(dm)
                assert "organization" not in result


class TestPromptForToken:
    @patch("click.prompt")
    def test_no_gh_token_empty_input_raises(self, mock_prompt):
        """No gh CLI token and user enters empty string."""
        provider = GitHubCopilotProvider({})
        dm = MagicMock()

        with patch.object(provider, "_get_gh_token", return_value=None):
            mock_prompt.return_value = ""
            with pytest.raises(Exception, match="GitHub token is required"):
                provider._prompt_for_token(dm)


class TestTryDiscoverOrgs:
    def test_success(self):
        provider = GitHubCopilotProvider({})
        dm = MagicMock()

        with patch.object(
            provider, "_discover_organizations", return_value=["org1", "org2"]
        ):
            orgs = provider._try_discover_orgs(dm, "token")
            assert orgs == ["org1", "org2"]

    def test_exception(self):
        provider = GitHubCopilotProvider({})
        dm = MagicMock()

        with patch.object(
            provider, "_discover_organizations", side_effect=Exception("fail")
        ):
            orgs = provider._try_discover_orgs(dm, "token")
            assert orgs == []


class TestSelectOrgFromList:
    @patch("click.prompt")
    def test_select_valid(self, mock_prompt):
        dm = MagicMock()
        mock_prompt.return_value = 2
        result = GitHubCopilotProvider._select_org_from_list(
            dm, ["org-a", "org-b", "org-c"]
        )
        assert result == "org-b"

    @patch("click.prompt")
    def test_select_skip(self, mock_prompt):
        dm = MagicMock()
        mock_prompt.return_value = 0
        result = GitHubCopilotProvider._select_org_from_list(dm, ["org-a"])
        assert result is None


# --- Additional edge case tests ---


class TestValidateToken:
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_validate_token_exception(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        with pytest.raises(Exception, match="GitHub authentication failed"):
            GitHubCopilotProvider._validate_token("some-token")


class TestFetchQuotasEdgeCases:
    def test_no_token(self):
        provider = GitHubCopilotProvider({})
        assert provider.fetch_quotas() == []

    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_no_personal_no_org_fallback(self, mock_get):
        """No personal quota found, no org → use default personal."""
        provider = GitHubCopilotProvider({"githubToken": "tok"})
        mock_get.return_value.status_code = 401
        with patch.object(provider, "_fetch_personal_copilot_quota", return_value=None):
            quotas = provider.fetch_quotas()
            assert len(quotas) == 1
            assert quotas[0]["display_name"] == "Personal"
            assert quotas[0]["remaining_pct"] == 100.0


class TestTryPersonalViaBilling:
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_success(self, mock_get):
        provider = GitHubCopilotProvider({})
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "seat_breakdown": {"total": 100, "active_this_cycle": 25}
        }
        headers = _make_github_headers("token")
        result = provider._try_personal_via_billing(headers)
        assert result is not None
        assert result["remaining_pct"] == 75.0
        assert result["used_pct"] == 25.0

    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_exception(self, mock_get):
        provider = GitHubCopilotProvider({})
        mock_get.side_effect = Exception("timeout")
        headers = _make_github_headers("token")
        result = provider._try_personal_via_billing(headers)
        assert result is None


class TestTryPersonalViaGhCli:
    @patch.object(GitHubCopilotProvider, "_get_copilot_usage_via_gh")
    def test_success(self, mock_usage):
        provider = GitHubCopilotProvider({})
        mock_usage.return_value = {"usage_percentage": 25.0}
        result = provider._try_personal_via_gh_cli()
        assert result is not None
        assert result["remaining_pct"] == 75.0
        assert result["used_pct"] == 25.0

    @patch.object(GitHubCopilotProvider, "_get_copilot_usage_via_gh")
    def test_no_data(self, mock_usage):
        provider = GitHubCopilotProvider({})
        mock_usage.return_value = None
        result = provider._try_personal_via_gh_cli()
        assert result is None

    @patch.object(GitHubCopilotProvider, "_get_copilot_usage_via_gh")
    def test_exception(self, mock_usage):
        provider = GitHubCopilotProvider({})
        mock_usage.side_effect = Exception("fail")
        result = provider._try_personal_via_gh_cli()
        assert result is None


class TestFetchOrgCopilotQuota:
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_other_error_code(self, mock_get):
        """Test non-200/403/404 HTTP response."""
        provider = GitHubCopilotProvider({"githubToken": "tok"})
        mock_get.return_value.status_code = 500
        headers = _make_github_headers("tok")
        result = provider._fetch_org_copilot_quota(headers, "myorg")
        assert result["is_error"] is True
        assert "HTTP 500" in result["message"]

    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_exception(self, mock_get):
        """Test exception during org fetch."""
        provider = GitHubCopilotProvider({"githubToken": "tok"})
        mock_get.side_effect = Exception("Connection reset")
        headers = _make_github_headers("tok")
        result = provider._fetch_org_copilot_quota(headers, "myorg")
        assert result["is_error"] is True
        assert "Connection reset" in result["message"]


class TestFetchCopilotInternalUser:
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_no_token(self, mock_get):
        provider = GitHubCopilotProvider({})
        headers = _make_github_headers("tok")
        result = provider._fetch_copilot_internal_user(headers)
        assert result is None


class TestFetchOrgFromInternalUser:
    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_org_not_in_list(self, mock_get):
        provider = GitHubCopilotProvider({"githubToken": "tok"})
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "organization_login_list": ["other-org"],
            "quota_snapshots": {},
        }
        headers = _make_github_headers("tok")
        result = provider._fetch_org_from_copilot_internal_user(headers, "myorg")
        assert result is None

    @patch("limitwatch.providers.github_copilot.requests.get")
    def test_no_percent_remaining(self, mock_get):
        """Org in list but no percent_remaining → defaults."""
        provider = GitHubCopilotProvider({"githubToken": "tok"})
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "organization_login_list": ["myorg"],
            "quota_snapshots": {},
        }
        headers = _make_github_headers("tok")
        result = provider._fetch_org_from_copilot_internal_user(headers, "myorg")
        assert result is not None
        assert result["remaining_pct"] == 100.0
        assert result["used_pct"] == 0.0


class TestTryGhInternalUsage:
    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_free_plan(self, mock_run):
        provider = GitHubCopilotProvider({})
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = '{"copilot_plan":"free"}'
        result = provider._try_gh_internal_usage()
        assert result == {"usage_percentage": 0.0}

    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_non_personal_plan(self, mock_run):
        provider = GitHubCopilotProvider({})
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = '{"copilot_plan":"business"}'
        result = provider._try_gh_internal_usage()
        assert result is None

    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_no_percent_remaining(self, mock_run):
        provider = GitHubCopilotProvider({})
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = '{"copilot_plan":"individual","quota_snapshots":{"premium_interactions":{}}}'
        result = provider._try_gh_internal_usage()
        assert result is None

    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_returncode_nonzero(self, mock_run):
        provider = GitHubCopilotProvider({})
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        result = provider._try_gh_internal_usage()
        assert result is None

    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_exception(self, mock_run):
        provider = GitHubCopilotProvider({})
        mock_run.side_effect = FileNotFoundError()
        result = provider._try_gh_internal_usage()
        assert result is None


class TestTryGhBillingUsage:
    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            '{"seat_breakdown":{"total":10,"active_this_cycle":3}}'
        )
        result = GitHubCopilotProvider._try_gh_billing_usage()
        assert result is not None
        assert result["usage_percentage"] == 30.0

    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_returncode_nonzero(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        result = GitHubCopilotProvider._try_gh_billing_usage()
        assert result is None

    @patch("limitwatch.providers.github_copilot.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = GitHubCopilotProvider._try_gh_billing_usage()
        assert result is None


class TestExtractPremiumQuota:
    def test_no_percent_remaining(self):
        provider = GitHubCopilotProvider({})
        result = provider._extract_premium_quota(
            {"quota_snapshots": {"premium_interactions": {}}}
        )
        assert result is None

    def test_with_overage(self):
        provider = GitHubCopilotProvider({})
        result = provider._extract_premium_quota(
            {
                "quota_reset_date": "2026-03-01T00:00:00Z",
                "quota_snapshots": {
                    "premium_interactions": {
                        "percent_remaining": 60.0,
                        "entitlement": 100,
                        "remaining": 60,
                        "overage_count": 5,
                        "overage_permitted": True,
                    }
                },
            }
        )
        assert result is not None
        assert result["remaining_pct"] == 60.0
        assert result["used_pct"] == 40.0
        assert result["limit"] == 100
        assert result["remaining"] == 60
        assert result["used"] == 40
        assert result["overage_used"] == 5
        assert result["overage_permitted"] is True
