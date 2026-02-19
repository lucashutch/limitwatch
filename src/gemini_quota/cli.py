import json
import click
import logging
import concurrent.futures
from importlib.metadata import version, PackageNotFoundError
from .config import Config
from .auth import AuthManager
from .quota_client import QuotaClient
from .display import DisplayManager

try:
    __version__ = version("gemini-quota")
except PackageNotFoundError:
    __version__ = "unknown"


def fetch_account_data(idx, acc_data, auth_mgr, show_all):
    email = acc_data.get("email", f"Account {idx}")
    account_type = acc_data.get("type", "google")

    creds = None
    if account_type == "google":
        creds = auth_mgr.get_credentials(idx)
        if not creds:
            return email, None, None, f"Could not load credentials for {email}"
        try:
            # Refresh token
            auth_mgr.refresh_credentials(creds)
        except Exception as e:
            return email, None, None, f"Token refresh failed: {e}"

    try:
        # Initialize Client with account data and credentials
        client = QuotaClient(acc_data, credentials=creds)
        quotas = client.fetch_quotas()

        return email, quotas, client, None
    except Exception as e:
        return email, None, None, str(e)


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(__version__, "--version", "-v", prog_name="gemini-quota")
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
                display.console.print("[bold blue]Select Provider:[/bold blue]")
                providers = QuotaClient.get_available_providers()
                for i, (p_type, p_name) in enumerate(providers.items(), 1):
                    display.console.print(f"{i}) {p_name}")

                choice = click.prompt("Enter choice", type=int, default=1)
                provider_type = list(providers.keys())[choice - 1]

                # Instantiate an empty client of that type to run its interactive login
                client = QuotaClient(account_data={"type": provider_type})
                account_data = client.provider.interactive_login(display)
                email = auth_mgr.login(account_data)
            else:
                # For non-interactive JSON output, we default to Google login
                client = QuotaClient(account_data={"type": "google"})
                account_data = client.provider.login()
                email = auth_mgr.login(account_data)

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
            email, quotas, client, error = idx_to_result[idx]

            if not json_output:
                provider_name = client.provider.provider_name if client else ""
                display.print_account_header(email, provider=provider_name)
                if error:
                    display.console.print(f"[yellow]Warning:[/yellow] {error}")
                    display.console.print("━" * 50)
                    continue
                display.draw_quota_bars(quotas, client=client, show_all=show_all)
                display.console.print("━" * 50)
            else:
                filtered_quotas = display.filter_quotas(
                    quotas, client=client, show_all=show_all
                )
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
