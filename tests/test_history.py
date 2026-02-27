"""Tests for the history module."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from limitwatch.history import HistoryManager, TIME_PRESETS


@pytest.fixture
def mock_storage():
    """Create a mock storage object."""
    storage = MagicMock()
    storage.db_path = "/test/history.db"
    return storage


@pytest.fixture
def history_mgr(mock_storage):
    """Create a HistoryManager with mocked storage."""
    with patch("limitwatch.history.Storage", return_value=mock_storage):
        mgr = HistoryManager()
        mgr.storage = mock_storage
        return mgr


class TestHistoryManager:
    """Tests for the HistoryManager class."""

    def test_parse_time_preset(self, history_mgr):
        """Test parsing time presets."""
        now = datetime.now(timezone.utc)

        result = history_mgr.parse_time_preset("24h")
        assert result is not None
        assert (now - result).total_seconds() == pytest.approx(86400, rel=1)

        result = history_mgr.parse_time_preset("7d")
        assert result is not None
        assert (now - result).total_seconds() == pytest.approx(604800, rel=1)

        result = history_mgr.parse_time_preset("invalid")
        assert result is None

    def test_parse_datetime_iso(self, history_mgr):
        """Test parsing ISO format datetime."""
        result = history_mgr.parse_datetime("2024-01-15T10:30:00+00:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        result = history_mgr.parse_datetime("2024-01-15T10:30:00Z")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_parse_datetime_relative_days(self, history_mgr):
        """Test parsing relative day strings."""
        now = datetime.now(timezone.utc)

        result = history_mgr.parse_datetime("7d")
        expected = now - timedelta(days=7)
        assert (result - expected).total_seconds() == pytest.approx(0, abs=1)

        result = history_mgr.parse_datetime("30d")
        expected = now - timedelta(days=30)
        assert (result - expected).total_seconds() == pytest.approx(0, abs=1)

    def test_parse_datetime_relative_hours(self, history_mgr):
        """Test parsing relative hour strings."""
        now = datetime.now(timezone.utc)

        result = history_mgr.parse_datetime("24h")
        expected = now - timedelta(hours=24)
        assert (result - expected).total_seconds() == pytest.approx(0, abs=1)

    def test_parse_datetime_empty(self, history_mgr):
        """Test parsing empty or None strings."""
        assert history_mgr.parse_datetime("") is None
        assert history_mgr.parse_datetime(None) is None

    def test_parse_datetime_invalid(self, history_mgr):
        """Test parsing invalid datetime strings."""
        result = history_mgr.parse_datetime("not-a-date")
        assert result is None

    def test_record_quotas(self, history_mgr, mock_storage):
        """Test recording quotas delegates to storage."""
        quotas = [{"name": "test", "remaining_pct": 100.0}]

        history_mgr.record_quotas("test@example.com", "google", quotas)

        mock_storage.record_quotas.assert_called_once()
        call_args = mock_storage.record_quotas.call_args
        assert call_args[0][0] == "test@example.com"
        assert call_args[0][1] == "google"
        assert call_args[0][2] == quotas

    def test_get_history_with_preset(self, history_mgr, mock_storage):
        """Test getting history with a preset."""
        mock_storage.query_history.return_value = [{"test": "data"}]

        result = history_mgr.get_history(preset="24h")

        mock_storage.query_history.assert_called_once()
        call_kwargs = mock_storage.query_history.call_args[1]
        assert call_kwargs["since"] is not None
        assert call_kwargs["until"] is None
        assert result == [{"test": "data"}]

    def test_get_history_with_custom_range(self, history_mgr, mock_storage):
        """Test getting history with custom date range."""
        mock_storage.query_history.return_value = []

        history_mgr.get_history(since="2024-01-01", until="2024-01-15")

        call_kwargs = mock_storage.query_history.call_args[1]
        assert call_kwargs["since"] is not None
        assert call_kwargs["until"] is not None

    def test_get_history_with_filters(self, history_mgr, mock_storage):
        """Test getting history with account/provider/quota filters."""
        mock_storage.query_history.return_value = []

        history_mgr.get_history(
            preset="7d",
            account_email="test@example.com",
            provider_type="google",
            quota_name="my_quota",
        )

        call_kwargs = mock_storage.query_history.call_args[1]
        assert call_kwargs["account_email"] == "test@example.com"
        assert call_kwargs["provider_type"] == "google"
        assert call_kwargs["quota_name"] == "my_quota"

    def test_get_aggregation(self, history_mgr, mock_storage):
        """Test getting aggregated statistics."""
        mock_storage.get_aggregation.return_value = [
            {"account_email": "test@example.com", "avg_remaining": 75.0}
        ]

        result = history_mgr.get_aggregation(preset="30d")

        mock_storage.get_aggregation.assert_called_once()
        call_kwargs = mock_storage.get_aggregation.call_args[1]
        assert call_kwargs["since"] is not None
        assert result[0]["avg_remaining"] == 75.0

    def test_get_time_series(self, history_mgr, mock_storage):
        """Test getting time series data for a specific quota."""
        mock_storage.query_history.return_value = [
            {"timestamp": "2024-01-15T10:00:00+00:00", "remaining_pct": 100.0},
            {"timestamp": "2024-01-15T11:00:00+00:00", "remaining_pct": 90.0},
            {"timestamp": "2024-01-15T12:00:00+00:00", "remaining_pct": 80.0},
        ]

        result = history_mgr.get_time_series("my_quota")

        assert len(result) == 3
        assert result[0][1] == 100.0  # First value
        assert result[-1][1] == 80.0  # Last value
        assert isinstance(result[0][0], datetime)

    def test_get_time_series_sorts_by_timestamp(self, history_mgr, mock_storage):
        """Test that time series data is sorted by timestamp."""
        # Return unsorted data
        mock_storage.query_history.return_value = [
            {"timestamp": "2024-01-15T12:00:00+00:00", "remaining_pct": 80.0},
            {"timestamp": "2024-01-15T10:00:00+00:00", "remaining_pct": 100.0},
            {"timestamp": "2024-01-15T11:00:00+00:00", "remaining_pct": 90.0},
        ]

        result = history_mgr.get_time_series("my_quota")

        # Should be sorted
        values = [r[1] for r in result]
        assert values == [100.0, 90.0, 80.0]

    def test_get_available_filters(self, history_mgr, mock_storage):
        """Test getting available filter values."""
        mock_storage.get_distinct_accounts.return_value = [
            "a@example.com",
            "b@example.com",
        ]
        mock_storage.get_distinct_providers.return_value = ["google", "chutes"]

        result = history_mgr.get_available_filters()

        assert result["accounts"] == ["a@example.com", "b@example.com"]
        assert result["providers"] == ["google", "chutes"]

    def test_get_database_info(self, history_mgr, mock_storage):
        """Test getting database information."""
        mock_storage.get_time_range.return_value = (
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        mock_storage.get_distinct_accounts.return_value = ["test@example.com"]
        mock_storage.get_distinct_providers.return_value = ["google"]

        result = history_mgr.get_database_info()

        assert result["path"] == "/test/history.db"
        assert result["oldest_record"] is not None
        assert result["newest_record"] is not None
        assert len(result["accounts"]) == 1
        assert len(result["providers"]) == 1

    def test_purge_data(self, history_mgr, mock_storage):
        """Test purging data."""
        mock_storage.purge_old_data.return_value = 10

        result = history_mgr.purge_data("2024-01-01")

        mock_storage.purge_old_data.assert_called_once()
        assert result == 10

    def test_purge_data_invalid_date(self, history_mgr):
        """Test purging with invalid date raises error."""
        with pytest.raises(ValueError, match="Invalid date format"):
            history_mgr.purge_data("not-a-date")


class TestTimePresets:
    """Tests for TIME_PRESETS constant."""

    def test_presets_exist(self):
        """Test that expected presets exist."""
        assert "24h" in TIME_PRESETS
        assert "7d" in TIME_PRESETS
        assert "30d" in TIME_PRESETS
        assert "90d" in TIME_PRESETS

    def test_preset_values(self):
        """Test that preset values are correct timedeltas."""
        assert TIME_PRESETS["24h"] == timedelta(hours=24)
        assert TIME_PRESETS["7d"] == timedelta(days=7)
        assert TIME_PRESETS["30d"] == timedelta(days=30)
        assert TIME_PRESETS["90d"] == timedelta(days=90)
