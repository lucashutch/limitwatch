import subprocess
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional
from .base import BaseProvider


class GitHubCopilotProvider(BaseProvider):
    def __init__(self, account_data: Dict[str, Any]):
        super().__init__(account_data)
        self.github_token = account_data.get("githubToken")
        self.github_login = account_data.get("email", "")
        self.organization = account_data.get("organization")

    @property
    def provider_name(self) -> str:
        return "GitHub Copilot"

    @property
    def source_priority(self) -> int:
        return 2

    @property
    def primary_color(self) -> str:
        return "white"

    @property
    def short_indicator(self) -> str:
        return "H"

    def get_color(self, quota: Dict[str, Any]) -> str:
        """Return color based on quota type."""
        return "white"

    def interactive_login(self, display_manager: Any) -> Dict[str, Any]:
        """Perform an interactive login flow with the user."""
        import click

        # Attempt to load token from GitHub CLI
        try:
            token = self._get_gh_token()
            if token:
                display_manager.console.print("[green]✓ GitHub CLI token found[/green]")
            else:
                display_manager.console.print(
                    "[yellow]⚠ Could not load GitHub CLI token[/yellow]"
                )
                token = click.prompt("Enter GitHub token (or press Enter to skip)")
                if not token:
                    raise Exception("GitHub token is required")
        except Exception as e:
            display_manager.console.print(f"[yellow]Error loading token: {e}[/yellow]")
            raise

        # Auto-discover organizations
        orgs = []
        try:
            display_manager.console.print("[dim]Discovering organizations...[/dim]")
            orgs = self._discover_organizations(token)
            if orgs:
                display_manager.console.print(
                    f"[green]Found {len(orgs)} organization(s)[/green]"
                )
        except Exception as e:
            display_manager.console.print(
                f"[yellow]Could not auto-discover orgs: {e}[/yellow]"
            )

        # Let user select organization
        org = None
        if orgs:
            display_manager.console.print(
                "\n[bold blue]Select an organization (or press Enter to skip):[/bold blue]"
            )
            for i, o in enumerate(orgs, 1):
                display_manager.console.print(f"{i}) {o}")
            display_manager.console.print("0) Skip (personal only)")

            choice = click.prompt("Enter choice", type=int, default=0)
            if 1 <= choice <= len(orgs):
                org = orgs[choice - 1]
        else:
            # Fallback to manual entry if auto-discovery fails
            org = click.prompt(
                "Enter organization name (optional, for work quotas)",
                default="",
                show_default=False,
            )
            if org:
                org = org.strip() or None

        return self.login(token=token, organization=org)

    def _discover_organizations(self, token: str) -> list:
        """Discover organizations the user has access to."""
        headers = {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        }

        try:
            resp = requests.get(
                "https://api.github.com/user/orgs",
                headers=headers,
                timeout=10,
                params={"per_page": 100},
            )
            if resp.status_code == 200:
                orgs_data = resp.json()
                # Return organization logins sorted
                org_logins = [o.get("login") for o in orgs_data if o.get("login")]
                return sorted(org_logins)
        except Exception:
            pass

        return []

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        """Filter quotas - show all by default for Copilot."""
        return quotas

    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        """Sort by quota type (personal first, then org)."""
        name = quota.get("display_name", "")
        # Personal quota priority 0, org quota priority 1
        type_priority = 0 if "Personal" in name else 1
        return 0, type_priority, name

    def login(self, **kwargs) -> Dict[str, Any]:
        """Perform GitHub login and return account data."""
        token = kwargs.get("token")
        organization = kwargs.get("organization")

        if not token:
            raise Exception("GitHub token is required for GitHub Copilot login")

        # Validate token and get user info
        headers = {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        }

        try:
            # Get authenticated user info
            resp = requests.get(
                "https://api.github.com/user", headers=headers, timeout=10
            )
            if resp.status_code != 200:
                raise Exception(
                    f"Failed to authenticate with GitHub: {resp.status_code}"
                )

            user_data = resp.json()
            email = user_data.get("login") or user_data.get("email") or "GitHub User"

        except Exception as e:
            raise Exception(f"GitHub authentication failed: {e}")

        account_data = {
            "type": "github_copilot",
            "email": str(email),
            "githubToken": token,
            "services": ["GITHUB_COPILOT"],
        }

        if organization:
            account_data["organization"] = organization

        return account_data

    def _get_gh_token(self) -> Optional[str]:
        """Attempt to retrieve GitHub CLI token using 'gh auth token'."""
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        return None

    def fetch_quotas(self) -> List[Dict[str, Any]]:
        """Fetch Copilot quotas for personal and org."""
        if not self.github_token:
            return []

        results = []
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        }

        # 1. Personal/User quota
        personal_quota = self._fetch_personal_copilot_quota(headers)
        if personal_quota:
            results.append(personal_quota)
        elif not self.organization:
            # Only show the generic fallback when there is no org — for
            # Business/Enterprise users the org quota is the real number and
            # showing 'Personal (Available)' alongside it would be misleading.
            results.append(
                {
                    "name": "GitHub Copilot Personal",
                    "display_name": "Personal (Available)",
                    "remaining_pct": 100.0,
                    "reset": "Monthly",
                    "source_type": "GitHub Copilot",
                }
            )

        # 2. Organization quota (if organization is specified)
        if self.organization:
            org_quota = self._fetch_org_copilot_quota(headers, self.organization)
            if org_quota:
                results.append(org_quota)

        return results

    def _fetch_personal_copilot_quota(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Fetch personal Copilot quota. Uses multiple fallback paths."""
        # Try 1: Copilot internal user endpoint (used by Copilot extensions)
        internal_data = self._fetch_copilot_internal_user(headers)
        if internal_data:
            copilot_plan = str(internal_data.get("copilot_plan", "")).lower()
            reset_iso = internal_data.get("quota_reset_date") or "Monthly"
            if copilot_plan == "free":
                # Free plan users don't have a personal premium allotment.
                return {
                    "name": "GitHub Copilot Personal",
                    "display_name": "Personal",
                    "remaining_pct": 100.0,
                    "used_pct": 0.0,
                    "reset": reset_iso,
                    "source_type": "GitHub Copilot",
                }

            # Only individual plans should use the internal premium snapshot
            # for PERSONAL usage. Business/enterprise and unknown plans can
            # reflect shared org pool usage.
            personal_plans = {"individual", "individual_pro", "pro", "pro+"}
            if copilot_plan and copilot_plan not in personal_plans:
                internal_data = None

            if not copilot_plan and self.organization:
                copilot_orgs = {
                    o.lower()
                    for o in (internal_data.get("organization_login_list") or [])
                    if isinstance(o, str)
                }
                if self.organization.lower() in copilot_orgs:
                    internal_data = None

        if internal_data:
            quota_snapshots = internal_data.get("quota_snapshots", {})
            premium = quota_snapshots.get("premium_interactions", {})
            percent_remaining = premium.get("percent_remaining")

            if isinstance(percent_remaining, (int, float)):
                remaining_pct = float(percent_remaining)
                used_pct = max(0.0, min(100.0, 100.0 - remaining_pct))

                entitlement = premium.get("entitlement")
                remaining = premium.get("remaining")
                overage_count = premium.get("overage_count", 0)
                overage_permitted = premium.get("overage_permitted", False)
                reset_iso = internal_data.get("quota_reset_date") or "Monthly"

                quota = {
                    "name": "GitHub Copilot Personal",
                    "display_name": "Personal",
                    "remaining_pct": remaining_pct,
                    "used_pct": used_pct,
                    "reset": reset_iso,
                    "source_type": "GitHub Copilot",
                }

                if isinstance(entitlement, (int, float)):
                    quota["limit"] = entitlement
                if isinstance(remaining, (int, float)):
                    quota["remaining"] = remaining
                if isinstance(entitlement, (int, float)) and isinstance(
                    remaining, (int, float)
                ):
                    quota["used"] = entitlement - remaining
                if isinstance(overage_count, (int, float)):
                    quota["overage_used"] = overage_count
                quota["overage_permitted"] = bool(overage_permitted)

                return quota

        # Try 2: User-level billing endpoint (may require additional scopes)
        try:
            resp = requests.get(
                "https://api.github.com/user/copilot/billing",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                seat_breakdown = data.get("seat_breakdown", {})
                total_seats = seat_breakdown.get("total", 0)
                active_seats = seat_breakdown.get("active_this_cycle", 0)

                if total_seats > 0:
                    remaining_pct = ((total_seats - active_seats) / total_seats) * 100
                else:
                    remaining_pct = 100.0

                now = datetime.now(timezone.utc)
                next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
                reset_iso = next_month.isoformat().replace("+00:00", "Z")

                return {
                    "name": "GitHub Copilot Personal",
                    "display_name": "Personal",
                    "remaining_pct": remaining_pct,
                    "used_pct": max(0.0, min(100.0, 100.0 - remaining_pct)),
                    "remaining": total_seats - active_seats,
                    "limit": total_seats,
                    "used": active_seats,
                    "reset": reset_iso,
                    "source_type": "GitHub Copilot",
                }
        except Exception:
            pass

        # Try 3: Use gh CLI if available (may have better permissions)
        try:
            usage_data = self._get_copilot_usage_via_gh()
            if usage_data and "usage_percentage" in usage_data:
                usage_pct = usage_data.get("usage_percentage", 0)
                remaining_pct = 100.0 - usage_pct

                return {
                    "name": "GitHub Copilot Personal",
                    "display_name": "Personal",
                    "remaining_pct": remaining_pct,
                    "used_pct": usage_pct,
                    "reset": "Monthly",
                    "source_type": "GitHub Copilot",
                }
        except Exception:
            pass

        return None

    def _fetch_org_copilot_quota(
        self, headers: Dict[str, str], organization: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch organization Copilot quota. Returns error dict on failure."""
        try:
            resp = requests.get(
                f"https://api.github.com/orgs/{organization}/copilot/billing",
                headers=headers,
                timeout=10,
            )

            if resp.status_code == 200:
                org_data = resp.json()
                seat_breakdown = org_data.get("seat_breakdown", {})

                total_seats = seat_breakdown.get("total", 0)
                active_seats = seat_breakdown.get("active_this_cycle", 0)

                if total_seats > 0:
                    remaining_pct = ((total_seats - active_seats) / total_seats) * 100
                else:
                    remaining_pct = 100.0

                now = datetime.now(timezone.utc)
                next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
                reset_iso = next_month.isoformat().replace("+00:00", "Z")

                seat_used_pct = (
                    max(0.0, min(100.0, (active_seats / total_seats) * 100))
                    if total_seats > 0
                    else 0.0
                )
                return {
                    "name": f"GitHub Copilot Org ({organization})",
                    "display_name": organization,
                    "remaining_pct": remaining_pct,
                    "used_pct": seat_used_pct,
                    "remaining": total_seats - active_seats,
                    "limit": total_seats,
                    "used": active_seats,
                    "reset": reset_iso,
                    "source_type": "GitHub Copilot",
                }
            elif resp.status_code == 404:
                # Org not found; try member-level endpoint instead
                member_quota = self._fetch_member_copilot_quota(headers, organization)
                if member_quota:
                    return member_quota
                internal_org_quota = self._fetch_org_from_copilot_internal_user(
                    headers, organization
                )
                if internal_org_quota:
                    return internal_org_quota
                return {
                    "name": f"GitHub Copilot Org ({organization})",
                    "display_name": f"{organization}",
                    "is_error": True,
                    "message": "Copilot Business/Enterprise not found or disabled for this org",
                    "source_type": "GitHub Copilot",
                }
            elif resp.status_code == 403:
                # Permission denied on billing; try member-level endpoint
                member_quota = self._fetch_member_copilot_quota(headers, organization)
                if member_quota:
                    return member_quota
                internal_org_quota = self._fetch_org_from_copilot_internal_user(
                    headers, organization
                )
                if internal_org_quota:
                    return internal_org_quota
                return {
                    "name": f"GitHub Copilot Org ({organization})",
                    "display_name": f"{organization}",
                    "is_error": True,
                    "message": "Insufficient permissions (requires org owner or manage_billing:copilot scope)",
                    "source_type": "GitHub Copilot",
                }
            else:
                return {
                    "name": f"GitHub Copilot Org ({organization})",
                    "display_name": f"{organization}",
                    "is_error": True,
                    "message": f"Could not fetch org quota (HTTP {resp.status_code})",
                    "source_type": "GitHub Copilot",
                }
        except Exception as e:
            return {
                "name": f"GitHub Copilot Org ({organization})",
                "display_name": f"{organization}",
                "is_error": True,
                "message": f"Error fetching org quota: {str(e)}",
                "source_type": "GitHub Copilot",
            }

    def _get_copilot_usage_via_gh(self) -> Optional[Dict[str, Any]]:
        """Try to fetch Copilot usage via gh CLI (may have better permissions)."""
        # Try 1: Copilot internal user endpoint
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "/copilot_internal/user",
                    "--header",
                    "X-GitHub-Api-Version:2025-04-01",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                import json

                data = json.loads(result.stdout)
                copilot_plan = str(data.get("copilot_plan", "")).lower()
                if copilot_plan == "free":
                    return {"usage_percentage": 0.0}
                if copilot_plan not in {"individual", "individual_pro", "pro", "pro+"}:
                    return None

                premium = data.get("quota_snapshots", {}).get(
                    "premium_interactions", {}
                )
                percent_remaining = premium.get("percent_remaining")
                if isinstance(percent_remaining, (int, float)):
                    usage_pct = 100.0 - float(percent_remaining)
                    return {"usage_percentage": usage_pct}
        except Exception:
            pass

        # Try 2: User billing endpoint
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "/user/copilot/billing",
                    "--header",
                    "X-GitHub-Api-Version:2022-11-28",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                import json

                data = json.loads(result.stdout)
                # Parse the response to extract usage percentage
                if "seat_breakdown" in data:
                    seat_breakdown = data.get("seat_breakdown", {})
                    total = seat_breakdown.get("total", 1)
                    active = seat_breakdown.get("active_this_cycle", 0)
                    if total > 0:
                        usage_pct = (active / total) * 100
                        return {"usage_percentage": usage_pct}
        except Exception:
            pass

        return None

    def _fetch_copilot_internal_user(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Fetch Copilot user metadata from /copilot_internal/user."""
        if not self.github_token:
            return None

        # Copilot internal endpoints commonly expect `token` auth style.
        internal_headers = dict(headers)
        internal_headers["Authorization"] = f"token {self.github_token}"
        internal_headers["X-GitHub-Api-Version"] = "2025-04-01"

        try:
            resp = requests.get(
                "https://api.github.com/copilot_internal/user",
                headers=internal_headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

        return None

    def _fetch_org_from_copilot_internal_user(
        self, headers: Dict[str, str], organization: str
    ) -> Optional[Dict[str, Any]]:
        """Fallback org status from copilot_internal/user organization list."""
        internal_data = self._fetch_copilot_internal_user(headers)
        if not internal_data:
            return None

        copilot_orgs = [
            o.lower()
            for o in (internal_data.get("organization_login_list") or [])
            if isinstance(o, str)
        ]
        if organization.lower() not in copilot_orgs:
            return None

        premium = internal_data.get("quota_snapshots", {}).get(
            "premium_interactions", {}
        )
        percent_remaining = premium.get("percent_remaining")
        if isinstance(percent_remaining, (int, float)):
            remaining_pct = float(percent_remaining)
            used_pct = max(0.0, min(100.0, 100.0 - remaining_pct))
        else:
            remaining_pct = 100.0
            used_pct = 0.0

        return {
            "name": f"GitHub Copilot Org ({organization})",
            "display_name": organization,
            "remaining_pct": remaining_pct,
            "used_pct": used_pct,
            "reset": internal_data.get("quota_reset_date") or "Monthly",
            "source_type": "GitHub Copilot",
        }

    def _fetch_member_copilot_quota(
        self, headers: Dict[str, str], organization: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch personal Copilot status within an organization.
        Uses member endpoint: /orgs/{org}/members/{username}/copilot
        This returns seat assignment details (plan type, activity, etc) even for non-owners.
        """
        # Get the authenticated user's login (email field stores the login)
        try:
            user_resp = requests.get(
                "https://api.github.com/user",
                headers=headers,
                timeout=10,
            )
            if user_resp.status_code != 200:
                return None

            user_data = user_resp.json()
            username = user_data.get("login")
            if not username:
                return None

            # Try to fetch member's seat assignment in the org
            resp = requests.get(
                f"https://api.github.com/orgs/{organization}/members/{username}/copilot",
                headers=headers,
                timeout=10,
            )

            if resp.status_code == 200:
                return {
                    "name": f"GitHub Copilot Org ({organization})",
                    "display_name": organization,
                    "remaining_pct": 100.0,
                    "reset": "Monthly",
                    "source_type": "GitHub Copilot",
                }
        except Exception:
            pass

        return None
