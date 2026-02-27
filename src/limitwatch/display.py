from datetime import datetime, timezone
import re

from rich.console import Console


class DisplayManager:
    def __init__(self):
        self.console = Console()

    def print_main_header(self):
        self.console.print("\n[bold blue]Quota Status[/bold blue]")

    def print_account_header(
        self, email: str, provider: str = "", alias: str = "", group: str = ""
    ):
        if alias:
            display_name = alias
            metadata = f"{email}|{group}" if group else email
        else:
            display_name = email
            metadata = group

        header = f"{provider}: {display_name}" if provider else display_name
        if metadata:
            header += f" [dim]({metadata})[/dim]"
        self.console.print(f"[dim]📧 {header}[/dim]")

    def filter_quotas(self, quotas, client, show_all=False):
        if not quotas or not client:
            return quotas
        return client.filter_quotas(quotas, show_all=show_all)

    def draw_quota_bars(
        self,
        quotas,
        client,
        show_all=False,
        query=None,
        compact=False,
        account_name=None,
    ):
        filtered_quotas = self.filter_quotas(quotas, client, show_all=show_all)
        filtered_quotas = apply_query_filter(filtered_quotas, query)

        if not filtered_quotas:
            self._print_empty_message(quotas, show_all)
            return

        if client:
            filtered_quotas.sort(key=lambda q: client.get_sort_key(q))

        if compact:
            self._draw_compact(filtered_quotas, client, account_name)
        else:
            self._draw_normal(filtered_quotas, client)

    # --- History view methods ---

    def render_history_sparklines(self, history_data):
        """Render history data as sparklines (one per quota)."""
        from rich.table import Table
        from rich.text import Text

        if not history_data:
            self.console.print("[yellow]No historical data found.[/yellow]")
            return

        table = Table(
            title="Quota History (Sparklines)",
            show_header=True,
            header_style="bold blue",
        )
        table.add_column("Account", style="cyan")
        table.add_column("Provider", style="magenta")
        table.add_column("Quota", style="green")
        table.add_column("Trend (24h)", style="white", min_width=30)
        table.add_column("Latest", style="yellow", justify="right")
        table.add_column("Range", style="dim", justify="right")

        # Group by account/quota and create sparklines
        grouped = {}
        for record in history_data:
            key = (
                record["account_email"],
                record["provider_type"],
                record["quota_name"],
            )
            if key not in grouped:
                grouped[key] = {
                    "display_name": record.get("display_name") or record["quota_name"],
                    "values": [],
                }
            if record.get("remaining_pct") is not None:
                grouped[key]["values"].append(record["remaining_pct"])

        for (email, provider, quota_name), data in sorted(grouped.items()):
            values = data["values"]
            if not values:
                continue

            display_name = data["display_name"]
            sparkline = self._generate_sparkline(values)
            latest = f"{values[-1]:.1f}%"
            range_str = f"{min(values):.0f}-{max(values):.0f}%"

            table.add_row(
                email.split("@")[0] if "@" in email else email,
                provider,
                display_name,
                sparkline,
                latest,
                range_str,
            )

        self.console.print(table)

    def _generate_sparkline(self, values, width=20):
        """Generate a simple sparkline string from values."""
        if not values or len(values) < 2:
            return "─" * width

        blocks = " ▁▂▃▄▅▆▇█"
        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val if max_val != min_val else 1

        # Sample or interpolate to fit width
        if len(values) <= width:
            # Repeat values to fill width
            step = len(values) / width
            sampled = [values[int(i * step)] for i in range(width)]
        else:
            # Sample evenly
            step = len(values) / width
            sampled = [values[int(i * step)] for i in range(width)]

        sparkline = ""
        for val in sampled:
            normalized = (val - min_val) / range_val
            idx = int(normalized * (len(blocks) - 1))
            sparkline += blocks[idx]

        return sparkline

    def render_history_table(self, history_data):
        """Render history data as a time-series table."""
        from rich.table import Table
        from datetime import datetime

        if not history_data:
            self.console.print("[yellow]No historical data found.[/yellow]")
            return

        table = Table(
            title="Quota History (Time Series)",
            show_header=True,
            header_style="bold blue",
        )
        table.add_column("Time", style="dim", min_width=20)
        table.add_column("Account", style="cyan")
        table.add_column("Provider", style="magenta")
        table.add_column("Quota", style="green")
        table.add_column("Remaining %", style="yellow", justify="right")
        table.add_column("Used", style="blue", justify="right")
        table.add_column("Limit", style="dim", justify="right")

        for record in history_data[:100]:  # Limit to 100 most recent
            timestamp = record["timestamp"]
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = timestamp[:16]  # First 16 chars
            else:
                time_str = str(timestamp)[:16]

            remaining = (
                f"{record['remaining_pct']:.1f}%"
                if record.get("remaining_pct") is not None
                else "N/A"
            )
            used = f"{record['used']:.0f}" if record.get("used") is not None else "N/A"
            limit = (
                f"{record['limit_val']:.0f}"
                if record.get("limit_val") is not None
                else "N/A"
            )

            display_name = record.get("display_name") or record["quota_name"]

            table.add_row(
                time_str,
                record["account_email"].split("@")[0]
                if "@" in record["account_email"]
                else record["account_email"],
                record["provider_type"],
                display_name,
                remaining,
                used,
                limit,
            )

        if len(history_data) > 100:
            table.add_row(
                "...",
                f"[{len(history_data) - 100} more records]",
                "",
                "",
                "",
                "",
                "",
                style="dim",
            )

        self.console.print(table)

    def print_history_summary(self, info):
        """Print a summary of the history database."""
        from rich.table import Table

        self.console.print("\n[bold blue]History Database Summary[/bold blue]")

        table = Table(show_header=False, box=None)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Database Path", info["path"])
        table.add_row("Oldest Record", info["oldest_record"] or "None")
        table.add_row("Newest Record", info["newest_record"] or "None")
        table.add_row("Accounts Tracked", str(len(info["accounts"])))
        table.add_row("Providers Tracked", ", ".join(info["providers"]) or "None")

        self.console.print(table)
        self.console.print()

        if client:
            filtered_quotas.sort(key=lambda q: client.get_sort_key(q))

        if compact:
            self._draw_compact(filtered_quotas, client, account_name)
        else:
            self._draw_normal(filtered_quotas, client)

    def _print_empty_message(self, quotas, show_all):
        if not quotas:
            self.console.print("[yellow]No active quota information found.[/yellow]")
        elif not show_all:
            self.console.print(
                "[dim]No premium models found (use --show-all to see all models).[/dim]"
            )
        else:
            self.console.print("[yellow]No active quota information found.[/yellow]")

    def _draw_compact(self, filtered_quotas, client, account_name):
        if not filtered_quotas:
            return

        short_indicator = client.short_indicator if client else "?"
        provider_color = client.primary_color if client else "white"

        # Compact account name: drop any leading "owner: " prefix (e.g. "lucashutch: Myriota" -> "Myriota")
        display_account = account_name or ""
        if isinstance(display_account, str) and ": " in display_account:
            display_account = display_account.split(": ", 1)[1]

        # Keep a fixed-width account field to align bars across rows in compact view
        account_field = display_account[:10] if isinstance(display_account, str) else ""
        account_field = account_field.ljust(10)
        prefix = f"[{provider_color}]{short_indicator}[/] {account_field}: "

        reserved_width = len(prefix) + 30
        terminal_width = self.console.width
        bar_width = max(5, min(30, terminal_width - reserved_width))

        for q in filtered_quotas:
            name = q.get("display_name", q.get("name"))

            # For compact display of Google provider models, drop a leading
            # "Gemini " to make labels shorter (e.g. "Gemini Pro" -> "Pro").
            try:
                short_ind = getattr(client, "short_indicator", None) if client else None
            except Exception:
                short_ind = None
            if short_ind == "G" and isinstance(name, str):
                if name.lower().startswith("gemini "):
                    name = name.split(" ", 1)[1]

            # Remove numeric parenthetical suffixes like " (300/300)" for compact display
            if isinstance(name, str):
                name = re.sub(r"\s*\(\d+/\d+\)\s*$", "", name)
            shown_pct, is_used, remaining_pct = extract_percentages(q)

            if q.get("is_error"):
                message = q.get("message", "Error")
                self.console.print(f"{prefix}[red]{name}: {message}[/red]")
                continue

            if q.get("show_progress", True) is False:
                self.console.print(f"{prefix}{name}")
                continue

            bar_color = get_bar_color(shown_pct, is_used)
            bar = render_compact_bar(shown_pct, bar_width, bar_color)
            reset_str = get_reset_string(q.get("reset") or "Unknown", remaining_pct)
            suffix = f"{shown_pct:5.1f}% used" if is_used else f"{shown_pct:5.1f}%"
            self.console.print(f"{prefix}{name[:18]:18} {bar} {suffix}{reset_str}")

    def _draw_normal(self, filtered_quotas, client):
        # Reserve space for: padded_name(22) + space(1) + suffix(8) + reset_str(~20)
        # Reduce end-of-row buffer from 60 to 50 to allow more bar space
        reserved_width = 50
        terminal_width = self.console.width
        bar_width = max(10, min(60, terminal_width - reserved_width))

        for q in filtered_quotas:
            name = q.get("display_name", q.get("name"))
            shown_pct, is_used, remaining_pct = extract_percentages(q)

            name_color = client.get_color(q) if client else "white"
            padded_name = f"{name:22}"
            styled_name = f"[{name_color}]{padded_name}[/]"

            if q.get("is_error"):
                self._print_error_quota(styled_name, q)
                continue

            if q.get("show_progress", True) is False:
                self.console.print(f"{styled_name}")
                continue

            bar_color = get_bar_color(shown_pct, is_used)
            bar = render_normal_bar(shown_pct, bar_width, bar_color)
            reset_str = get_reset_string(q.get("reset") or "Unknown", remaining_pct)
            suffix = f"{shown_pct:5.1f}% used" if is_used else f"{shown_pct:5.1f}%"
            self.console.print(f"{styled_name} {bar} {suffix}{reset_str}")

    def _print_error_quota(self, styled_name, quota):
        message = quota.get("message", "Validation Required")
        url = quota.get("url", "")
        if url:
            self.console.print(
                f"{styled_name} [red]⚠️ {message}[/red] "
                f"[link={url}][dim]-> Click here to verify <-[/dim][/link]"
            )
        else:
            self.console.print(f"{styled_name} [red]⚠️ {message}[/red]")

    def _generate_sparkline(self, values, width=20):
        """Generate a simple sparkline string from values."""
        if not values or len(values) < 2:
            return "─" * width

        blocks = " ▁▂▃▄▅▆▇█"
        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val if max_val != min_val else 1

        # Sample or interpolate to fit width
        if len(values) <= width:
            step = len(values) / width
            sampled = [values[int(i * step)] for i in range(width)]
        else:
            step = len(values) / width
            sampled = [values[int(i * step)] for i in range(width)]

        sparkline = ""
        for val in sampled:
            normalized = (val - min_val) / range_val
            idx = int(normalized * (len(blocks) - 1))
            sparkline += blocks[idx]

        return sparkline

    def render_history_table(self, history_data):
        """Render history data as a time-series table."""
        from rich.table import Table
        from datetime import datetime

        if not history_data:
            self.console.print("[yellow]No historical data found.[/yellow]")
            return

        table = Table(
            title="Quota History (Time Series)",
            show_header=True,
            header_style="bold blue",
        )
        table.add_column("Time", style="dim", min_width=20)
        table.add_column("Account", style="cyan")
        table.add_column("Provider", style="magenta")
        table.add_column("Quota", style="green")
        table.add_column("Remaining %", style="yellow", justify="right")
        table.add_column("Used", style="blue", justify="right")
        table.add_column("Limit", style="dim", justify="right")

        for record in history_data[:100]:  # Limit to 100 most recent
            timestamp = record["timestamp"]
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = timestamp[:16]  # First 16 chars
            else:
                time_str = str(timestamp)[:16]

            remaining = (
                f"{record['remaining_pct']:.1f}%"
                if record.get("remaining_pct") is not None
                else "N/A"
            )
            used = f"{record['used']:.0f}" if record.get("used") is not None else "N/A"
            limit = (
                f"{record['limit_val']:.0f}"
                if record.get("limit_val") is not None
                else "N/A"
            )

            display_name = record.get("display_name") or record["quota_name"]

            table.add_row(
                time_str,
                record["account_email"].split("@")[0]
                if "@" in record["account_email"]
                else record["account_email"],
                record["provider_type"],
                display_name,
                remaining,
                used,
                limit,
            )

        if len(history_data) > 100:
            table.add_row(
                "...",
                f"[{len(history_data) - 100} more records]",
                "",
                "",
                "",
                "",
                "",
                style="dim",
            )

        self.console.print(table)

    def print_history_summary(self, info):
        """Print a summary of the history database."""
        from rich.table import Table

        self.console.print("\n[bold blue]History Database Summary[/bold blue]")

        table = Table(show_header=False, box=None)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Database Path", info["path"])
        table.add_row("Oldest Record", info["oldest_record"] or "None")
        table.add_row("Newest Record", info["newest_record"] or "None")
        table.add_row("Accounts Tracked", str(len(info["accounts"])))
        table.add_row("Providers Tracked", ", ".join(info["providers"]) or "None")

        self.console.print(table)
        self.console.print()

    def render_activity_heatmap(self, weekly_data):
        """Render weekly activity as a heatmap (days × accounts)."""
        if not weekly_data.get("daily_per_account"):
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        daily_per_account = weekly_data["daily_per_account"]
        accounts = weekly_data["accounts"]
        dates = weekly_data["dates"]
        day_labels = weekly_data["days"]

        if not accounts or not dates:
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        blocks = " ░▒▓█"

        account_data = {}
        for acc in accounts:
            account_data[acc] = {d: 0 for d in dates}
            for row in daily_per_account:
                if row["account_email"] == acc:
                    account_data[acc][row["date"]] = row["record_count"]

        max_records = max((row["record_count"] for row in daily_per_account), default=1)

        header = "Account".ljust(20) + "  " + "  ".join(d.ljust(2) for d in day_labels)
        separator = "-" * (23 + len(day_labels) * 3)

        self.console.print("\n[bold blue]Activity Heatmap (Last 7 Days)[/bold blue]")
        self.console.print(
            "[dim]Intensity = number of quota snapshots recorded[/dim]\n"
        )
        self.console.print(header)
        self.console.print(separator)

        for acc in accounts:
            short_name = acc.split("@")[0] if "@" in acc else acc[:18]
            row_str = short_name.ljust(20) + "  "
            for date in dates:
                count = account_data[acc].get(date, 0)
                if count == 0:
                    idx = 0
                else:
                    idx = min(int((count / max_records) * 4), 4)
                row_str += blocks[idx] + "  "
            self.console.print(row_str)

        self.console.print(
            f"\n[dim]Legend: {blocks[0]} = none  {blocks[1]} = low  {blocks[2]} = medium  {blocks[3]} = high  {blocks[4]} = very high[/dim]"
        )

    def render_ascii_chart(self, weekly_data):
        """Render weekly data as ASCII line chart showing remaining % over time."""
        if not weekly_data.get("daily_per_account"):
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        daily_per_account = weekly_data["daily_per_account"]
        accounts = weekly_data["accounts"]
        dates = weekly_data["dates"]
        day_labels = weekly_data["days"]

        if not accounts or not dates:
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        self.console.print("\n[bold blue]Quota Remaining % (Last 7 Days)[/bold blue]")
        self.console.print("[dim]Average remaining % per account per day[/dim]\n")

        account_avgs = {}
        for acc in accounts:
            account_avgs[acc] = {}
            for date in dates:
                account_avgs[acc][date] = None

            for row in daily_per_account:
                if row["account_email"] == acc and row.get("avg_remaining_pct"):
                    account_avgs[acc][row["date"]] = row["avg_remaining_pct"]

        for acc in accounts:
            short_name = acc.split("@")[0] if "@" in acc else acc[:18]
            self.console.print(f"[cyan]{short_name}[/cyan]:")

            values = [account_avgs[acc].get(d) for d in dates]
            valid_values = [v for v in values if v is not None]

            if not valid_values:
                self.console.print("  [dim]No data[/dim]")
                continue

            chart = self._generate_line_chart(values, day_labels)
            self.console.print(chart)
            self.console.print()

    def _generate_line_chart(self, values, labels):
        """Generate an ASCII line chart from values."""
        if not values:
            return ""

        chart_lines = []
        chart_width = len(labels) * 4

        for pct in [100, 80, 60, 40, 20, 0]:
            line = f"{pct:3}% │"

            for i, val in enumerate(values):
                if val is None:
                    line += "   ·"
                elif val >= pct:
                    if i > 0 and values[i - 1] is not None and values[i - 1] >= pct:
                        line += "───"
                    else:
                        line += "·──"
                else:
                    line += "   "

            chart_lines.append(line)

        chart_str = "\n".join(chart_lines)
        chart_str += "\n    " + "┼" + "─" * (chart_width - 1)

        x_labels = ""
        for label in labels:
            x_labels += f"  {label[:2]} "
        chart_str += "\n    " + x_labels

        return chart_str

    def render_calendar_view(self, weekly_data):
        """Render weekly activity as a calendar-style view."""
        if not weekly_data.get("daily_per_account"):
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        daily_per_account = weekly_data["daily_per_account"]
        dates = weekly_data["dates"]
        day_labels = weekly_data["days"]
        daily_totals = weekly_data["daily_totals"]

        if not dates:
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        self.console.print("\n[bold blue]Weekly Activity Calendar[/bold blue]\n")

        totals_map = {d["date"]: d for d in daily_totals}

        blocks = " ░▒▓█"

        for date, label in zip(dates, day_labels):
            total = totals_map.get(date, {})
            record_count = total.get("record_count", 0)
            total_used = total.get("total_used", 0)
            account_count = total.get("account_count", 0)

            if record_count == 0:
                intensity = 0
            elif record_count <= 2:
                intensity = 1
            elif record_count <= 5:
                intensity = 2
            elif record_count <= 10:
                intensity = 3
            else:
                intensity = 4

            self.console.print(f"┌──────────┐")
            self.console.print(
                f"│ {label:^8} │  [bold]{blocks[intensity] * 4}[/bold] {record_count} snapshots"
            )
            self.console.print(
                f"│ {date[5:]}   │  [cyan]{account_count}[/cyan] accounts active"
            )
            if total_used > 0:
                self.console.print(
                    f"│          │  [yellow]{total_used:.0f}[/yellow] credits used"
                )
            else:
                self.console.print(f"│          │")
            self.console.print(f"└──────────┘")

    def render_daily_bars(self, weekly_data):
        """Render daily credit consumption as horizontal bar chart."""
        if not weekly_data.get("daily_totals"):
            self.console.print(
                "[yellow]No consumption data found for the past week.[/yellow]"
            )
            return

        daily_totals = weekly_data["daily_totals"]
        day_labels = weekly_data["days"]

        if not daily_totals:
            self.console.print(
                "[yellow]No consumption data found for the past week.[/yellow]"
            )
            return

        self.console.print(
            "\n[bold blue]Daily Credit Consumption (Last 7 Days)[/bold blue]\n"
        )

        max_used = max((d.get("total_used", 0) or 0 for d in daily_totals), default=1)
        bar_width = 30

        for i, total in enumerate(daily_totals):
            date = total.get("date", "")
            label = day_labels[i] if i < len(day_labels) else date[5:]
            used = total.get("total_used", 0) or 0
            account_count = total.get("account_count", 0)

            if max_used > 0:
                filled = int((used / max_used) * bar_width)
                bar = "█" * filled + "░" * (bar_width - filled)
            else:
                bar = "░" * bar_width

            if used > 0:
                pct = (used / max_used) * 100 if max_used > 0 else 0
                self.console.print(
                    f"{label:8} [green]{bar}[/green]  [yellow]{used:.0f}[/yellow] credits ({account_count} acct)"
                )
            else:
                self.console.print(
                    f"{label:8} [dim]{bar}[/dim]  [dim]no activity[/dim]"
                )


