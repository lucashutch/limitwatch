"""Export functionality for historical quota data."""

import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .history import HistoryManager

logger = logging.getLogger(__name__)


class Exporter:
    """Exports historical quota data to various formats."""

    def __init__(self, history_mgr: Optional[HistoryManager] = None):
        self.history_mgr = history_mgr or HistoryManager()

    def export_csv(
        self,
        output_path: Optional[Path] = None,
        preset: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        account_email: Optional[str] = None,
        provider_type: Optional[str] = None,
        quota_name: Optional[str] = None,
    ) -> str:
        """Export history data to CSV format.

        Args:
            output_path: Path to write CSV file (if None, returns string)
            preset: Time preset (24h, 7d, 30d, 90d)
            since: Start time string
            until: End time string
            account_email: Filter by account
            provider_type: Filter by provider
            quota_name: Filter by quota

        Returns:
            CSV string if output_path is None, otherwise empty string
        """
        history_data = self.history_mgr.get_history(
            preset=preset,
            since=since,
            until=until,
            account_email=account_email,
            provider_type=provider_type,
            quota_name=quota_name,
        )

        if not history_data:
            logger.warning("No data to export")
            return ""

        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(
            [
                "timestamp",
                "account_email",
                "provider_type",
                "quota_name",
                "display_name",
                "remaining_pct",
                "used",
                "limit",
                "reset_time",
            ]
        )

        # Write data
        for record in history_data:
            writer.writerow(
                [
                    record.get("timestamp", ""),
                    record.get("account_email", ""),
                    record.get("provider_type", ""),
                    record.get("quota_name", ""),
                    record.get("display_name", ""),
                    record.get("remaining_pct", ""),
                    record.get("used", ""),
                    record.get("limit_val", ""),
                    record.get("reset_time", ""),
                ]
            )

        csv_content = output.getvalue()
        output.close()

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", newline="") as f:
                f.write(csv_content)
            logger.info(f"Exported {len(history_data)} records to {output_path}")
            return ""

        return csv_content

    def export_markdown(
        self,
        output_path: Optional[Path] = None,
        preset: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        account_email: Optional[str] = None,
        provider_type: Optional[str] = None,
        quota_name: Optional[str] = None,
    ) -> str:
        """Export history data to Markdown table format.

        Args:
            output_path: Path to write Markdown file (if None, returns string)
            preset: Time preset (24h, 7d, 30d, 90d)
            since: Start time string
            until: End time string
            account_email: Filter by account
            provider_type: Filter by provider
            quota_name: Filter by quota

        Returns:
            Markdown string if output_path is None, otherwise empty string
        """
        history_data = self.history_mgr.get_history(
            preset=preset,
            since=since,
            until=until,
            account_email=account_email,
            provider_type=provider_type,
            quota_name=quota_name,
        )

        if not history_data:
            logger.warning("No data to export")
            return ""

        lines = []
        lines.append("# Quota History Export")
        lines.append("")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("")

        # Add filters info
        if preset or since or account_email or provider_type or quota_name:
            lines.append("## Filters")
            if preset:
                lines.append(f"- Time Range: {preset}")
            if since:
                lines.append(f"- Since: {since}")
            if until:
                lines.append(f"- Until: {until}")
            if account_email:
                lines.append(f"- Account: {account_email}")
            if provider_type:
                lines.append(f"- Provider: {provider_type}")
            if quota_name:
                lines.append(f"- Quota: {quota_name}")
            lines.append("")

        lines.append("## Data")
        lines.append("")
        lines.append(
            "| Timestamp | Account | Provider | Quota | Remaining % | Used | Limit |"
        )
        lines.append(
            "|-----------|---------|----------|-------|-------------|------|-------|"
        )

        for record in history_data:
            timestamp = record.get("timestamp", "")[:16]  # Truncate to remove seconds
            account = record.get("account_email", "").split("@")[0]
            provider = record.get("provider_type", "")
            quota = record.get("display_name") or record.get("quota_name", "")
            remaining = (
                f"{record.get('remaining_pct', 0):.1f}%"
                if record.get("remaining_pct") is not None
                else "N/A"
            )
            used = (
                f"{record.get('used', 0):.0f}"
                if record.get("used") is not None
                else "N/A"
            )
            limit = (
                f"{record.get('limit_val', 0):.0f}"
                if record.get("limit_val") is not None
                else "N/A"
            )

            lines.append(
                f"| {timestamp} | {account} | {provider} | {quota} | {remaining} | {used} | {limit} |"
            )

        lines.append("")
        lines.append(f"*Total records: {len(history_data)}*")
        lines.append("")

        markdown_content = "\n".join(lines)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                f.write(markdown_content)
            logger.info(f"Exported {len(history_data)} records to {output_path}")
            return ""

        return markdown_content

    def get_export_info(
        self,
        preset: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        account_email: Optional[str] = None,
        provider_type: Optional[str] = None,
        quota_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get information about what would be exported.

        Returns:
            Dict with record count and date range
        """
        history_data = self.history_mgr.get_history(
            preset=preset,
            since=since,
            until=until,
            account_email=account_email,
            provider_type=provider_type,
            quota_name=quota_name,
        )

        if not history_data:
            return {
                "record_count": 0,
                "date_range": None,
            }

        timestamps = [r["timestamp"] for r in history_data if r.get("timestamp")]
        if timestamps:
            timestamps.sort()
            return {
                "record_count": len(history_data),
                "date_range": {
                    "start": timestamps[0],
                    "end": timestamps[-1],
                },
            }

        return {
            "record_count": len(history_data),
            "date_range": None,
        }
