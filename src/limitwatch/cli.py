import json
import sys
import click
import logging
import time
import concurrent.futures
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
from .config import Config
from .auth import AuthManager
from .quota_client import QuotaClient
from .display import DisplayManager
from .history import HistoryManager
from .export import Exporter

logger = logging.getLogger(__name__)

try:
    __version__ = version("limitwatch")
except PackageNotFoundError:
    __version__ = "unknown"


# --- Helper functions extracted from main() ---


def fetch_account_data(idx, acc_data, auth_mgr, show_all):
    """Fetch quota data for a single account. Returns (email, quotas, client, error)."""
    email = acc_data.get("email", f"Account {idx}")
    account_type = acc_data.get("type", "google")
    start = time.perf_counter()
    logger.debug(
        f"[cli] fetch_account_data start account={email} provider={account_type}"
    )

    creds = None
    if account_type == "google":
        creds = auth_mgr.get_credentials(idx)
        if not creds:
            return email, None, None, f"Could not load credentials for {email}"
        try:
            auth_mgr.refresh_credentials(creds)
        except Exception as e:
            return email, None, None, f"Token refresh failed: {e}"

    try:
        client = QuotaClient(acc_data, credentials=creds)
        quotas = client.fetch_quotas()
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[cli] fetch_account_data done account={email} provider={account_type} "
            f"elapsed_ms={elapsed_ms:.1f} quota_count={len(quotas or [])}"
        )
        return email, quotas, client, None
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[cli] fetch_account_data error account={email} provider={account_type} "
            f"elapsed_ms={elapsed_ms:.1f} err={e}"
        )
        return email, None, None, str(e)


def _output_json(data):
    """Print a JSON-serializable object to stdout."""
    print(json.dumps(data, indent=2))


def _output_json_msg(status, **kwargs):
    """Print a simple JSON status message."""
    print(json.dumps({"status": status, **kwargs}))


def _handle_login(display, auth_mgr, json_output, provider):
    """Handle the --login flow. Returns early from main()."""
    try:
        if not json_output:
            account_data = _interactive_login(display)
        else:
            account_data = _non_interactive_login(provider)

        email = auth_mgr.login(account_data)

        if json_output:
            _output_json_msg("success", email=email)
        else:
            display.console.print(
                f"[green]Successfully logged in as [bold]{email}[/bold][/green]"
            )
    except Exception as e:
        if json_output:
            _output_json_msg("error", message=str(e))
        else:
            display.console.print(f"[red]Login failed:[/red] {e}")


def _interactive_login(display):
    """Run the interactive provider selection and login flow."""
    display.console.print("[bold blue]Select Provider:[/bold blue]")
    providers = QuotaClient.get_available_providers()
    for i, (p_type, p_name) in enumerate(providers.items(), 1):
        display.console.print(f"{i}) {p_name}")

    choice = click.prompt("Enter choice", type=int, default=1)
    provider_type = list(providers.keys())[choice - 1]

    client = QuotaClient(account_data={"type": provider_type})
    return client.provider.interactive_login(display)


def _non_interactive_login(provider):
    """Run the non-interactive login flow for JSON/scripted usage."""
    p_type = (
        provider
        if provider in ["google", "chutes", "github_copilot", "openai", "openrouter"]
        else "google"
    )
    client = QuotaClient(account_data={"type": p_type})
    return client.provider.login()


