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

        if query:
            queries = [query] if isinstance(query, str) else query
            for q_str in queries:
                q_lower = q_str.lower()
                filtered_quotas = [
                    q
                    for q in filtered_quotas
                    if q_lower in q.get("name", "").lower()
                    or q_lower in q.get("display_name", "").lower()
                ]

        if not filtered_quotas:
            if not quotas:
                self.console.print(
                    "[yellow]No active quota information found.[/yellow]"
                )
            elif not show_all:
                self.console.print(
                    "[dim]No premium models found (use --show-all to see all models).[/dim]"
                )
            else:
                self.console.print(
                    "[yellow]No active quota information found.[/yellow]"
                )
            return

        # Sort filtered quotas using provider logic via client
        if client:
            filtered_quotas.sort(key=lambda q: client.get_sort_key(q))

        if compact:
            self._draw_compact(filtered_quotas, client, account_name)
        else:
            self._draw_normal(filtered_quotas, client)

    def _get_reset_string(self, reset_info, remaining_pct):
        if reset_info != "Unknown" and remaining_pct < 100:

            def format_diff(delta):
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

            if isinstance(reset_info, str) and "T" in reset_info and "Z" in reset_info:
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(reset_info.replace("Z", "+00:00"))
                    now = datetime.now(dt.tzinfo)
                    return format_diff(dt - now)
                except Exception:
                    pass
            elif isinstance(reset_info, (int, float)):
                try:
                    from datetime import datetime, timezone

                    dt = datetime.fromtimestamp(
                        reset_info / 1000 if reset_info > 1e11 else reset_info,
                        tz=timezone.utc,
                    )
                    now = datetime.now(timezone.utc)
                    return format_diff(dt - now)
                except Exception:
                    pass
        return ""

    def _draw_compact(self, filtered_quotas, client, account_name):
        if not filtered_quotas:
            return

        short_indicator = client.short_indicator if client else "?"
        provider_color = client.primary_color if client else "white"
        prefix = f"[{provider_color}]{short_indicator}[/] {account_name}: "

        reserved_width = len(prefix) + 30
        terminal_width = self.console.width
        bar_width = max(5, min(30, terminal_width - reserved_width))

        for q in filtered_quotas:
            name = q.get("display_name", q.get("name"))
            remaining_pct = q.get("remaining_pct", 100)

            if q.get("is_error"):
                message = q.get("message", "Error")
                self.console.print(f"{prefix}[red]{name}: {message}[/red]")
                continue

            if remaining_pct <= 20:
                bar_color = "red"
            elif remaining_pct <= 50:
                bar_color = "yellow"
            else:
                bar_color = "green"

            total_filled = (remaining_pct / 100) * bar_width
            filled_whole = int(total_filled)
            bar = (
                f"[{bar_color}]"
                + "█" * filled_whole
                + "[/]"
                + " " * (bar_width - filled_whole)
            )

            reset_info = q.get("reset") or "Unknown"
            reset_str = self._get_reset_string(reset_info, remaining_pct)

            self.console.print(
                f"{prefix}{name[:18]:18} {bar} {remaining_pct:5.1f}%{reset_str}"
            )

    def _draw_normal(self, filtered_quotas, client):
        reserved_width = 45
        terminal_width = self.console.width
        bar_width = max(10, min(60, terminal_width - reserved_width))

        for q in filtered_quotas:
            name = q.get("display_name", q.get("name"))
            remaining_pct = q.get("remaining_pct", 100)

            name_color = client.get_color(q) if client else "white"
            padded_name = f"{name:22}"
            styled_name = f"[{name_color}]{padded_name}[/]"

            if q.get("is_error"):
                message = q.get("message", "Validation Required")
                url = q.get("url", "")
                if url:
                    self.console.print(
                        f"{styled_name} [red]⚠️ {message}[/red] [link={url}][dim]-> Click here to verify <-[/dim][/link]"
                    )
                else:
                    self.console.print(f"{styled_name} [red]⚠️ {message}[/red]")
                continue

            if remaining_pct <= 20:
                bar_color = "red"
            elif remaining_pct <= 50:
                bar_color = "yellow"
            else:
                bar_color = "green"

            total_filled = (remaining_pct / 100) * bar_width
            filled_whole = int(total_filled)
            remainder = total_filled - filled_whole

            blocks = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
            fraction_block = blocks[int(remainder * 8)]

            if filled_whole >= bar_width:
                bar = f"[{bar_color}]" + "█" * bar_width + "[/]"
            else:
                bar = f"[{bar_color}]" + "█" * filled_whole
                if fraction_block != " ":
                    bar += fraction_block
                bar += "[/]"
                used_width = filled_whole + (1 if fraction_block != " " else 0)
                bar += " " * (bar_width - used_width)

            reset_info = q.get("reset") or "Unknown"
            reset_str = self._get_reset_string(reset_info, remaining_pct)

            self.console.print(f"{styled_name} {bar} {remaining_pct:5.1f}%{reset_str}")
