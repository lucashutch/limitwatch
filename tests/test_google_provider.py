import pytest
from unittest.mock import MagicMock, patch
from gemini_quota.providers.google import GoogleProvider


def test_google_provider_metadata():
    provider = GoogleProvider({"type": "google"})
    assert provider.provider_name == "Google"
    assert provider.source_priority == 1
    assert provider.primary_color == "cyan"


def test_google_provider_get_color():
    provider = GoogleProvider({"type": "google"})
    assert provider.get_color({"source_type": "Gemini CLI"}) == "cyan"
    assert provider.get_color({"source_type": "Antigravity"}) == "magenta"


def test_google_provider_filter_quotas():
    provider = GoogleProvider({"type": "google"})

    quotas = [
        {"display_name": "Gemini Pro (CLI)", "source_type": "Gemini CLI"},
        {"display_name": "Gemini 2.0 Flash (CLI)", "source_type": "Gemini CLI"},
        {"display_name": "Gemini 1.5 Flash (CLI)", "source_type": "Gemini CLI"},
        {"display_name": "Claude (AG)", "source_type": "Antigravity"},
        {"display_name": "Gemini 2.5 Flash (AG)", "source_type": "Antigravity"},
    ]

    # Default filtering (show_all=False)
    # Should keep premium (Pro, Flash, Claude) and fallback (1.5 Flash if no premium in CLI)
    # Wait, 1.5 Flash (CLI) should be kept if no premium in CLI.
    # But here Gemini Pro (CLI) IS premium.

    filtered = provider.filter_quotas(quotas, show_all=False)

    # Premium should be there
    assert any("Gemini Pro" in q["display_name"] for q in filtered)
    assert any("Claude" in q["display_name"] for q in filtered)

    # 2.0 should be removed
    assert not any("2.0" in q["display_name"] for q in filtered)

    # 1.5 Flash (CLI) should be removed because Gemini Pro (CLI) is present
    assert not any("Gemini 1.5 Flash (CLI)" == q["display_name"] for q in filtered)

    # 2.5 Flash (AG) should be removed because Claude (AG) is present
    assert not any("Gemini 2.5 Flash (AG)" == q["display_name"] for q in filtered)


def test_google_provider_get_sort_key():
    provider = GoogleProvider({"type": "google"})

    q1 = {"display_name": "Gemini Pro (CLI)", "source_type": "Gemini CLI"}
    q2 = {"display_name": "Gemini 2.0 Flash (CLI)", "source_type": "Gemini CLI"}
    q3 = {"display_name": "Claude (AG)", "source_type": "Antigravity"}

    key1 = provider.get_sort_key(q1)
    key2 = provider.get_sort_key(q2)
    key3 = provider.get_sort_key(q3)

    # CLI (0) before AG (1)
    assert key1[0] == 0
    assert key2[0] == 0
    assert key3[0] == 1

    # 2.0 (0) before Pro (4)
    assert key2[1] == 0
    assert key1[1] == 4


@patch("requests.post")
def test_fetch_gemini_cli_quotas(mock_post):
    creds = MagicMock()
    creds.token = "fake_token"
    provider = GoogleProvider({"type": "google"}, credentials=creds)

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "buckets": [
            {
                "modelId": "gemini-3-pro",
                "remainingFraction": 0.8,
                "resetTime": "2026-02-19T22:00:00Z",
            },
            {
                "modelId": "gemini-2.5-flash",
                "remainingFraction": 0.5,
                "resetTime": "2026-02-19T21:00:00Z",
            },
        ]
    }

    quotas = provider._fetch_gemini_cli_quotas("test-project")

    assert len(quotas) == 2
    assert any(q["display_name"] == "Gemini Pro (CLI)" for q in quotas)
    assert any(q["display_name"] == "Gemini 2.5 Flash (CLI)" for q in quotas)


