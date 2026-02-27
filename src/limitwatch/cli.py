import json
import sys
import click
import logging
import time
import concurrent.futures
from importlib.metadata import version, PackageNotFoundError
from .config import Config
from .auth import AuthManager
from .quota_client import QuotaClient
from .display import DisplayManager

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
        if provider in ["google", "chutes", "github_copilot", "openai"]
        else "google"
    )
    client = QuotaClient(account_data={"type": p_type})
    return client.provider.login()


def _handle_logout(display, auth_mgr, email, json_output):
    """Handle the --logout flow."""
    success = auth_mgr.logout(email)
    if json_output:
        _output_json_msg("success" if success else "not_found")
    elif success:
        display.console.print(
            f"[green]Successfully logged out [bold]{email}[/bold][/green]"
        )
    else:
        display.console.print(
            f"[yellow]Account [bold]{email}[/bold] not found.[/yellow]"
        )


def _handle_logout_all(display, auth_mgr, json_output):
    """Handle the --logout-all flow."""
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


# --- Main CLI entrypoint ---


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(__version__, "--version", "-v", prog_name="limitwatch")
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
@click.option("--logout", help="Logout from a specific account.")
@click.option("--logout-all", is_flag=True, help="Logout from all accounts.")
@click.option("--verbose", is_flag=True, help="Enable verbose logging.")
def main(
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
    verbose,
):
    """Monitor API quota usage and reset times across all accounts."""
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
        _handle_logout(display, auth_mgr, logout, json_output)
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


if __name__ == "__main__":
    main()