# --- Pure helper functions (no self, easily testable) ---


def apply_query_filter(quotas, query):
    """Apply name-based query filtering to a list of quotas."""
    if not query or not quotas:
        return quotas

    queries = [query] if isinstance(query, str) else query
    for q_str in queries:
        q_lower = q_str.lower()
        quotas = [
            q
            for q in quotas
            if q_lower in q.get("name", "").lower()
            or q_lower in q.get("display_name", "").lower()
        ]
    return quotas


def extract_percentages(quota):
    """Extract shown percentage, whether it's used-mode, and remaining_pct from a quota dict."""
    used_pct = quota.get("used_pct")
    remaining_pct = quota.get("remaining_pct", 100)
    if used_pct is not None:
        return float(used_pct), True, remaining_pct
    return float(remaining_pct), False, remaining_pct


def get_bar_color(shown_pct, is_used):
    """Determine bar color based on percentage and display mode."""
    if is_used:
        if shown_pct <= 20:
            return "green"
        if shown_pct <= 50:
            return "yellow"
        return "red"
    else:
        if shown_pct <= 20:
            return "red"
        if shown_pct <= 50:
            return "yellow"
        return "green"


def format_time_delta(delta):
    """Format a timedelta into a compact string like '1d 2h 30m'."""
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return ""
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}m")
    return f" [dim]({' '.join(parts)})[/dim]"


