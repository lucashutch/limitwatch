import json
import click
import logging
import concurrent.futures
from .config import Config
from .auth import AuthManager
from .quota_client import QuotaClient
from .display import DisplayManager


def fetch_account_data(idx, acc_data, auth_mgr, show_all):
    email = acc_data.get("email", f"Account {idx}")
    account_type = acc_data.get("type", "google")

    creds = None
    if account_type == "google":
        creds = auth_mgr.get_credentials(idx)
        if not creds:
            return email, None, f"Could not load credentials for {email}"
        try:
            # Refresh token
            auth_mgr.refresh_credentials(creds)
        except Exception as e:
            return email, None, f"Token refresh failed: {e}"

    try:
        # Initialize Client with account data and credentials
        client = QuotaClient(acc_data, credentials=creds)
        quotas = client.fetch_quotas()

        if not quotas:
            # Fallback to cachedQuota if API call failed or returned empty
            cached = acc_data.get("cachedQuota", {})
            if cached:
                # Mapping from cached keys to display names
                family_map = {
                    "gemini-pro": "Gemini 3 Pro (AG)",
                    "gemini-flash": "Gemini 3 Flash (AG)",
                    "claude": "Claude (AG)",
                    "gemini-2.5-flash": "Gemini 2.5 Flash (AG)",
                    "gemini-2.5-pro": "Gemini 2.5 Pro (AG)",
                }
                for family, q_data in cached.items():
                    display_name = family_map.get(
                        family, f"{family.replace('-', ' ').title()} (AG)"
                    )
                    quotas.append(
                        {
                            "name": family,
                            "display_name": display_name,
                            "remaining_pct": q_data.get("remainingFraction", 1.0) * 100,
                            "reset": q_data.get("resetTime", "Unknown"),
                            "source_type": "Antigravity",
                        }
                    )

        return email, quotas, None
    except Exception as e:
        return email, None, str(e)


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option("0.0.2", "--version", "-v", prog_name="gemini-quota")
@click.option("-a", "--account", help="Email of the account to check.")
@click.option("-r", "--refresh", is_flag=True, help="Force refresh of OAuth tokens.")
@click.option(
    "-s", "--show-all", is_flag=True, help="Show all models including Gemini 2.0/2.5."
)
@click.option(
    "-j", "--json", "json_output", is_flag=True, help="Output results as JSON."
)
@click.option("-l", "--login", is_flag=True, help="Login to a new account.")
@click.option(
    "-p",
    "--project-id",
    help="Manually specify a Google Cloud Project ID for an account.",
)
@click.option("--logout", help="Logout from a specific account.")
@click.option("--logout-all", is_flag=True, help="Logout from all accounts.")
@click.option("--verbose", is_flag=True, help="Enable verbose logging.")
def main(
    account,
    refresh,
    show_all,
    json_output,
    login,
    project_id,
    logout,
    logout_all,
    verbose,
):
    """Query Gemini CLI/Code Assist quota usage and reset times across all accounts."""
    # Configure logging
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
    )

    config = Config()
    display = DisplayManager()

    # Determine auth path
    auth_path = config.auth_path

    # Initialize Auth Manager
    auth_mgr = AuthManager(auth_path)

    # Handle login/logout
    if login:
        try:
            if not json_output:
                display.console.print(
                    "[bold blue]Select services to enable:[/bold blue]"
                )
                display.console.print(
                    "1) Both Antigravity and Gemini CLI (Recommended)"
                )
                display.console.print("2) Antigravity only")
                display.console.print("3) Gemini CLI only")

            choice = click.prompt("Enter choice", type=int, default=1)
            services = ["AG", "CLI"]
            if choice == 2:
                services = ["AG"]
            elif choice == 3:
                services = ["CLI"]

            email = auth_mgr.login(services=services, manual_project_id=project_id)
            if not json_output:
                display.console.print(
                    f"[green]Successfully logged in as [bold]{email}[/bold][/green]"
                )
            else:
                print(json.dumps({"status": "success", "email": email}))
            return
        except Exception as e:
            if not json_output:
                display.console.print(f"[red]Login failed:[/red] {e}")
            else:
                print(json.dumps({"status": "error", "message": str(e)}))
            return

    if logout:
        success = auth_mgr.logout(logout)
        if not json_output:
            if success:
                display.console.print(
                    f"[green]Successfully logged out [bold]{logout}[/bold][/green]"
                )
            else:
                display.console.print(
                    f"[yellow]Account [bold]{logout}[/bold] not found.[/yellow]"
                )
        else:
            print(json.dumps({"status": "success" if success else "not_found"}))
        return

    if logout_all:
        auth_mgr.logout_all()
        if not json_output:
            display.console.print(
                "[green]Successfully logged out from all accounts.[/green]"
            )
        else:
            print(json.dumps({"status": "success"}))
        return

    if not auth_path.exists():
        display.console.print(
            f"[red]Error:[/red] Accounts file not found at [bold]{auth_path}[/bold]"
        )
        display.console.print("Please login with [bold]--login[/bold] to authenticate.")
        return

    try:
        accounts = auth_mgr.load_accounts()
        if not accounts:
            display.console.print("[red]Error:[/red] No accounts found in file.")
            return

        # If project_id is provided without --login, we might want to update an account
        if project_id and account:
            acc = next((a for a in accounts if a.get("email") == account), None)
            if acc:
                acc["projectId"] = project_id
                acc["managedProjectId"] = project_id
                auth_mgr.save_accounts()
                if not json_output:
                    display.console.print(
                        f"[green]Updated project ID for [bold]{account}[/bold] to [bold]{project_id}[/bold][/green]"
                    )

        # Print main header once
        if not json_output:
            display.print_main_header()

        # Filter accounts if requested
        if account:
            indices_to_check = [
                (i, a) for i, a in enumerate(accounts) if a.get("email") == account
            ]
            if not indices_to_check:
                display.console.print(
                    f"[red]Error:[/red] Account [bold]{account}[/bold] not found."
                )
                return
        else:
            indices_to_check = list(enumerate(accounts))

        # Use indices_to_check to maintain original order
        idx_to_result = {idx: None for idx, _ in indices_to_check}

        if not json_output:
            with display.console.status(
                "[bold blue]Fetching quotas for all accounts..."
            ):
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(indices_to_check), 10)
                ) as executor:
                    future_to_idx = {
                        executor.submit(
                            fetch_account_data, idx, acc_data, auth_mgr, show_all
                        ): idx
                        for idx, acc_data in indices_to_check
                    }
                    for future in concurrent.futures.as_completed(future_to_idx):
                        idx = future_to_idx[future]
                        idx_to_result[idx] = future.result()
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(indices_to_check), 10)
            ) as executor:
                future_to_idx = {
                    executor.submit(
                        fetch_account_data, idx, acc_data, auth_mgr, show_all
                    ): idx
                    for idx, acc_data in indices_to_check
                }
                for future in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    idx_to_result[idx] = future.result()

        results = []
        for idx, _ in indices_to_check:
            email, quotas, error = idx_to_result[idx]

            if not json_output:
                display.print_account_header(email)
                if error:
                    display.console.print(f"[yellow]Warning:[/yellow] {error}")
                    display.console.print("━" * 50)
                    continue
                display.draw_quota_bars(quotas, show_all=show_all)
                display.console.print("━" * 50)
            else:
                filtered_quotas = display.filter_quotas(quotas, show_all=show_all)
                results.append(
                    {
                        "email": email,
                        "quotas": filtered_quotas,
                        "error": error,
                    }
                )

        if json_output:
            print(json.dumps(results, indent=2))

    except Exception as e:
        display.console.print(f"[red]Error:[/red] {e}")


if __name__ == "__main__":
    main()