def _interactive_logout(display, auth_mgr):
    """Interactive logout flow: pick provider → pick account → confirm."""
    accounts = auth_mgr.accounts
    if not accounts:
        display.console.print("[yellow]No accounts found to log out from.[/yellow]")
        return

    # Step 1: Provider selection — only show providers that have accounts
    all_providers = QuotaClient.get_available_providers()
    present_types = {a.get("type") for a in accounts}
    available_providers = {k: v for k, v in all_providers.items() if k in present_types}

    display.console.print("[bold blue]Select Provider to log out from:[/bold blue]")
    p_types = list(available_providers.keys())
    for i, p_type in enumerate(p_types, 1):
        count = sum(1 for a in accounts if a.get("type") == p_type)
        display.console.print(
            f"{i}) {available_providers[p_type]} "
            f"({count} account{'s' if count > 1 else ''})"
        )

    choice = click.prompt("Enter choice", type=int, default=1)
    if choice < 1 or choice > len(p_types):
        display.console.print("[red]Invalid choice.[/red]")
        return
    chosen_type = p_types[choice - 1]

    # Step 2: Account selection
    provider_accounts = [a for a in accounts if a.get("type") == chosen_type]
    if len(provider_accounts) == 1:
        chosen_account = provider_accounts[0]
    else:
        display.console.print("[bold blue]Select Account to log out:[/bold blue]")
        for i, acc in enumerate(provider_accounts, 1):
            label = acc.get("alias") or acc.get("email", f"Account {i}")
            display.console.print(f"{i}) {label}")
        acc_choice = click.prompt("Enter choice", type=int, default=1)
        if acc_choice < 1 or acc_choice > len(provider_accounts):
            display.console.print("[red]Invalid choice.[/red]")
            return
        chosen_account = provider_accounts[acc_choice - 1]

    # Step 3: Confirmation
    email = chosen_account.get("email", "")
    alias = chosen_account.get("alias", "")
    label = alias or email
    if not click.confirm(f"Log out {label}?", default=False):
        display.console.print("[yellow]Logout cancelled.[/yellow]")
        return

    # Step 4: Execute
    auth_mgr.logout(email)
    display.console.print(
        f"[green]Successfully logged out [bold]{label}[/bold][/green]"
    )


def _handle_logout_all(display, auth_mgr, json_output):
    """Handle the --logout-all flow."""
    if not json_output:
        count = len(auth_mgr.accounts)
        if count == 0:
            display.console.print("[yellow]No accounts to log out from.[/yellow]")
            return
        if not click.confirm(
            f"Log out from all {count} account{'s' if count > 1 else ''}?",
            default=False,
        ):
            display.console.print("[yellow]Logout cancelled.[/yellow]")
            return
    auth_mgr.logout_all()
    if json_output:
        _output_json_msg("success")
    else:
        display.console.print(
            "[green]Successfully logged out from all accounts.[/green]"
        )


def _handle_metadata_update(
    display, auth_mgr, accounts, account, alias, group, project_id, json_output
):
    """Handle updating account metadata (alias, group, project-id)."""
    target_accounts = [
        a for a in accounts if a.get("email") == account or a.get("alias") == account
    ]
    if not target_accounts:
        if not json_output:
            display.console.print(
                f"[red]Error:[/red] Account [bold]{account}[/bold] not found."
            )
        return

    for target_acc in target_accounts:
        email_to_update = target_acc.get("email")
        metadata = {}
        if alias is not None:
            metadata["alias"] = alias
        if group is not None:
            metadata["group"] = group
        if project_id is not None:
            metadata["projectId"] = project_id
            metadata["managedProjectId"] = project_id

        if auth_mgr.update_account_metadata(email_to_update, metadata):
            if not json_output:
                display.console.print(
                    f"[green]Updated metadata for [bold]{email_to_update}[/bold][/green]"
                )


def _filter_accounts(accounts, account, provider, group):
    """Filter the accounts list based on CLI flags. Returns list of (index, account_data)."""
    indices = []
    for i, a in enumerate(accounts):
        if account and a.get("email") != account and a.get("alias") != account:
            continue
        if provider and a.get("type", "google") != provider:
            continue
        if group and not account and a.get("group") != group:
            continue
        indices.append((i, a))
    return indices


def _fetch_all_quotas(indices_to_check, auth_mgr, show_all, display, json_output):
    """Fetch quotas for all accounts concurrently. Returns {idx: (email, quotas, client, error)}."""
    idx_to_result = {}
    max_workers = min(len(indices_to_check), 10)

    def run_executor():
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(
                    fetch_account_data, idx, acc_data, auth_mgr, show_all
                ): idx
                for idx, acc_data in indices_to_check
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                idx_to_result[idx] = future.result()

    if not json_output:
        with display.console.status("[bold blue]Fetching quotas for all accounts..."):
            run_executor()
    else:
        run_executor()

    return idx_to_result


