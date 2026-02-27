"""SQLite storage module for historical quota tracking."""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".config" / "limitwatch" / "history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS quota_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_email TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    quota_name TEXT NOT NULL,
    display_name TEXT,
    remaining_pct REAL,
    used REAL,
    limit_val REAL,
    reset_time TEXT,
    timestamp TEXT NOT NULL,
    hour_bucket TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_email, quota_name, hour_bucket)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_account ON quota_snapshots(account_email);
CREATE INDEX IF NOT EXISTS idx_snapshots_provider ON quota_snapshots(provider_type);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON quota_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_name ON quota_snapshots(quota_name);
CREATE INDEX IF NOT EXISTS idx_snapshots_hour ON quota_snapshots(hour_bucket);
"""


class Storage:
    """Manages SQLite storage for historical quota data."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Ensure database file and schema exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _get_connection(self):
        """Get a database connection with proper row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def record_quotas(
        self,
        account_email: str,
        provider_type: str,
        quotas: List[Dict[str, Any]],
        timestamp: Optional[datetime] = None,
    ) -> int:
        """Record quota snapshots with hourly deduplication.

        Args:
            account_email: The account identifier
            provider_type: Type of provider (google, chutes, etc.)
            quotas: List of quota dictionaries
            timestamp: Optional timestamp (defaults to now)

        Returns:
            Number of records inserted/updated
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        timestamp_str = timestamp.isoformat()
        hour_str = timestamp.strftime("%Y-%m-%d %H")

        inserted = 0
        with self._get_connection() as conn:
            for quota in quotas:
                # Skip error quotas
                if quota.get("is_error"):
                    continue

                quota_name = quota.get("name", "unknown")

                # Use INSERT OR REPLACE for hourly deduplication
                conn.execute(
                    """
                    INSERT OR REPLACE INTO quota_snapshots
                    (account_email, provider_type, quota_name, display_name,
                     remaining_pct, used, limit_val, reset_time, timestamp, hour_bucket)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        account_email,
                        provider_type,
                        quota_name,
                        quota.get("display_name"),
                        quota.get("remaining_pct"),
                        quota.get("used"),
                        quota.get("limit"),
                        str(quota.get("reset", "")),
                        timestamp_str,
                        hour_str,
                    ),
                )
                inserted += 1

        logger.debug(
            f"Recorded {inserted} quotas for {account_email} at hour {hour_str}"
        )
        return inserted

    def query_history(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        account_email: Optional[str] = None,
        provider_type: Optional[str] = None,
        quota_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query historical quota data.

        Args:
            since: Start time (inclusive)
            until: End time (inclusive)
            account_email: Filter by account
            provider_type: Filter by provider type
            quota_name: Filter by quota name

        Returns:
            List of quota snapshot records
        """
        query = "SELECT * FROM quota_snapshots WHERE 1=1"
        params = []

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND timestamp <= ?"
            params.append(until.isoformat())
        if account_email:
            query += " AND account_email = ?"
            params.append(account_email)
        if provider_type:
            query += " AND provider_type = ?"
            params.append(provider_type)
        if quota_name:
            query += " AND quota_name = ?"
            params.append(quota_name)

        query += " ORDER BY timestamp DESC, account_email, quota_name"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_aggregation(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        account_email: Optional[str] = None,
        provider_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get aggregated statistics per quota over a time period.

        Returns:
            List of dicts with quota stats (min, max, avg, count)
        """
        query = """
            SELECT 
                account_email,
                provider_type,
                quota_name,
                display_name,
                MIN(remaining_pct) as min_remaining,
                MAX(remaining_pct) as max_remaining,
                AVG(remaining_pct) as avg_remaining,
                MIN(used) as min_used,
                MAX(used) as max_used,
                AVG(used) as avg_used,
                COUNT(*) as data_points,
                MIN(timestamp) as first_seen,
                MAX(timestamp) as last_seen
            FROM quota_snapshots
            WHERE 1=1
        """
        params = []

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND timestamp <= ?"
            params.append(until.isoformat())
        if account_email:
            query += " AND account_email = ?"
            params.append(account_email)
        if provider_type:
            query += " AND provider_type = ?"
            params.append(provider_type)

        query += " GROUP BY account_email, provider_type, quota_name"
        query += " ORDER BY account_email, quota_name"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_distinct_accounts(self) -> List[str]:
        """Get list of all tracked account emails."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT account_email FROM quota_snapshots ORDER BY account_email"
            )
            return [row[0] for row in cursor.fetchall()]

    def get_distinct_providers(self) -> List[str]:
        """Get list of all tracked provider types."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT provider_type FROM quota_snapshots ORDER BY provider_type"
            )
            return [row[0] for row in cursor.fetchall()]

    def get_distinct_quotas(self, account_email: Optional[str] = None) -> List[str]:
        """Get list of all tracked quota names."""
        query = "SELECT DISTINCT quota_name FROM quota_snapshots"
        params = []
        if account_email:
            query += " WHERE account_email = ?"
            params.append(account_email)
        query += " ORDER BY quota_name"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [row[0] for row in cursor.fetchall()]

    def get_time_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Get the min and max timestamps in the database."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM quota_snapshots"
            )
            row = cursor.fetchone()
            if row and row[0]:
                min_ts = datetime.fromisoformat(row[0])
                max_ts = datetime.fromisoformat(row[1])
                return min_ts, max_ts
            return None, None

    def purge_old_data(self, before: datetime) -> int:
        """Delete data older than the specified date.

        Args:
            before: Delete records before this timestamp

        Returns:
            Number of records deleted
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM quota_snapshots WHERE timestamp < ?",
                (before.isoformat(),),
            )
            deleted = cursor.rowcount
            logger.info(f"Purged {deleted} old quota records")
            return deleted
