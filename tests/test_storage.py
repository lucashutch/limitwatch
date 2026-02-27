"""Tests for the storage module."""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from limitwatch.storage import Storage, DEFAULT_DB_PATH


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_history.db"
    storage = Storage(db_path)
    return storage


class TestStorage:
    """Tests for the Storage class."""

    def test_init_creates_database(self, tmp_path):
        """Test that initialization creates the database file."""
        db_path = tmp_path / "new_history.db"
        assert not db_path.exists()

        storage = Storage(db_path)

        assert db_path.exists()
        assert storage.db_path == db_path

    def test_record_quotas_basic(self, temp_db):
        """Test basic quota recording."""
        quotas = [
            {
                "name": "test_quota_1",
                "display_name": "Test Quota 1",
                "remaining_pct": 75.5,
                "used": 25,
                "limit": 100,
                "reset": "2024-01-01T00:00:00Z",
            }
        ]

        count = temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=quotas,
        )

        assert count == 1

        # Verify it was stored
        history = temp_db.query_history()
        assert len(history) == 1
        assert history[0]["account_email"] == "test@example.com"
        assert history[0]["provider_type"] == "google"
        assert history[0]["quota_name"] == "test_quota_1"
        assert history[0]["remaining_pct"] == 75.5

    def test_record_quotas_hourly_deduplication(self, temp_db):
        """Test that quotas are deduplicated within the same hour."""
        quotas = [
            {
                "name": "test_quota",
                "display_name": "Test Quota",
                "remaining_pct": 80.0,
                "used": 20,
                "limit": 100,
            }
        ]

        timestamp = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)

        # Record twice in same hour
        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=quotas,
            timestamp=timestamp,
        )

        quotas[0]["remaining_pct"] = 70.0
        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=quotas,
            timestamp=timestamp.replace(minute=45),  # Same hour, different minute
        )

        # Should only have one record (the second one overwrote the first)
        history = temp_db.query_history()
        assert len(history) == 1
        assert history[0]["remaining_pct"] == 70.0

    def test_record_quotas_different_hours(self, temp_db):
        """Test that quotas in different hours are not deduplicated."""
        quotas = [
            {
                "name": "test_quota",
                "display_name": "Test Quota",
                "remaining_pct": 80.0,
                "used": 20,
                "limit": 100,
            }
        ]

        # Record in two different hours
        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=quotas,
            timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        )

        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=quotas,
            timestamp=datetime(2024, 1, 15, 11, 30, tzinfo=timezone.utc),
        )

        history = temp_db.query_history()
        assert len(history) == 2

    def test_record_quotas_skips_errors(self, temp_db):
        """Test that quotas with is_error=True are skipped."""
        quotas = [
            {
                "name": "error_quota",
                "display_name": "Error Quota",
                "remaining_pct": 0,
                "is_error": True,
                "message": "API Error",
            },
            {
                "name": "good_quota",
                "display_name": "Good Quota",
                "remaining_pct": 90.0,
            },
        ]

        count = temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=quotas,
        )

        assert count == 1  # Only the good quota
        history = temp_db.query_history()
        assert len(history) == 1
        assert history[0]["quota_name"] == "good_quota"

    def test_query_history_with_filters(self, temp_db):
        """Test querying with various filters."""
        # Add test data
        for i in range(3):
            temp_db.record_quotas(
                account_email=f"user{i}@example.com",
                provider_type="google" if i < 2 else "chutes",
                quotas=[
                    {
                        "name": f"quota_{i}",
                        "display_name": f"Quota {i}",
                        "remaining_pct": float(90 - i * 10),
                    }
                ],
                timestamp=datetime(2024, 1, 15, 10 + i, 0, tzinfo=timezone.utc),
            )

        # Test account filter
        history = temp_db.query_history(account_email="user1@example.com")
        assert len(history) == 1
        assert history[0]["account_email"] == "user1@example.com"

        # Test provider filter
        history = temp_db.query_history(provider_type="google")
        assert len(history) == 2

        # Test quota name filter
        history = temp_db.query_history(quota_name="quota_2")
        assert len(history) == 1

    def test_query_history_with_time_range(self, temp_db):
        """Test querying with time range filters."""
        base_time = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)

        for i in range(5):
            temp_db.record_quotas(
                account_email="test@example.com",
                provider_type="google",
                quotas=[{"name": "test_quota", "remaining_pct": float(100 - i * 10)}],
                timestamp=base_time + timedelta(hours=i),
            )

        # Test since filter
        history = temp_db.query_history(since=base_time + timedelta(hours=2))
        assert len(history) == 3  # hours 2, 3, 4

        # Test until filter
        history = temp_db.query_history(until=base_time + timedelta(hours=2))
        assert len(history) == 3  # hours 0, 1, 2

        # Test both filters
        history = temp_db.query_history(
            since=base_time + timedelta(hours=1),
            until=base_time + timedelta(hours=3),
        )
        assert len(history) == 3  # hours 1, 2, 3

    def test_get_aggregation(self, temp_db):
        """Test the aggregation function."""
        # Add test data with varying values
        base_time = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)

        for i in range(5):
            temp_db.record_quotas(
                account_email="test@example.com",
                provider_type="google",
                quotas=[
                    {
                        "name": "test_quota",
                        "display_name": "Test Quota",
                        "remaining_pct": float(50 + i * 10),
                        "used": float(i * 10),
                        "limit": 100.0,
                    }
                ],
                timestamp=base_time + timedelta(hours=i),
            )

        agg = temp_db.get_aggregation()

        assert len(agg) == 1
        assert agg[0]["account_email"] == "test@example.com"
        assert agg[0]["min_remaining"] == 50.0
        assert agg[0]["max_remaining"] == 90.0
        assert agg[0]["avg_remaining"] == 70.0
        assert agg[0]["data_points"] == 5

    def test_get_distinct_values(self, temp_db):
        """Test getting distinct accounts, providers, and quotas."""
        from datetime import datetime, timezone, timedelta

        # Add mixed data with different timestamps to avoid deduplication
        base_time = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)

        for hour_offset, provider in enumerate(["google", "chutes", "google"]):
            for i in range(2):
                temp_db.record_quotas(
                    account_email=f"user{i}@example.com",
                    provider_type=provider,
                    quotas=[{"name": f"quota_{i}", "remaining_pct": 100.0}],
                    timestamp=base_time + timedelta(hours=hour_offset, minutes=i),
                )

        accounts = temp_db.get_distinct_accounts()
        assert sorted(accounts) == ["user0@example.com", "user1@example.com"]

        providers = temp_db.get_distinct_providers()
        assert sorted(providers) == ["chutes", "google"]

    def test_get_time_range(self, temp_db):
        """Test getting the time range of data."""
        # Empty database
        min_ts, max_ts = temp_db.get_time_range()
        assert min_ts is None
        assert max_ts is None

        # Add data
        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=[{"name": "test", "remaining_pct": 100.0}],
            timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        )

        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=[{"name": "test", "remaining_pct": 90.0}],
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        )

        min_ts, max_ts = temp_db.get_time_range()
        assert min_ts.hour == 10
        assert max_ts.hour == 12

    def test_purge_old_data(self, temp_db):
        """Test purging old data."""
        # Add old and new data
        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=[{"name": "test", "remaining_pct": 100.0}],
            timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        )

        temp_db.record_quotas(
            account_email="test@example.com",
            provider_type="google",
            quotas=[{"name": "test", "remaining_pct": 90.0}],
            timestamp=datetime(2024, 1, 15, 0, 0, tzinfo=timezone.utc),
        )

        assert len(temp_db.query_history()) == 2

        # Purge data older than Jan 10
        deleted = temp_db.purge_old_data(
            datetime(2024, 1, 10, 0, 0, tzinfo=timezone.utc)
        )

        assert deleted == 1
        assert len(temp_db.query_history()) == 1
        assert temp_db.query_history()[0]["remaining_pct"] == 90.0


class TestDefaultDBPath:
    """Tests for the default database path."""

    def test_default_db_path(self):
        """Test that default DB path is in config directory."""
        expected = Path.home() / ".config" / "limitwatch" / "history.db"
        assert DEFAULT_DB_PATH == expected
