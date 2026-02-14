from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.table import Table
from rich import box


class DisplayManager:
    def __init__(self):
        self.console = Console()

    def print_main_header(self):
        self.console.print(f"\n[bold blue]Gemini CLI Quota Status[/bold blue]")

    def print_account_header(self, email: str):
        self.console.print(f"[dim]📧 Account: {email}[/dim]")

    def filter_quotas(self, quotas, show_all=False):
        if not quotas:
            return []

        if show_all:
            filtered = quotas
        else:
            # Smart filtering:
            # Identify if "premium" (Gemini 3 or Claude) models exist for each source
            has_premium_cli = any(
                (
                    "3" in q.get("display_name", "")
                    or "Claude" in q.get("display_name", "")
                )
                and q.get("source_type") == "Gemini CLI"
                for q in quotas
            )
            has_premium_ag = any(
                (
                    "3" in q.get("display_name", "")
                    or "Claude" in q.get("display_name", "")
                )
                and q.get("source_type") == "Antigravity"
                for q in quotas
            )

            filtered = []
            for q in quotas:
                name = q.get("display_name", "")
                source = q.get("source_type", "")

                # Always hide 2.0 Flash in the verbose list (only show if show_all is True)
                if "2.0" in name:
                    continue

                is_premium = "3" in name or "Claude" in name

                if is_premium:
                    filtered.append(q)
                elif source == "Gemini CLI" and not has_premium_cli:
                    # If no Gemini 3/Claude exists for CLI, show the 2.5/1.5 models
                    filtered.append(q)
                elif source == "Antigravity" and not has_premium_ag:
                    # Same for Antigravity
                    filtered.append(q)

        # Custom sorting order
        def sort_key(q):
            source = q.get("source_type", "")
            name = q.get("display_name", "")

            # Source priority: CLI first, then AG
            source_prio = 0 if source == "Gemini CLI" else 1

            # Family priority
            family_prio = 99
            if "Gemini 2.0 Flash" in name:
                family_prio = 0
            elif "Gemini 2.5 Flash" in name:
                family_prio = 1
            elif "Gemini 2.5 Pro" in name:
                family_prio = 2
            elif "Gemini 3 Flash" in name:
                family_prio = 3
            elif "Gemini 3 Pro" in name:
                family_prio = 4
            elif "Claude" in name:
                family_prio = 5

            return source_prio, family_prio, name

        filtered.sort(key=sort_key)
        return filtered

    def draw_quota_bars(self, quotas, show_all=False):
        filtered_quotas = self.filter_quotas(quotas, show_all=show_all)

        if not filtered_quotas:
            if not quotas:
                self.console.print(
                    "[yellow]No active quota information found.[/yellow]"
                )
            elif not show_all:
                self.console.print(
                    "[dim]No premium models found (use --show-all to see Gemini 2.0/2.5).[/dim]"
                )
            else:
                self.console.print(
                    "[yellow]No active quota information found.[/yellow]"
                )
            return

        for q in filtered_quotas:
            name = q.get("display_name", q.get("name"))
            source = q.get("source_type", "")
            remaining_pct = q.get("remaining_pct", 100)

            # Determine name color based on source
            name_color = "cyan" if source == "Gemini CLI" else "magenta"
            # Pad the name first to ensure consistent alignment, then add color tags
            padded_name = f"{name:25}"
            styled_name = f"[{name_color}]{padded_name}[/]"

            # Determine bar color based on REMAINING amount
            if remaining_pct <= 20:
                bar_color = "red"
            elif remaining_pct <= 50:
                bar_color = "yellow"
            else:
                bar_color = "green"

            # Progress bar representation (smooth blocks like pytest-sugar)
            bar_width = 40
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

                # Pad with spaces to maintain alignment
                used_width = filled_whole + (1 if fraction_block != " " else 0)
                bar += " " * (bar_width - used_width)

            reset_info = q.get("reset") or "Unknown"

            # Clean up ISO timestamp if possible
            reset_str = ""
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

                if (
                    isinstance(reset_info, str)
                    and "T" in reset_info
                    and "Z" in reset_info
                ):
                    try:
                        from datetime import datetime

                        dt = datetime.fromisoformat(reset_info.replace("Z", "+00:00"))
                        now = datetime.now(dt.tzinfo)
                        reset_str = format_diff(dt - now)
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
                        reset_str = format_diff(dt - now)
                    except Exception:
                        pass

            self.console.print(f"{styled_name} {bar} {remaining_pct:5.1f}%{reset_str}")