def _render_account_quotas(
    display, acc_data, email, quotas, client, error, query, show_all, compact
):
    """Render quotas for a single account in the terminal. Returns True if query matched."""
    alias = acc_data.get("alias", "")
    group_val = acc_data.get("group", "")
    provider_name = client.provider.provider_name if client else ""
    account_name = alias or email

    if error:
        if not query:
            _render_error(
                display, email, provider_name, alias, group_val, error, client, compact
            )
        return False

    filtered_quotas = display.filter_quotas(quotas, client=client, show_all=show_all)
    if query:
        filtered_quotas = _apply_cli_query(filtered_quotas, query)

    has_matches = bool(filtered_quotas)

    if not filtered_quotas and query:
        return False

    # Show account header for both compact and non-compact modes
    display.print_account_header(
        email, provider=provider_name, alias=alias, group=group_val
    )

    display.draw_quota_bars(
        quotas,
        client=client,
        show_all=show_all,
        query=query,
        compact=compact,
        account_name=account_name,
    )

    if not compact:
        display.console.print("━" * 50)

    return has_matches


def _render_error(
    display, email, provider_name, alias, group_val, error, client, compact
):
    """Render an error message for an account."""
    if compact:
        short_indicator = client.provider.short_indicator if client else "?"
        color = client.provider.primary_color if client else "white"
        display.console.print(
            f"[{color}]{short_indicator}[/] {alias or email}: [yellow]Warning:[/yellow] {error}"
        )
    else:
        display.print_account_header(
            email, provider=provider_name, alias=alias, group=group_val
        )
        display.console.print(f"[yellow]Warning:[/yellow] {error}")
        display.console.print("━" * 50)


def _apply_cli_query(quotas, query):
    """Apply the CLI --query filter to a list of quota dicts."""
    if not query:
        return quotas
    for q_str in query:
        q_lower = q_str.lower()
        quotas = [
            q
            for q in quotas
            if q_lower in q.get("name", "").lower()
            or q_lower in q.get("display_name", "").lower()
        ]
    return quotas


def _build_json_results(indices_to_check, idx_to_result, display, show_all, query):
    """Build the JSON output structure for all accounts."""
    results = []
    any_query_matches = False

    for idx, acc_data in indices_to_check:
        email, quotas, client, error = idx_to_result[idx]
        alias = acc_data.get("alias", "")
        group_val = acc_data.get("group", "")

        filtered_quotas = display.filter_quotas(
            quotas, client=client, show_all=show_all
        )
        if query:
            filtered_quotas = _apply_cli_query(filtered_quotas, query)
            if filtered_quotas:
                any_query_matches = True

        results.append(
            {
                "email": email,
                "alias": alias,
                "group": group_val,
                "quotas": filtered_quotas,
                "error": error,
            }
        )

    return results, any_query_matches


# --- Main CLI group ---


@click.group(
    context_settings=dict(help_option_names=["-h", "--help"]),
    invoke_without_command=True,
)
@click.version_option(__version__, "--version", "-v", prog_name="limitwatch")
@click.pass_context
def cli(ctx):
    """Monitor API quota usage and reset times across all accounts."""
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        ctx.invoke(show)


