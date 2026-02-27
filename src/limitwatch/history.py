"""History management and querying for historical quota data."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .storage import Storage

logger = logging.getLogger(__name__)

TIME_PRESETS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


class HistoryManager:
    """Manages historical quota data queries and aggregations."""

    def __init__(self, db_path: Optional[Path] = None):
        self.storage = Storage(db_path)

    def record_quotas(
        self,
        account_email: str,
        provider_type: str,
        quotas: List[Dict[str, Any]],
        timestamp: Optional[datetime] = None,
    ) -> int:
        """Record quota snapshots."""
        return self.storage.record_quotas(
            account_email, provider_type, quotas, timestamp
        )

    def parse_time_preset(self, preset: str) -> Optional[datetime]:
        """Convert a preset string to a start datetime."""
        if preset in TIME_PRESETS:
            return datetime.now(timezone.utc) - TIME_PRESETS[preset]
        return None

    def parse_datetime(self, value: str) -> Optional[datetime]:
        """Parse a datetime string (ISO format or relative)."""
        if not value:
            return None

        # Try ISO format first
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass

        # Try relative days (e.g., "7d", "30d")
        if value.endswith("d") and value[:-1].isdigit():
            days = int(value[:-1])
            return datetime.now(timezone.utc) - timedelta(days=days)

        # Try relative hours (e.g., "24h", "48h")
        if value.endswith("h") and value[:-1].isdigit():
            hours = int(value[:-1])
            return datetime.now(timezone.utc) - timedelta(hours=hours)

        logger.warning(f"Could not parse datetime: {value}")
        return None

    def get_history(
        self,
        preset: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        account_email: Optional[str] = None,
        provider_type: Optional[str] = None,
        quota_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get historical quota data with flexible time filtering.

        Args:
            preset: One of "24h", "7d", "30d", "90d"
            since: Start time (ISO format or relative like "7d", "24h")
            until: End time (ISO format)
            account_email: Filter by account
            provider_type: Filter by provider
            quota_name: Filter by quota name

        Returns:
            List of quota snapshot records
        """
        # Determine time range
        start_time = None
        end_time = None

        if preset:
            start_time = self.parse_time_preset(preset)
        elif since:
            start_time = self.parse_datetime(since)

        if until:
            end_time = self.parse_datetime(until)

        return self.storage.query_history(
            since=start_time,
            until=end_time,
            account_email=account_email,
            provider_type=provider_type,
            quota_name=quota_name,
        )

    def get_aggregation(
        self,
        preset: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        account_email: Optional[str] = None,
        provider_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get aggregated statistics per quota.

        Returns:
            List of dicts with quota stats
        """
        start_time = None
        end_time = None

        if preset:
            start_time = self.parse_time_preset(preset)
        elif since:
            start_time = self.parse_datetime(since)

        if until:
            end_time = self.parse_datetime(until)

        return self.storage.get_aggregation(
            since=start_time,
            until=end_time,
            account_email=account_email,
            provider_type=provider_type,
        )

    def get_time_series(
        self,
        quota_name: str,
        account_email: Optional[str] = None,
        preset: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[Tuple[datetime, float]]:
        """Get time series data for a specific quota.

        Returns:
            List of (timestamp, remaining_pct) tuples
        """
        history = self.get_history(
            preset=preset,
            since=since,
            account_email=account_email,
            quota_name=quota_name,
        )

        # Sort by timestamp ascending for time series
        history.sort(key=lambda x: x["timestamp"])

        result = []
        for record in history:
            ts = datetime.fromisoformat(record["timestamp"])
            remaining = record.get("remaining_pct")
            if remaining is not None:
                result.append((ts, remaining))

        return result

    def get_available_filters(self) -> Dict[str, List[str]]:
        """Get available filter values from the database."""
        return {
            "accounts": self.storage.get_distinct_accounts(),
            "providers": self.storage.get_distinct_providers(),
        }

    def get_database_info(self) -> Dict[str, Any]:
        """Get information about the database."""
        min_ts, max_ts = self.storage.get_time_range()

        return {
            "path": str(self.storage.db_path),
            "oldest_record": min_ts.isoformat() if min_ts else None,
            "newest_record": max_ts.isoformat() if max_ts else None,
            "accounts": self.storage.get_distinct_accounts(),
            "providers": self.storage.get_distinct_providers(),
        }

    def purge_data(self, before: str) -> int:
        """Purge data older than the specified date.

        Args:
            before: ISO format datetime string

        Returns:
            Number of records deleted
        """
        dt = self.parse_datetime(before)
        if not dt:
            raise ValueError(f"Invalid date format: {before}")
        return self.storage.purge_old_data(dt)