@patch("requests.post")
def test_fetch_antigravity_quotas(mock_post):
    creds = MagicMock()
    creds.token = "fake_token"
    provider = GoogleProvider({"type": "google"}, credentials=creds)

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "models": {
            "gemini-3-pro": {
                "displayName": "Gemini 3 Pro",
                "quotaInfo": {
                    "remainingFraction": 0.9,
                    "resetTime": "2026-02-19T23:00:00Z",
                },
            },
            "claude-3-5-sonnet": {
                "displayName": "Claude 3.5 Sonnet",
                "quotaInfo": {
                    "remainingFraction": 0.4,
                    "resetTime": "2026-02-19T20:00:00Z",
                },
            },
        },
        "remaining_fraction": 0.5,
        "reset": "2026-02-19T20:00:00Z",
    }

    quotas = provider._fetch_antigravity_quotas("test-project")
    assert len(quotas) == 2
    assert any("Gemini Pro (AG)" == q["display_name"] for q in quotas)


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_google_provider_login_manual_project(mock_session_cls, mock_flow_cls):
    provider = GoogleProvider({"type": "google"})

    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_creds.refresh_token = "refresh_token"
    mock_flow.run_local_server.return_value = mock_creds

    mock_session = mock_session_cls.return_value
    mock_session.get.return_value.json.return_value = {"email": "test@example.com"}

    account_data = provider.login(manual_project_id="manual-id")

    assert account_data["email"] == "test@example.com"
    assert account_data["projectId"] == "manual-id"
    assert account_data["refreshToken"] == "refresh_token"


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_google_provider_login_discovery(mock_session_cls, mock_flow_cls):
    provider = GoogleProvider({"type": "google"})

    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_creds.refresh_token = "refresh_token"
    mock_flow.run_local_server.return_value = mock_creds

    mock_session = mock_session_cls.return_value
    mock_session.get.return_value.json.return_value = {"email": "test@example.com"}

    # Mock loadCodeAssist success
    mock_session.post.return_value.status_code = 200
    mock_session.post.return_value.json.return_value = {
        "cloudaicompanionProject": "discovered-id"
    }

    account_data = provider.login()

    assert account_data["projectId"] == "discovered-id"


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_google_provider_login_discovery_get_managed_project(
    mock_session_cls, mock_flow_cls
):
    provider = GoogleProvider({"type": "google"})

    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_creds.refresh_token = "refresh_token"
    mock_flow.run_local_server.return_value = mock_creds

    mock_session = mock_session_cls.return_value
    mock_session.get.return_value.json.return_value = {"email": "test@example.com"}

    # Mock loadCodeAssist failure, getManagedProject success
    def side_effect(url, **kwargs):
        m = MagicMock()
        if "loadCodeAssist" in url:
            m.status_code = 404
        elif "getManagedProject" in url:
            m.status_code = 200
            m.json.return_value = {"projectId": "managed-id"}
        return m

    mock_session.post.side_effect = side_effect

    account_data = provider.login()
    assert account_data["projectId"] == "managed-id"


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_google_provider_login_discovery_cloud_resource_manager(
    mock_session_cls, mock_flow_cls
):
    provider = GoogleProvider({"type": "google"})

    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_creds.refresh_token = "refresh_token"
    mock_flow.run_local_server.return_value = mock_creds

    mock_session = mock_session_cls.return_value
    mock_session.get.side_effect = [
        MagicMock(json=lambda: {"email": "test@example.com"}),  # userinfo
        MagicMock(
            status_code=200,
            json=lambda: {
                "projects": [
                    {"projectId": "gen-lang-client-123", "lifecycleState": "ACTIVE"}
                ]
            },
        ),  # crm
    ]

    # All posts fail
    mock_session.post.return_value.status_code = 404

    account_data = provider.login()
    assert account_data["projectId"] == "gen-lang-client-123"


def test_google_provider_fetch_quotas_empty_services():
    provider = GoogleProvider({"type": "google", "services": []})
    assert provider.fetch_quotas() == []


@patch("requests.post")
def test_fetch_gemini_cli_quotas_error(mock_post):
    creds = MagicMock()
    creds.token = "fake_token"
    provider = GoogleProvider({"type": "google"}, credentials=creds)

    mock_post.return_value.status_code = 500
    assert provider._fetch_gemini_cli_quotas() == []


def test_google_provider_filter_quotas_edge_cases():
    provider = GoogleProvider({"type": "google"})
    assert provider.filter_quotas([], False) == []

    # All premium
    quotas = [{"display_name": "Gemini 3 Pro", "source_type": "Gemini CLI"}]
    assert len(provider.filter_quotas(quotas, False)) == 1


