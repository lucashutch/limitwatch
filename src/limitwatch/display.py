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

    def _get_pct_color(self, pct):
        """Get a Rich color string based on a remaining percentage value."""
        if pct >= 80:
            return "green"
        if pct >= 60:
            return "bright_green"
        if pct >= 40:
            return "yellow"
        if pct >= 20:
            return "dark_orange"
        return "red"

    def _get_trend_indicator(self, values):
        """Return a trend arrow and label based on value direction."""
        if len(values) < 2:
            return "[dim]--[/dim]"
        first_third = sum(values[: len(values) // 3]) / max(len(values) // 3, 1)
        last_third = sum(values[-(len(values) // 3) :]) / max(len(values) // 3, 1)
        diff = last_third - first_third
        if abs(diff) < 1.0:
            return "[dim]=[/dim] [dim]stable[/dim]"
        if diff > 10:
            return "[green]^[/green] [green]rising[/green]"
        if diff > 0:
            return "[bright_green]^[/bright_green] [dim]rising[/dim]"
        if diff < -10:
            return "[red]v[/red] [red]falling[/red]"
        return "[dark_orange]v[/dark_orange] [dim]falling[/dim]"

    def render_history_sparklines(self, history_data):
        """Render history data as sparklines with color gradients and trend indicators."""
        from rich.table import Table
        from rich import box

        if not history_data:
            self.console.print("[yellow]No historical data found.[/yellow]")
            return

        table = Table(
            title="Quota History",
            title_style="bold blue",
            show_header=True,
            header_style="bold bright_white",
            box=box.ROUNDED,
            border_style="blue",
            padding=(0, 1),
        )
        table.add_column("Account", style="cyan", no_wrap=True)
        table.add_column("Provider", style="magenta", no_wrap=True)
        table.add_column("Quota", style="white", no_wrap=True)
        table.add_column("Trend", min_width=24, no_wrap=True)
        table.add_column("Current", justify="right", no_wrap=True)
        table.add_column("Min", justify="right", no_wrap=True)
        table.add_column("Max", justify="right", no_wrap=True)
        table.add_column("Direction", no_wrap=True)

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
            latest = values[-1]
            latest_color = self._get_pct_color(latest)
            min_val = min(values)
            max_val = max(values)
            min_color = self._get_pct_color(min_val)
            max_color = self._get_pct_color(max_val)
            trend = self._get_trend_indicator(values)

            table.add_row(
                email.split("@")[0] if "@" in email else email,
                provider,
                display_name,
                sparkline,
                f"[{latest_color}]{latest:.1f}%[/]",
                f"[{min_color}]{min_val:.0f}%[/]",
                f"[{max_color}]{max_val:.0f}%[/]",
                trend,
            )

        self.console.print()
        self.console.print(table)
        self.console.print(
            f"  [dim]{len(grouped)} quotas tracked across {len(history_data)} snapshots[/dim]"
        )
        self.console.print()

    def _generate_sparkline(self, values, width=20):
        """Generate a colored sparkline string using Rich markup."""
        if not values or len(values) < 2:
            return "[dim]" + "─" * width + "[/dim]"

        blocks = " ▁▂▃▄▅▆▇█"

        # Sample values to fit width
        step = len(values) / width
        sampled = [values[min(int(i * step), len(values) - 1)] for i in range(width)]

        # Use absolute scale (0-100%) for remaining_pct values
        min_val = 0.0
        max_val = 100.0
        range_val = max_val - min_val

        sparkline = ""
        for val in sampled:
            normalized = max(0.0, min(1.0, (val - min_val) / range_val))
            idx = int(normalized * (len(blocks) - 1))
            color = self._get_pct_color(val)
            sparkline += f"[{color}]{blocks[idx]}[/]"

        return sparkline

    def render_history_table(self, history_data):
        """Render history data as a styled time-series table with color-coded percentages."""
        from rich.table import Table
        from rich import box
        from datetime import datetime

        if not history_data:
            self.console.print("[yellow]No historical data found.[/yellow]")
            return

        table = Table(
            title=f"Quota History ({min(len(history_data), 100)} of {len(history_data)} records)",
            title_style="bold blue",
            show_header=True,
            header_style="bold bright_white",
            box=box.SIMPLE_HEAVY,
            border_style="blue",
            row_styles=["", "dim"],
        )
        table.add_column("Time", style="bright_black", no_wrap=True)
        table.add_column("Account", style="cyan", no_wrap=True)
        table.add_column("Provider", style="magenta", no_wrap=True)
        table.add_column("Quota", style="white")
        table.add_column("Remaining", justify="right", no_wrap=True)
        table.add_column("Bar", no_wrap=True, min_width=12)
        table.add_column("Used", style="blue", justify="right", no_wrap=True)
        table.add_column("Limit", style="dim", justify="right", no_wrap=True)

        for record in history_data[:100]:
            timestamp = record["timestamp"]
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%b %d %H:%M")
                except Exception:
                    time_str = timestamp[:16]
            else:
                time_str = str(timestamp)[:16]

            remaining_pct = record.get("remaining_pct")
            if remaining_pct is not None:
                color = self._get_pct_color(remaining_pct)
                remaining = f"[{color}]{remaining_pct:.1f}%[/]"
                # Mini bar (10 chars wide)
                filled = int(remaining_pct / 10)
                bar = f"[{color}]{'█' * filled}[/][dim]{'░' * (10 - filled)}[/dim]"
            else:
                remaining = "[dim]N/A[/dim]"
                bar = "[dim]░░░░░░░░░░[/dim]"

            used = f"{record['used']:,.0f}" if record.get("used") is not None else "N/A"
            limit = (
                f"{record['limit_val']:,.0f}"
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
                bar,
                used,
                limit,
            )

        if len(history_data) > 100:
            table.add_row(
                "",
                f"[dim]... {len(history_data) - 100} more records[/dim]",
                "",
                "",
                "",
                "",
                "",
                "",
            )

        self.console.print()
        self.console.print(table)
        self.console.print()

    def print_history_summary(self, info):
        """Print a summary of the history database using Rich panels."""
        from rich.table import Table
        from rich.panel import Panel
        from rich import box

        rows = []
        rows.append(("Database", info["path"]))
        rows.append(("Oldest Record", info["oldest_record"] or "[dim]None[/dim]"))
        rows.append(("Newest Record", info["newest_record"] or "[dim]None[/dim]"))
        rows.append(("Accounts", str(len(info["accounts"]))))
        rows.append(
            (
                "Providers",
                ", ".join(info["providers"])
                if info["providers"]
                else "[dim]None[/dim]",
            )
        )
        if info["accounts"]:
            rows.append(("Account List", ", ".join(info["accounts"])))

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan bold", no_wrap=True)
        table.add_column("Value", style="white")
        for key, value in rows:
            table.add_row(key, value)

        panel = Panel(
            table,
            title="History Database Summary",
            title_align="left",
            border_style="blue",
            box=box.ROUNDED,
            padding=(1, 2),
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

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

    def render_activity_heatmap(self, weekly_data):
        """Render weekly activity as a rich heatmap table with colored cells."""
        from rich.table import Table
        from rich import box

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

        # Build lookup: account -> date -> record_count
        account_data = {}
        for acc in accounts:
            account_data[acc] = {d: 0 for d in dates}
            for row in daily_per_account:
                if row["account_email"] == acc:
                    account_data[acc][row["date"]] = row["record_count"]

        max_records = max((row["record_count"] for row in daily_per_account), default=1)

        # Color scale for heatmap intensity
        heat_colors = ["bright_black", "blue", "cyan", "yellow", "bright_green"]
        heat_blocks = ["  ·  ", " ░░░ ", " ▒▒▒ ", " ▓▓▓ ", " ███ "]

        table = Table(
            title="Activity Heatmap (Last 7 Days)",
            title_style="bold blue",
            show_header=True,
            header_style="bold bright_white",
            box=box.ROUNDED,
            border_style="blue",
            padding=(0, 0),
        )
        table.add_column("Account", style="cyan", no_wrap=True, min_width=16)
        for label in day_labels:
            table.add_column(label, justify="center", no_wrap=True, min_width=5)
        table.add_column("Total", justify="right", style="bold", no_wrap=True)

        for acc in accounts:
            short_name = acc.split("@")[0] if "@" in acc else acc[:16]
            cells = []
            total = 0
            for date in dates:
                count = account_data[acc].get(date, 0)
                total += count
                if count == 0:
                    idx = 0
                else:
                    idx = min(int((count / max_records) * 4) + 1, 4)
                color = heat_colors[idx]
                block = heat_blocks[idx]
                cells.append(f"[{color}]{block}[/]")

            table.add_row(short_name, *cells, str(total))

        # Totals row
        total_cells = []
        grand_total = 0
        for date in dates:
            day_total = sum(account_data[acc].get(date, 0) for acc in accounts)
            grand_total += day_total
            total_cells.append(f"[dim]{day_total}[/dim]")
        table.add_row(
            "[bold]Total[/bold]",
            *total_cells,
            f"[bold]{grand_total}[/bold]",
            style="dim",
        )

        self.console.print()
        self.console.print(table)
        legend_parts = []
        for i, (color, label) in enumerate(
            zip(heat_colors, ["none", "low", "medium", "high", "peak"])
        ):
            legend_parts.append(f"[{color}]{heat_blocks[i].strip()}[/] {label}")
        self.console.print(f"  [dim]Legend:[/dim] {'  '.join(legend_parts)}")
        self.console.print()

    def render_ascii_chart(self, weekly_data):
        """Render weekly data as a braille-resolution line chart showing remaining % over time."""
        from rich.panel import Panel
        from rich import box

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

        # Build account -> date -> avg_remaining_pct lookup
        account_avgs = {}
        for acc in accounts:
            account_avgs[acc] = {}
            for row in daily_per_account:
                if (
                    row["account_email"] == acc
                    and row.get("avg_remaining_pct") is not None
                ):
                    account_avgs[acc][row["date"]] = row["avg_remaining_pct"]

        # Assign colors to accounts for multi-line chart
        acc_colors = [
            "cyan",
            "magenta",
            "green",
            "yellow",
            "red",
            "blue",
            "bright_green",
            "bright_red",
        ]

        chart_height = 12  # rows

        for acc_idx, acc in enumerate(accounts):
            short_name = acc.split("@")[0] if "@" in acc else acc[:18]
            color = acc_colors[acc_idx % len(acc_colors)]

            values = [account_avgs[acc].get(d) for d in dates]
            valid_values = [v for v in values if v is not None]

            if not valid_values:
                self.console.print(f"  [{color}]{short_name}[/]: [dim]No data[/dim]")
                continue

            chart = self._generate_braille_chart(
                values, day_labels, chart_height, color
            )

            panel = Panel(
                chart,
                title=f"[{color}]{short_name}[/] - Remaining %",
                title_align="left",
                border_style=color,
                box=box.ROUNDED,
                padding=(0, 1),
            )
            self.console.print()
            self.console.print(panel)

        self.console.print()

    def _generate_braille_chart(self, values, labels, height=12, color="cyan"):
        """Generate an improved ASCII area chart with filled regions."""
        if not values:
            return ""

        y_labels = [100, 80, 60, 40, 20, 0]
        col_width = 6

        chart_lines = []
        for row_idx, pct_threshold in enumerate(y_labels):
            if row_idx == 0:
                label = f"[dim]{pct_threshold:>3}%[/dim] "
            else:
                label = f"[dim]{pct_threshold:>3}%[/dim] "

            line_chars = ""
            for i, val in enumerate(values):
                segment = " " * col_width
                if val is None:
                    # Show gap
                    segment = "[dim]" + "·" * col_width + "[/dim]"
                elif val >= pct_threshold:
                    next_threshold = y_labels[row_idx - 1] if row_idx > 0 else 101
                    if val >= next_threshold:
                        # Fully filled row
                        segment = f"[{color}]" + "█" * col_width + "[/]"
                    else:
                        # Partially filled - top of the bar
                        segment = f"[{color}]" + "▓" * col_width + "[/]"
                else:
                    # Below the value - show faint fill if value is close
                    if pct_threshold - val < 20 and val > 0:
                        segment = "[dim]" + "░" * col_width + "[/dim]"
                    else:
                        segment = " " * col_width

                line_chars += segment

            chart_lines.append(label + "│" + line_chars)

        # X-axis
        axis_line = "     └" + "─" * (len(values) * col_width)
        chart_lines.append(axis_line)

        # X-labels
        x_label_line = "      "
        for label in labels:
            x_label_line += f"{label:^{col_width}}"
        chart_lines.append(x_label_line)

        # Stats line
        valid = [v for v in values if v is not None]
        if valid:
            avg = sum(valid) / len(valid)
            avg_color = self._get_pct_color(avg)
            stats = f"      [{avg_color}]avg: {avg:.1f}%[/]  "
            stats += f"[{self._get_pct_color(min(valid))}]min: {min(valid):.1f}%[/]  "
            stats += f"[{self._get_pct_color(max(valid))}]max: {max(valid):.1f}%[/]"
            chart_lines.append(stats)

        return "\n".join(chart_lines)

    def render_calendar_view(self, weekly_data):
        """Render weekly activity as a row of Rich panels for each day."""
        from rich.columns import Columns
        from rich.panel import Panel
        from rich import box

        if not weekly_data.get("daily_per_account"):
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        dates = weekly_data["dates"]
        day_labels = weekly_data["days"]
        daily_totals = weekly_data["daily_totals"]

        if not dates:
            self.console.print(
                "[yellow]No activity data found for the past week.[/yellow]"
            )
            return

        totals_map = {d["date"]: d for d in daily_totals}

        # Find max values for relative scaling
        max_records = (
            max((t.get("record_count", 0) for t in daily_totals), default=1) or 1
        )

        self.console.print()
        self.console.print("[bold blue]  Weekly Activity Calendar[/bold blue]")
        self.console.print()

        panels = []
        for date, label in zip(dates, day_labels):
            total = totals_map.get(date, {})
            record_count = total.get("record_count", 0)
            total_used = total.get("total_used", 0) or 0
            account_count = total.get("account_count", 0)

            # Activity level bar (relative to the week's max)
            if record_count > 0 and max_records > 0:
                bar_filled = max(1, int((record_count / max_records) * 8))
            else:
                bar_filled = 0

            # Determine border color based on activity level
            if record_count == 0:
                border_color = "bright_black"
            elif record_count <= max_records * 0.25:
                border_color = "blue"
            elif record_count <= max_records * 0.5:
                border_color = "cyan"
            elif record_count <= max_records * 0.75:
                border_color = "yellow"
            else:
                border_color = "green"

            # Build card content
            activity_bar = f"[{border_color}]{'█' * bar_filled}[/][dim]{'░' * (8 - bar_filled)}[/dim]"

            lines = []
            lines.append(f"[bold]{date[5:]}[/bold]")
            lines.append("")
            lines.append(activity_bar)
            lines.append("")
            lines.append(f"[cyan]{record_count}[/] snapshots")
            lines.append(f"[magenta]{account_count}[/] accounts")
            if total_used > 0:
                lines.append(f"[yellow]{total_used:,.0f}[/] credits")
            else:
                lines.append("[dim]no credits[/dim]")

            panel = Panel(
                "\n".join(lines),
                title=f"[bold]{label}[/bold]",
                title_align="center",
                border_style=border_color,
                box=box.ROUNDED,
                width=18,
                padding=(0, 1),
            )
            panels.append(panel)

        self.console.print(Columns(panels, equal=True, expand=True))
        self.console.print()

    def render_daily_bars(self, weekly_data):
        """Render daily credit consumption as styled horizontal bar chart."""
        from rich.table import Table
        from rich import box

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

        max_used = (
            max((d.get("total_used", 0) or 0 for d in daily_totals), default=1) or 1
        )
        bar_width = min(35, max(15, self.console.width - 50))

        # Color scale based on relative usage
        def get_bar_color(used, max_val):
            ratio = used / max_val if max_val > 0 else 0
            if ratio >= 0.8:
                return "red"
            if ratio >= 0.6:
                return "dark_orange"
            if ratio >= 0.4:
                return "yellow"
            if ratio >= 0.2:
                return "bright_green"
            return "green"

        table = Table(
            title="Daily Credit Consumption (Last 7 Days)",
            title_style="bold blue",
            show_header=True,
            header_style="bold bright_white",
            box=box.ROUNDED,
            border_style="blue",
            padding=(0, 1),
        )
        table.add_column("Day", style="bold", no_wrap=True, min_width=8)
        table.add_column("Usage", no_wrap=True, min_width=bar_width + 2)
        table.add_column("Credits", justify="right", no_wrap=True)
        table.add_column("Accounts", justify="center", no_wrap=True)
        table.add_column("% of Peak", justify="right", no_wrap=True)

        peak_day = None
        total_credits = 0

        for i, total in enumerate(daily_totals):
            date = total.get("date", "")
            label = day_labels[i] if i < len(day_labels) else date[5:]
            used = total.get("total_used", 0) or 0
            account_count = total.get("account_count", 0)
            total_credits += used

            pct_of_peak = (used / max_used * 100) if max_used > 0 else 0

            if used == max_used and used > 0:
                peak_day = label

            if used > 0:
                filled = max(1, int((used / max_used) * bar_width))
                color = get_bar_color(used, max_used)
                bar = (
                    f"[{color}]{'█' * filled}[/][dim]{'░' * (bar_width - filled)}[/dim]"
                )
                pct_str = f"[{color}]{pct_of_peak:.0f}%[/]"
                if used == max_used:
                    pct_str += " [bold yellow]*[/bold yellow]"
                credit_str = f"[yellow]{used:,.0f}[/]"
                acct_str = f"[cyan]{account_count}[/]"
            else:
                bar = f"[dim]{'░' * bar_width}[/dim]"
                pct_str = "[dim]--[/dim]"
                credit_str = "[dim]0[/dim]"
                acct_str = "[dim]0[/dim]"

            table.add_row(label, bar, credit_str, acct_str, pct_str)

        self.console.print()
        self.console.print(table)

        # Summary footer
        avg_credits = total_credits / len(daily_totals) if daily_totals else 0
        summary = f"  [dim]Total: [yellow]{total_credits:,.0f}[/yellow] credits"
        summary += f"  |  Avg: [yellow]{avg_credits:,.0f}[/yellow]/day"
        if peak_day:
            summary += f"  |  [bold yellow]*[/bold yellow] Peak: {peak_day}[/dim]"
        self.console.print(summary)
        self.console.print()

    def render_stats_dashboard(self, history_data, weekly_data, aggregation_data):
        """Render a comprehensive stats dashboard with key metrics."""
        from rich.table import Table
        from rich.panel import Panel
        from rich.columns import Columns
        from rich import box

        self.console.print()
        self.console.print("[bold blue]  Quota Statistics Dashboard[/bold blue]")
        self.console.print()

        # --- Top row: Key metric panels ---
        panels = []

        # Panel 1: Snapshot count and date range
        total_snapshots = len(history_data) if history_data else 0
        if history_data:
            from datetime import datetime

            timestamps = []
            for r in history_data:
                try:
                    ts = r["timestamp"]
                    if isinstance(ts, str):
                        timestamps.append(
                            datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        )
                except Exception:
                    pass
            if timestamps:
                span = max(timestamps) - min(timestamps)
                days = span.days
                hours = span.seconds // 3600
                span_str = f"{days}d {hours}h" if days > 0 else f"{hours}h"
            else:
                span_str = "N/A"
        else:
            span_str = "N/A"

        p1_lines = [
            f"[bold bright_white]{total_snapshots:,}[/] snapshots",
            f"[dim]spanning {span_str}[/]",
        ]
        panels.append(
            Panel(
                "\n".join(p1_lines),
                title="[bold]Data Volume[/bold]",
                border_style="blue",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

        # Panel 2: Account & provider summary
        if history_data:
            accounts = set(r["account_email"] for r in history_data)
            providers = set(r["provider_type"] for r in history_data)
            quotas = set(r["quota_name"] for r in history_data)
        else:
            accounts, providers, quotas = set(), set(), set()

        p2_lines = [
            f"[cyan]{len(accounts)}[/] accounts",
            f"[magenta]{len(providers)}[/] providers",
            f"[green]{len(quotas)}[/] quotas tracked",
        ]
        panels.append(
            Panel(
                "\n".join(p2_lines),
                title="[bold]Coverage[/bold]",
                border_style="magenta",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

        # Panel 3: Health overview from aggregation
        if aggregation_data:
            pcts = [
                a["avg_remaining"]
                for a in aggregation_data
                if a.get("avg_remaining") is not None
            ]
            if pcts:
                overall_avg = sum(pcts) / len(pcts)
                critical = sum(1 for p in pcts if p < 20)
                warning = sum(1 for p in pcts if 20 <= p < 50)
                healthy = sum(1 for p in pcts if p >= 50)
                avg_color = self._get_pct_color(overall_avg)

                p3_lines = [
                    f"[{avg_color}]{overall_avg:.1f}%[/] avg remaining",
                    f"[green]{healthy}[/] healthy  [yellow]{warning}[/] warning  [red]{critical}[/] critical",
                ]
            else:
                p3_lines = ["[dim]No percentage data[/dim]"]
        else:
            p3_lines = ["[dim]No aggregation data[/dim]"]

        panels.append(
            Panel(
                "\n".join(p3_lines),
                title="[bold]Health[/bold]",
                border_style="green",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

        self.console.print(Columns(panels, equal=True, expand=True))

        # --- Aggregation detail table ---
        if aggregation_data:
            self.console.print()
            agg_table = Table(
                title="Per-Quota Statistics",
                title_style="bold blue",
                show_header=True,
                header_style="bold bright_white",
                box=box.SIMPLE_HEAVY,
                border_style="blue",
                row_styles=["", "dim"],
            )
            agg_table.add_column("Account", style="cyan", no_wrap=True)
            agg_table.add_column("Provider", style="magenta", no_wrap=True)
            agg_table.add_column("Quota", style="white")
            agg_table.add_column("Avg %", justify="right", no_wrap=True)
            agg_table.add_column("Min %", justify="right", no_wrap=True)
            agg_table.add_column("Max %", justify="right", no_wrap=True)
            agg_table.add_column("Volatility", no_wrap=True)
            agg_table.add_column("Samples", justify="right", style="dim", no_wrap=True)

            for agg in aggregation_data:
                avg_r = agg.get("avg_remaining")
                min_r = agg.get("min_remaining")
                max_r = agg.get("max_remaining")
                points = agg.get("data_points", 0)
                display_name = agg.get("display_name") or agg["quota_name"]

                if avg_r is not None:
                    avg_color = self._get_pct_color(avg_r)
                    avg_str = f"[{avg_color}]{avg_r:.1f}%[/]"
                else:
                    avg_str = "[dim]N/A[/dim]"

                if min_r is not None:
                    min_color = self._get_pct_color(min_r)
                    min_str = f"[{min_color}]{min_r:.1f}%[/]"
                else:
                    min_str = "[dim]N/A[/dim]"

                if max_r is not None:
                    max_color = self._get_pct_color(max_r)
                    max_str = f"[{max_color}]{max_r:.1f}%[/]"
                else:
                    max_str = "[dim]N/A[/dim]"

                # Volatility indicator (range / average)
                if min_r is not None and max_r is not None and avg_r and avg_r > 0:
                    volatility = (max_r - min_r) / avg_r * 100
                    if volatility < 5:
                        vol_str = "[green]low[/]"
                    elif volatility < 20:
                        vol_str = "[yellow]moderate[/]"
                    else:
                        vol_str = "[red]high[/]"
                    vol_str += f" [dim]({max_r - min_r:.0f}pp)[/dim]"
                else:
                    vol_str = "[dim]--[/dim]"

                email = agg["account_email"]
                short_email = email.split("@")[0] if "@" in email else email

                agg_table.add_row(
                    short_email,
                    agg["provider_type"],
                    display_name,
                    avg_str,
                    min_str,
                    max_str,
                    vol_str,
                    str(points),
                )

            self.console.print(agg_table)

        # --- Weekly activity sparkline summary ---
        if weekly_data and weekly_data.get("daily_totals"):
            self.console.print()
            daily_totals = weekly_data["daily_totals"]

            total_credits = sum(d.get("total_used", 0) or 0 for d in daily_totals)
            active_days = sum(
                1 for d in daily_totals if (d.get("total_used", 0) or 0) > 0
            )

            credits_str = (
                f"[yellow]{total_credits:,.0f}[/]"
                if total_credits > 0
                else "[dim]0[/dim]"
            )
            days_str = f"[cyan]{active_days}[/]/{len(daily_totals)}"

            self.console.print(
                f"  [dim]7-Day Summary:[/dim] {credits_str} [dim]total credits  |  {days_str} active days[/dim]"
            )

        self.console.print()


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