@cli.command(name="show")
@click.option("-a", "--account", help="Email of the account to check.")
@click.option("--alias", help="Set an alias for an account (requires --account).")
@click.option(
    "-g",
    "--group",
    help="Filter by group or set a group for an account (setting requires --account).",
)
@click.option("-p", "--provider", help="Filter by provider (e.g., google, chutes).")
@click.option(
    "-q",
    "--query",
    multiple=True,
    help="Filter models by name (case-insensitive). Can be specified multiple times for an AND match.",
)
@click.option("-r", "--refresh", is_flag=True, help="Force refresh of OAuth tokens.")
@click.option(
    "-s", "--show-all", is_flag=True, help="Show all models including Gemini 2.0/2.5."
)
@click.option(
    "-c", "--compact", is_flag=True, help="Enable compact one-line-per-quota view."
)
@click.option(
    "-j", "--json", "json_output", is_flag=True, help="Output results as JSON."
)
@click.option("-l", "--login", is_flag=True, help="Login to a new account.")
@click.option(
    "--project-id", help="Manually specify a Google Cloud Project ID for an account."
)
@click.option(
    "--logout", is_flag=True, help="Log out from a saved account interactively."
)
@click.option("--logout-all", is_flag=True, help="Logout from all accounts.")
@click.option(
    "--no-record", is_flag=True, help="Skip recording quota data to history database."
)
@click.option("--verbose", is_flag=True, help="Enable verbose logging.")
def show(
    account,
    alias,
    group,
    provider,
    query,
    refresh,
    show_all,
    compact,
    json_output,
    login,
    project_id,
    logout,
    logout_all,
    no_record,
    verbose,
):
    """Show current quota status for all accounts."""
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(message)s", datefmt="[%X]")

    config = Config()
    display = DisplayManager()
    auth_mgr = AuthManager(config.auth_path)

    # --- Auth actions (login / logout) ---
    if login:
        _handle_login(display, auth_mgr, json_output, provider)
        return

    if logout:
        _interactive_logout(display, auth_mgr)
        return

    if logout_all:
        _handle_logout_all(display, auth_mgr, json_output)
        return

    # --- Load accounts ---
    if not config.auth_path.exists():
        if json_output:
            _output_json_msg("error", message="Accounts file not found")
        else:
            display.console.print(
                f"[red]Error:[/red] Accounts file not found at [bold]{config.auth_path}[/bold]"
            )
            display.console.print(
                "Please login with [bold]--login[/bold] to authenticate."
            )
        return

    try:
        accounts = auth_mgr.load_accounts()
        if not accounts:
            if json_output:
                _output_json_msg("error", message="No accounts found")
            else:
                display.console.print("[red]Error:[/red] No accounts found in file.")
            return

        # --- Metadata update ---
        if account and (
            alias is not None or group is not None or project_id is not None
        ):
            _handle_metadata_update(
                display,
                auth_mgr,
                accounts,
                account,
                alias,
                group,
                project_id,
                json_output,
            )
            return

        # --- Filter & fetch ---
        indices_to_check = _filter_accounts(accounts, account, provider, group)

        if not indices_to_check:
            if json_output:
                _output_json_msg("error", message="No accounts found")
            elif account:
                display.console.print(
                    f"[red]Error:[/red] Account [bold]{account}[/bold] not found."
                )
            else:
                display.console.print("[red]Error:[/red] No accounts matching filters.")
            return

        if not json_output and not query and not compact:
            display.print_main_header()

        idx_to_result = _fetch_all_quotas(
            indices_to_check, auth_mgr, show_all, display, json_output
        )

        # --- Record to history database ---
        if not no_record and config.history_enabled:
            try:
                history_mgr = HistoryManager(config.history_db_path)
                for idx, acc_data in indices_to_check:
                    email, quotas, client, error = idx_to_result[idx]
                    if quotas and not error and client:
                        account_type = acc_data.get("type", "unknown")
                        history_mgr.record_quotas(email, account_type, quotas)
                        logger.debug(f"Recorded quotas to history for {email}")
            except Exception as e:
                logger.warning(f"Failed to record quota history: {e}")

        # --- Render output ---
        if json_output:
            results, any_query_matches = _build_json_results(
                indices_to_check, idx_to_result, display, show_all, query
            )
            _output_json(results)
        else:
            any_query_matches = False
            for idx, acc_data in indices_to_check:
                email, quotas, client, error = idx_to_result[idx]
                matched = _render_account_quotas(
                    display,
                    acc_data,
                    email,
                    quotas,
                    client,
                    error,
                    query,
                    show_all,
                    compact,
                )
                if matched:
                    any_query_matches = True

        if query and not any_query_matches:
            sys.exit(1)

    except Exception as e:
        display.console.print(f"[red]Error:[/red] {e}")


