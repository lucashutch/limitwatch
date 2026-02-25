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

            bar_color = get_bar_color(shown_pct, is_used)
            bar = render_compact_bar(shown_pct, bar_width, bar_color)
            reset_str = get_reset_string(q.get("reset") or "Unknown", remaining_pct)
            suffix = f"{shown_pct:5.1f}% used" if is_used else f"{shown_pct:5.1f}%"
            self.console.print(f"{prefix}{name[:18]:18} {bar} {suffix}{reset_str}")

    def _draw_normal(self, filtered_quotas, client):
        reserved_width = 45
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