def test_google_provider_filter_quotas_show_all():
    provider = GoogleProvider({"type": "google"})
    quotas = [{"display_name": "Gemini 2.0 Flash"}]
    # 2.0 is normally hidden
    assert len(provider.filter_quotas(quotas, show_all=False)) == 0
    # But shown with show_all
    assert len(provider.filter_quotas(quotas, show_all=True)) == 1


def test_google_provider_filter_quotas_no_premium():
    provider = GoogleProvider({"type": "google"})
    quotas = [
        {"display_name": "Gemini 1.5 Flash", "source_type": "Gemini CLI"},
        {"display_name": "Gemini 1.5 Pro", "source_type": "Antigravity"},
    ]
    # No premium models (3, Claude) in either source, so both 1.5 should be kept
    filtered = provider.filter_quotas(quotas, show_all=False)
    assert len(filtered) == 2


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_google_provider_login_no_email(mock_session_cls, mock_flow_cls):
    provider = GoogleProvider({"type": "google"})
    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_flow.run_local_server.return_value = mock_creds

    mock_session = mock_session_cls.return_value
    mock_session.get.return_value.json.return_value = {}  # No email

    with pytest.raises(Exception, match="Failed to retrieve email"):
        provider.login()


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_google_provider_login_crm_variations(mock_session_cls, mock_flow_cls):
    provider = GoogleProvider({"type": "google"})
    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_creds.refresh_token = "rt"
    mock_flow.run_local_server.return_value = mock_creds

    mock_session = mock_session_cls.return_value

    # Test Priority 2: 'gemini' in name
    mock_session.get.side_effect = [
        MagicMock(json=lambda: {"email": "test@example.com"}),  # userinfo
        MagicMock(
            status_code=200,
            json=lambda: {
                "projects": [
                    {
                        "projectId": "my-gemini-project",
                        "lifecycleState": "ACTIVE",
                        "createTime": "2024-01-01T00:00:00Z",
                    }
                ]
            },
        ),  # crm
    ]
    mock_session.post.return_value.status_code = 404

    account_data = provider.login()
    assert account_data["projectId"] == "my-gemini-project"

    # Test Priority 3: Fallback newest active
    mock_session.get.side_effect = [
        MagicMock(json=lambda: {"email": "test@example.com"}),  # userinfo
        MagicMock(
            status_code=200,
            json=lambda: {
                "projects": [
                    {
                        "projectId": "active-1",
                        "lifecycleState": "ACTIVE",
                        "createTime": "2023-01-01T00:00:00Z",
                    },
                    {
                        "projectId": "active-2",
                        "lifecycleState": "ACTIVE",
                        "createTime": "2024-01-01T00:00:00Z",
                    },
                ]
            },
        ),  # crm
    ]
    account_data = provider.login()
    assert account_data["projectId"] == "active-2"


@patch("gemini_quota.providers.google.InstalledAppFlow")
@patch("gemini_quota.providers.google.google.auth.transport.requests.AuthorizedSession")
def test_google_provider_login_final_fallback(mock_session_cls, mock_flow_cls):
    provider = GoogleProvider({"type": "google"})
    mock_flow = mock_flow_cls.from_client_config.return_value
    mock_creds = MagicMock()
    mock_creds.refresh_token = "rt"
    mock_flow.run_local_server.return_value = mock_creds

    mock_session = mock_session_cls.return_value
    mock_session.get.side_effect = [
        MagicMock(json=lambda: {"email": "test@example.com"}),  # userinfo
        MagicMock(status_code=404),  # crm fails
    ]
    mock_session.post.return_value.status_code = 404

    account_data = provider.login()
    assert account_data["projectId"] == "rising-fact-p41fc"


def test_google_provider_fetch_quotas_cached_more():
    account_data = {
        "type": "google",
        "cachedQuota": {
            "gemini-pro": {"remainingFraction": 0.5},
            "gemini-flash": {"remainingFraction": 0.5},
            "claude": {"remainingFraction": 0.4},
            "gemini-2.5-flash": {"remainingFraction": 0.3},
            "gemini-2.5-pro": {"remainingFraction": 0.2},
            "other-model": {"remainingFraction": 0.1},
        },
    }
    provider = GoogleProvider(account_data)
    with patch.object(provider, "_fetch_gemini_cli_quotas", return_value=[]):
        with patch.object(provider, "_fetch_antigravity_quotas", return_value=[]):
            quotas = provider.fetch_quotas()

    assert any(q["display_name"] == "Gemini Flash (AG)" for q in quotas)
    assert any(q["display_name"] == "Claude (AG)" for q in quotas)
    assert any(q["display_name"] == "Gemini 2.5 Flash (AG)" for q in quotas)
    assert any(q["display_name"] == "Gemini 2.5 Pro (AG)" for q in quotas)
    assert any(q["display_name"] == "Other Model (AG)" for q in quotas)


