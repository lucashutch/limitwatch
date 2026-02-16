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


@patch("gemini_quota.providers.chutes.requests.get")
def test_quota_client_chutes_fetch(mock_get):
    client = QuotaClient({"type": "chutes", "apiKey": "fake_key"})

    def mock_responses(url, **kwargs):
        m = MagicMock()
        m.status_code = 200
        if "users/me/quota_usage/me" in url:
            m.json.return_value = {"quota": 300, "used": 15, "chute_id": "*"}
        elif "users/me" in url:
            m.json.return_value = {"balance": 10.5, "email": "test@chutes.ai"}
        return m

    mock_get.side_effect = mock_responses

    results = client.fetch_quotas()

    # Balance + Quota
    assert len(results) == 2
    assert any("Balance: $10.50" in r["display_name"] for r in results)
    assert any("Quota (285/300)" in r["display_name"] for r in results)