@cli.command(name="history")
@click.option(
    "--preset",
    type=click.Choice(["24h", "7d", "30d", "90d"]),
    help="Time range preset (default: 24h)",
)
@click.option("--since", help="Start time (ISO format or relative like '7d', '24h')")
@click.option("--until", help="End time (ISO format)")
@click.option("-a", "--account", help="Filter by account email")
@click.option("-p", "--provider", help="Filter by provider type")
@click.option("-q", "--quota", help="Filter by quota name")
@click.option(
    "--table", is_flag=True, help="Show time-series table instead of sparklines"
)
@click.option("--summary", is_flag=True, help="Show database summary instead of data")
@click.option(
    "--heatmap",
    "view_type",
    flag_value="heatmap",
    help="Show activity heatmap (days × accounts)",
)
@click.option(
    "--chart",
    "view_type",
    flag_value="chart",
    help="Show ASCII line chart of quota remaining %",
)
@click.option(
    "--calendar", "view_type", flag_value="calendar", help="Show weekly calendar view"
)
@click.option(
    "--bars", "view_type", flag_value="bars", help="Show daily credit consumption bars"
)
@click.option(
    "--stats",
    "view_type",
    flag_value="stats",
    help="Show comprehensive statistics dashboard",
)
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
def history_command(
    preset, since, until, account, provider, quota, table, summary, view_type, verbose
):
    """View historical quota data."""
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(message)s", datefmt="[%X]")

    config = Config()
    display = DisplayManager()
    history_mgr = HistoryManager(config.history_db_path)

    if summary:
        info = history_mgr.get_database_info()
        display.print_history_summary(info)
        return

    if view_type in ("heatmap", "chart", "calendar", "bars", "stats"):
        try:
            weekly_data = history_mgr.get_weekly_activity(
                account_email=account,
                provider_type=provider,
            )

            if view_type == "heatmap":
                display.render_activity_heatmap(weekly_data)
            elif view_type == "chart":
                display.render_ascii_chart(weekly_data)
            elif view_type == "calendar":
                display.render_calendar_view(weekly_data)
            elif view_type == "bars":
                display.render_daily_bars(weekly_data)
            elif view_type == "stats":
                # Fetch additional data needed for the stats dashboard
                effective_preset = preset or "7d"
                history_data = history_mgr.get_history(
                    preset=effective_preset,
                    since=since,
                    until=until,
                    account_email=account,
                    provider_type=provider,
                    quota_name=quota,
                )
                aggregation_data = history_mgr.get_aggregation(
                    preset=effective_preset,
                    since=since,
                    until=until,
                    account_email=account,
                    provider_type=provider,
                )
                display.render_stats_dashboard(
                    history_data, weekly_data, aggregation_data
                )

        except Exception as e:
            display.console.print(f"[red]Error:[/red] {e}")
        return

    # Default to 24h if no time range specified
    if not preset and not since:
        preset = "24h"

    try:
        history_data = history_mgr.get_history(
            preset=preset,
            since=since,
            until=until,
            account_email=account,
            provider_type=provider,
            quota_name=quota,
        )

        if table:
            display.render_history_table(history_data)
        else:
            display.render_history_sparklines(history_data)

    except Exception as e:
        display.console.print(f"[red]Error:[/red] {e}")


@cli.command(name="export")
@click.option(
    "--format",
    "export_format",
    type=click.Choice(["csv", "markdown"]),
    default="csv",
    help="Export format (default: csv)",
)
@click.option("-o", "--output", help="Output file path (default: stdout)")
@click.option(
    "--preset",
    type=click.Choice(["24h", "7d", "30d", "90d"]),
    help="Time range preset",
)
@click.option("--since", help="Start time (ISO format or relative like '7d', '24h')")
@click.option("--until", help="End time (ISO format)")
@click.option("-a", "--account", help="Filter by account email")
@click.option("-p", "--provider", help="Filter by provider type")
@click.option("-q", "--quota", help="Filter by quota name")
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
def export_command(
    export_format, output, preset, since, until, account, provider, quota, verbose
):
    """Export historical quota data to CSV or Markdown."""
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(message)s", datefmt="[%X]")

    config = Config()
    exporter = Exporter(HistoryManager(config.history_db_path))

    # Default to 7d if no time range specified
    if not preset and not since:
        preset = "7d"

    try:
        if export_format == "csv":
            result = exporter.export_csv(
                output_path=Path(output) if output else None,
                preset=preset,
                since=since,
                until=until,
                account_email=account,
                provider_type=provider,
                quota_name=quota,
            )
            if not output:
                print(result)
        elif export_format == "markdown":
            result = exporter.export_markdown(
                output_path=Path(output) if output else None,
                preset=preset,
                since=since,
                until=until,
                account_email=account,
                provider_type=provider,
                quota_name=quota,
            )
            if not output:
                print(result)

        if output:
            click.echo(f"Exported to {output}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)


# Default command is "show"
cli.add_command(show, name="")


# Export the CLI group as 'main' for backward compatibility with tests
main = cli


def cli_entry_point():
    """Entry point for the CLI (used by setup.py/pyproject.toml)."""
    cli()