def parse_reset_datetime(reset_info):
    """Parse reset_info (ISO string or epoch timestamp) into a datetime, or None."""
    if isinstance(reset_info, str) and "T" in reset_info and "Z" in reset_info:
        try:
            return datetime.fromisoformat(reset_info.replace("Z", "+00:00"))
        except Exception:
            return None
    elif isinstance(reset_info, (int, float)):
        try:
            ts = reset_info / 1000 if reset_info > 1e11 else reset_info
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    return None


def get_reset_string(reset_info, remaining_pct):
    """Build a reset countdown string for display."""
    if reset_info == "Unknown" or remaining_pct >= 100:
        return ""

    dt = parse_reset_datetime(reset_info)
    if dt is None:
        return ""

    now = datetime.now(dt.tzinfo)
    return format_time_delta(dt - now)


def render_compact_bar(shown_pct, bar_width, bar_color):
    """Render a compact progress bar string."""
    total_filled = (shown_pct / 100) * bar_width
    filled_whole = int(total_filled)
    return (
        f"[{bar_color}]" + "█" * filled_whole + "[/]" + " " * (bar_width - filled_whole)
    )


def render_normal_bar(shown_pct, bar_width, bar_color):
    """Render a normal (fractional-block) progress bar string."""
    total_filled = (shown_pct / 100) * bar_width
    filled_whole = int(total_filled)
    remainder = total_filled - filled_whole

    blocks = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
    fraction_block = blocks[int(remainder * 8)]

    if filled_whole >= bar_width:
        return f"[{bar_color}]" + "█" * bar_width + "[/]"

    bar = f"[{bar_color}]" + "█" * filled_whole
    if fraction_block != " ":
        bar += fraction_block
    bar += "[/]"
    used_width = filled_whole + (1 if fraction_block != " " else 0)
    bar += " " * (bar_width - used_width)
    return bar
