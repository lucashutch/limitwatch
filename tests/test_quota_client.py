from unittest.mock import MagicMock, patch
from gemini_quota.quota_client import QuotaClient


@patch("gemini_quota.providers.google.requests.post")
def test_quota_client_google_fetch_cli(mock_post):
    creds = MagicMock()
    creds.token = "fake_token"
    client = QuotaClient({"type": "google", "services": ["CLI"]}, credentials=creds)

    # Mock CLI response
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "buckets": [
            {
                "modelId": "gemini-3-pro-001",
                "remainingFraction": 0.8,
                "resetTime": "2026-02-15T00:00:00Z",
            }
        ]
    }

    results = client.fetch_quotas()

    assert len(results) == 1
    assert results[0]["display_name"] == "Gemini 3 Pro (CLI)"
    assert results[0]["remaining_pct"] == 80.0


@patch("gemini_quota.providers.google.requests.post")
def test_quota_client_google_fetch_ag(mock_post):
    creds = MagicMock()
    creds.token = "fake_token"
    client = QuotaClient({"type": "google", "services": ["AG"]}, credentials=creds)

    # Mock AG response
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "models": {
            "claude-3-opus": {
                "displayName": "Claude 3 Opus",
                "quotaInfo": {
                    "remainingFraction": 0.5,
                    "resetTime": "2026-02-15T00:00:00Z",
                },
            }
        }
    }

    results = client.fetch_quotas()

    assert len(results) == 1
    assert results[0]["display_name"] == "Claude (AG)"
    assert results[0]["remaining_pct"] == 50.0


def test_quota_client_init_legacy():
    client = QuotaClient(api_key="fake-key")
    assert client.account_data["apiKey"] == "fake-key"
    assert client.account_data["type"] == "chutes"
    assert client.provider.provider_name == "Chutes"


def test_get_available_providers():
    providers = QuotaClient.get_available_providers()
    assert "google" in providers
    assert "chutes" in providers


def test_quota_client_delegation():
    client = QuotaClient({"type": "google"})
    client.provider = MagicMock()

    client.filter_quotas([], True)
    client.provider.filter_quotas.assert_called_with([], True)

    client.get_sort_key({})
    client.provider.get_sort_key.assert_called_with({})

    client.get_color({})
    client.provider.get_color.assert_called_with({})
