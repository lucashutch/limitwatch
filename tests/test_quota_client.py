from unittest.mock import MagicMock, patch
from gemini_quota.quota_client import QuotaClient


@patch("requests.post")
def test_quota_client_fetch_cli(mock_post):
    creds = MagicMock()
    creds.token = "fake_token"
    client = QuotaClient(creds)

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

    results = client._fetch_gemini_cli_quotas(project_id="test-project")

    assert len(results) == 1
    assert results[0]["display_name"] == "Gemini 3 Pro (CLI)"
    assert results[0]["remaining_pct"] == 80.0


@patch("requests.post")
def test_quota_client_fetch_ag(mock_post):
    creds = MagicMock()
    creds.token = "fake_token"
    client = QuotaClient(creds)

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

    results = client._fetch_antigravity_quotas(project_id="test-project")

    assert len(results) == 1
    assert results[0]["display_name"] == "Claude (AG)"
    assert results[0]["remaining_pct"] == 50.0