@patch("requests.post")
def test_fetch_gemini_cli_quotas_all_families(mock_post):
    creds = MagicMock()
    provider = GoogleProvider({"type": "google"}, credentials=creds)
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "buckets": [
            {"modelId": "gemini-3-flash", "remainingFraction": 1.0},
            {"modelId": "gemini-2.5-pro", "remainingFraction": 1.0},
            {"modelId": "gemini-2.0-flash", "remainingFraction": 1.0},
            {"modelId": "gemini-1.5-pro", "remainingFraction": 1.0},
            {"modelId": "gemini-1.5-flash", "remainingFraction": 1.0},
            {"modelId": "unknown", "remainingFraction": 1.0},
        ],
        "remaining_fraction": 1.0,
        "reset": "now",
    }
    quotas = provider._fetch_gemini_cli_quotas()
    assert any("Gemini Flash" in q["display_name"] for q in quotas)
    assert any("Gemini 2.5 Pro" in q["display_name"] for q in quotas)
    assert any("Gemini 2.0 Flash" in q["display_name"] for q in quotas)
    assert any("Gemini 1.5 Pro" in q["display_name"] for q in quotas)
    assert any("Gemini 1.5 Flash" in q["display_name"] for q in quotas)


@patch("requests.post")
def test_fetch_antigravity_quotas_all_families(mock_post):
    creds = MagicMock()
    provider = GoogleProvider({"type": "google"}, credentials=creds)
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "models": {
            "gemini-3-flash": {
                "displayName": "Gemini 3 Flash",
                "quotaInfo": {"remainingFraction": 1.0},
            },
            "gemini-2.5-flash": {
                "displayName": "Gemini 2.5 Flash",
                "quotaInfo": {"remainingFraction": 1.0},
            },
            "gemini-2.5-pro": {
                "displayName": "Gemini 2.5 Pro",
                "quotaInfo": {"remainingFraction": 1.0},
            },
            "other": {"displayName": "Other", "quotaInfo": {"remainingFraction": 1.0}},
        },
        "remaining_fraction": 1.0,
        "reset": "now",
    }
    quotas = provider._fetch_antigravity_quotas()
    assert any("Gemini Flash" in q["display_name"] for q in quotas)
    assert any("Gemini 2.5 Flash" in q["display_name"] for q in quotas)
    assert any("Gemini 2.5 Pro" in q["display_name"] for q in quotas)


def test_google_provider_interactive_login_more():
    provider = GoogleProvider({"type": "google"})
    display = MagicMock()
    with patch.object(provider, "login") as mock_login:
        with patch("click.prompt", return_value=1):
            provider.interactive_login(display)
            mock_login.assert_called_with(services=["AG", "CLI"])
        with patch("click.prompt", return_value=2):
            provider.interactive_login(display)
            mock_login.assert_called_with(services=["AG"])
        with patch("click.prompt", return_value=3):
            provider.interactive_login(display)
            mock_login.assert_called_with(services=["CLI"])


@patch("requests.post")
def test_google_provider_fetch_quotas_one_fails(mock_post):
    creds = MagicMock()
    provider = GoogleProvider(
        {"type": "google", "services": ["AG", "CLI"]}, credentials=creds
    )

    # Mock CLI fails, AG succeeds
    def side_effect(url, **kwargs):
        m = MagicMock()
        if "retrieveUserQuota" in url:
            raise Exception("CLI fail")
        m.status_code = 200
        m.json.return_value = {"models": {}, "remaining_fraction": 1.0, "reset": "now"}
        return m

    mock_post.side_effect = side_effect
    quotas = provider.fetch_quotas()
    # Should still complete without crashing
    assert isinstance(quotas, list)
