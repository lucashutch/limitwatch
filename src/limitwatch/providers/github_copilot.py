import subprocess
import requests
import concurrent.futures
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional
from .base import BaseProvider

logger = logging.getLogger(__name__)


# --- Helper functions ---


def _make_github_headers(token: str) -> Dict[str, str]:
    """Build standard GitHub API headers."""
    return {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github+json",
    }


def _next_month_reset_iso() -> str:
    """Calculate the ISO timestamp for the 1st of next month (UTC)."""
    now = datetime.now(timezone.utc)
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    return next_month.isoformat().replace("+00:00", "Z")


def _seat_percentages(total: int, active: int) -> Tuple[float, float]:
    """Calculate remaining and used percentages from seat numbers."""
    if total <= 0:
        return 100.0, 0.0
    remaining_pct = ((total - active) / total) * 100
    used_pct = max(0.0, min(100.0, (active / total) * 100))
    return remaining_pct, used_pct


def _build_org_error(organization: str, message: str) -> Dict[str, Any]:
    """Build a standard org error quota dict."""
    return {
        "name": f"GitHub Copilot Org ({organization})",
        "display_name": f"{organization}",
        "is_error": True,
        "message": message,
        "source_type": "GitHub Copilot",
    }


def _build_personal_quota(remaining_pct, used_pct, reset, **extras) -> Dict[str, Any]:
    """Build a personal quota dict."""
    quota = {
        "name": "GitHub Copilot Personal",
        "display_name": "Personal",
        "remaining_pct": remaining_pct,
        "used_pct": used_pct,
        "reset": reset,
        "source_type": "GitHub Copilot",
    }
    quota.update(extras)
    return quota


PERSONAL_PLANS = {"individual", "individual_pro", "pro", "pro+"}
DEFAULT_API_TIMEOUT = 3
DEFAULT_GH_CLI_TIMEOUT = 4
ENABLE_GH_CLI_FALLBACK_DEFAULT = False


class GitHubCopilotProvider(BaseProvider):
    def __init__(self, account_data: Dict[str, Any]):
        super().__init__(account_data)
        self.github_token = account_data.get("githubToken")
        self.github_login = account_data.get("email", "")
        self.organization = account_data.get("organization")
        self._internal_user_cache: Optional[Dict[str, Any]] = None
        self._user_login_cache: Optional[str] = None

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
        return "white"

    def interactive_login(self, display_manager: Any) -> Dict[str, Any]:
        """Perform an interactive login flow with the user."""

        token = self._prompt_for_token(display_manager)
        org = self._prompt_for_org(display_manager, token)
        return self.login(token=token, organization=org)

    def _prompt_for_token(self, display_manager) -> str:
        """Try gh CLI token first, then prompt user."""
        import click

        try:
            token = self._get_gh_token()
            if token:
                display_manager.console.print("[green]✓ GitHub CLI token found[/green]")
                return token
            display_manager.console.print(
                "[yellow]⚠ Could not load GitHub CLI token[/yellow]"
            )
            token = click.prompt("Enter GitHub token (or press Enter to skip)")
            if not token:
                raise Exception("GitHub token is required")
            return token
        except Exception as e:
            display_manager.console.print(f"[yellow]Error loading token: {e}[/yellow]")
            raise

    def _prompt_for_org(self, display_manager, token: str) -> Optional[str]:
        """Auto-discover orgs, then let user pick one."""
        import click

        orgs = self._try_discover_orgs(display_manager, token)

        if orgs:
            return self._select_org_from_list(display_manager, orgs)
        else:
            org = click.prompt(
                "Enter organization name (optional, for work quotas)",
                default="",
                show_default=False,
            )
            return org.strip() or None

    def _try_discover_orgs(self, display_manager, token: str) -> list:
        """Attempt to discover organizations, handling errors gracefully."""
        try:
            display_manager.console.print("[dim]Discovering organizations...[/dim]")
            orgs = self._discover_organizations(token)
            if orgs:
                display_manager.console.print(
                    f"[green]Found {len(orgs)} organization(s)[/green]"
                )
            return orgs
        except Exception as e:
            display_manager.console.print(
                f"[yellow]Could not auto-discover orgs: {e}[/yellow]"
            )
            return []

    @staticmethod
    def _select_org_from_list(display_manager, orgs: list) -> Optional[str]:
        """Display org list and let user pick."""
        import click

        display_manager.console.print(
            "\n[bold blue]Select an organization (or press Enter to skip):[/bold blue]"
        )
        for i, o in enumerate(orgs, 1):
            display_manager.console.print(f"{i}) {o}")
        display_manager.console.print("0) Skip (personal only)")

        choice = click.prompt("Enter choice", type=int, default=0)
        if 1 <= choice <= len(orgs):
            return orgs[choice - 1]
        return None

    def _discover_organizations(self, token: str) -> list:
        """Discover organizations the user has access to."""
        headers = _make_github_headers(token)
        try:
            resp = requests.get(
                "https://api.github.com/user/orgs",
                headers=headers,
                timeout=10,
                params={"per_page": 100},
            )
            if resp.status_code == 200:
                return sorted(o.get("login") for o in resp.json() if o.get("login"))
        except Exception:
            pass
        return []

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        return quotas

    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        name = quota.get("display_name", "")
        type_priority = 0 if "Personal" in name else 1
        return 0, type_priority, name

    def login(self, **kwargs) -> Dict[str, Any]:
        """Perform GitHub login and return account data."""
        token = kwargs.get("token")
        organization = kwargs.get("organization")

        if not token:
            raise Exception("GitHub token is required for GitHub Copilot login")

        email = self._validate_token(token)

        account_data = {
            "type": "github_copilot",
            "email": str(email),
            "githubToken": token,
            "services": ["GITHUB_COPILOT"],
        }
        if organization:
            account_data["organization"] = organization
        return account_data

    @staticmethod
    def _validate_token(token: str) -> str:
        """Validate the token and return the user's login/email."""
        headers = _make_github_headers(token)
        try:
            resp = requests.get(
                "https://api.github.com/user", headers=headers, timeout=10
            )
            if resp.status_code != 200:
                raise Exception(
                    f"Failed to authenticate with GitHub: {resp.status_code}"
                )
            user_data = resp.json()
            return user_data.get("login") or user_data.get("email") or "GitHub User"
        except Exception as e:
            raise Exception(f"GitHub authentication failed: {e}")

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

        start = time.perf_counter()
        email = self.account_data.get("email", "unknown")
        logger.debug(
            f"[github_copilot] fetch_quotas start account={email} org={self.organization or '-'}"
        )

        results = []
        headers = _make_github_headers(self.github_token)

        if self.organization:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                personal_future = executor.submit(
                    self._fetch_personal_copilot_quota, headers
                )
                org_future = executor.submit(
                    self._fetch_org_copilot_quota, headers, self.organization
                )

                personal_quota = personal_future.result()
                org_quota = org_future.result()

            if personal_quota:
                results.append(personal_quota)
            if org_quota:
                results.append(org_quota)
        else:
            personal_quota = self._fetch_personal_copilot_quota(headers)
            if personal_quota:
                results.append(personal_quota)
            else:
                results.append(_build_personal_quota(100.0, 0.0, "Monthly"))

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[github_copilot] fetch_quotas done account={email} elapsed_ms={elapsed_ms:.1f} "
            f"quota_count={len(results)}"
        )
        return results

    # --- Personal quota fetching (3 fallback strategies) ---

    def _fetch_personal_copilot_quota(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Fetch personal Copilot quota using multiple fallback paths."""
        start = time.perf_counter()
        preferred = self.account_data.get("preferredPersonalQuotaMethod")

        if preferred == "internal":
            quota = self._try_personal_via_internal(headers)
            if quota:
                return quota
        elif preferred == "billing":
            quota = self._try_personal_via_billing(headers)
            if quota:
                return quota

        network_methods = {
            "internal": lambda: self._try_personal_via_internal(headers),
            "billing": lambda: self._try_personal_via_billing(headers),
        }

        if preferred in network_methods:
            del network_methods[preferred]

        method, quota = self._first_successful_method(network_methods)
        if quota:
            self.account_data["preferredPersonalQuotaMethod"] = method
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] personal method={method} elapsed_ms={elapsed_ms:.1f}"
            )
            return quota

        if not self.account_data.get(
            "enableGhCliFallback", ENABLE_GH_CLI_FALLBACK_DEFAULT
        ):
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] personal method=none elapsed_ms={elapsed_ms:.1f}"
            )
            return None

        quota = self._try_personal_via_gh_cli()
        if quota:
            self.account_data["preferredPersonalQuotaMethod"] = "gh_cli"
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] personal method=gh_cli elapsed_ms={elapsed_ms:.1f}"
            )
        else:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] personal method=none elapsed_ms={elapsed_ms:.1f}"
            )
        return quota

    @staticmethod
    def _first_successful_method(
        methods: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Run methods in parallel and return the first successful quota result."""
        if not methods:
            return None, None

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(methods)
        ) as executor:
            future_to_name = {
                executor.submit(method): name for name, method in methods.items()
            }
            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    quota = future.result()
                except Exception:
                    continue
                if quota:
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    logger.debug(
                        f"[github_copilot] method race winner={name} elapsed_ms={elapsed_ms:.1f}"
                    )
                    return name, quota
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[github_copilot] method race no-result elapsed_ms={elapsed_ms:.1f}"
        )
        return None, None

    def _try_personal_via_internal(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Try copilot_internal/user endpoint for personal quota."""
        internal_data = self._fetch_copilot_internal_user(headers)
        if not internal_data:
            return None

        copilot_plan = str(internal_data.get("copilot_plan", "")).lower()
        reset_iso = internal_data.get("quota_reset_date") or "Monthly"

        if copilot_plan == "free":
            return _build_personal_quota(100.0, 0.0, reset_iso)

        # Only individual plans use internal snapshot for personal usage
        if copilot_plan and copilot_plan not in PERSONAL_PLANS:
            return None

        # Unknown plan but org is present → likely org pool data
        if not copilot_plan and self.organization:
            copilot_orgs = {
                o.lower()
                for o in (internal_data.get("organization_login_list") or [])
                if isinstance(o, str)
            }
            if self.organization.lower() in copilot_orgs:
                return None

        return self._extract_premium_quota(internal_data)

    def _extract_premium_quota(self, internal_data: dict) -> Optional[Dict[str, Any]]:
        """Extract premium interaction quota from internal user data."""
        premium = internal_data.get("quota_snapshots", {}).get(
            "premium_interactions", {}
        )
        percent_remaining = premium.get("percent_remaining")

        if not isinstance(percent_remaining, (int, float)):
            return None

        remaining_pct = float(percent_remaining)
        used_pct = max(0.0, min(100.0, 100.0 - remaining_pct))
        reset_iso = internal_data.get("quota_reset_date") or "Monthly"

        extras = {}
        entitlement = premium.get("entitlement")
        remaining = premium.get("remaining")
        if isinstance(entitlement, (int, float)):
            extras["limit"] = entitlement
        if isinstance(remaining, (int, float)):
            extras["remaining"] = remaining
        if isinstance(entitlement, (int, float)) and isinstance(
            remaining, (int, float)
        ):
            extras["used"] = entitlement - remaining

        overage_count = premium.get("overage_count", 0)
        if isinstance(overage_count, (int, float)):
            extras["overage_used"] = overage_count
        extras["overage_permitted"] = bool(premium.get("overage_permitted", False))

        return _build_personal_quota(remaining_pct, used_pct, reset_iso, **extras)

    def _try_personal_via_billing(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Try /user/copilot/billing endpoint for personal quota."""
        try:
            resp = requests.get(
                "https://api.github.com/user/copilot/billing",
                headers=headers,
                timeout=DEFAULT_API_TIMEOUT,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            seat_breakdown = data.get("seat_breakdown", {})
            total = seat_breakdown.get("total", 0)
            active = seat_breakdown.get("active_this_cycle", 0)

            remaining_pct, used_pct = _seat_percentages(total, active)

            return _build_personal_quota(
                remaining_pct,
                used_pct,
                _next_month_reset_iso(),
                remaining=total - active,
                limit=total,
                used=active,
            )
        except Exception:
            return None

    def _try_personal_via_gh_cli(self) -> Optional[Dict[str, Any]]:
        """Try gh CLI for personal quota."""
        try:
            usage_data = self._get_copilot_usage_via_gh()
            if usage_data and "usage_percentage" in usage_data:
                usage_pct = usage_data.get("usage_percentage", 0)
                return _build_personal_quota(100.0 - usage_pct, usage_pct, "Monthly")
        except Exception:
            pass
        return None

    # --- Org quota fetching ---

    def _fetch_org_copilot_quota(
        self, headers: Dict[str, str], organization: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch organization Copilot quota with fallbacks."""
        start = time.perf_counter()
        try:
            resp = requests.get(
                f"https://api.github.com/orgs/{organization}/copilot/billing",
                headers=headers,
                timeout=DEFAULT_API_TIMEOUT,
            )
            if resp.status_code == 200:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.debug(
                    f"[github_copilot] org primary status=200 elapsed_ms={elapsed_ms:.1f}"
                )
                return self._parse_org_billing(resp.json(), organization)
            if resp.status_code in (403, 404):
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.debug(
                    f"[github_copilot] org primary status={resp.status_code} elapsed_ms={elapsed_ms:.1f}"
                )
                return self._try_org_fallbacks(headers, organization, resp.status_code)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] org primary status={resp.status_code} elapsed_ms={elapsed_ms:.1f}"
            )
            return _build_org_error(
                organization, f"Could not fetch org quota (HTTP {resp.status_code})"
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] org error elapsed_ms={elapsed_ms:.1f} err={e}"
            )
            return _build_org_error(organization, f"Error fetching org quota: {str(e)}")

    @staticmethod
    def _parse_org_billing(org_data: dict, organization: str) -> Dict[str, Any]:
        """Parse organization billing data into a quota dict."""
        seat_breakdown = org_data.get("seat_breakdown", {})
        total = seat_breakdown.get("total", 0)
        active = seat_breakdown.get("active_this_cycle", 0)
        remaining_pct, used_pct = _seat_percentages(total, active)

        return {
            "name": f"GitHub Copilot Org ({organization})",
            "display_name": organization,
            "remaining_pct": remaining_pct,
            "used_pct": used_pct,
            "remaining": total - active,
            "limit": total,
            "used": active,
            "reset": _next_month_reset_iso(),
            "source_type": "GitHub Copilot",
        }

    def _try_org_fallbacks(self, headers, organization, status_code) -> Dict[str, Any]:
        """Try member and internal endpoints as fallback for org quota."""
        _, quota = self._first_successful_method(
            {
                "member": lambda: self._fetch_member_copilot_quota(
                    headers, organization
                ),
                "internal": lambda: self._fetch_org_from_copilot_internal_user(
                    headers, organization
                ),
            }
        )
        if quota:
            return quota

        if status_code == 404:
            return _build_org_error(
                organization,
                "Copilot Business/Enterprise not found or disabled for this org",
            )
        return _build_org_error(
            organization,
            "Insufficient permissions (requires org owner or manage_billing:copilot scope)",
        )

    # --- Internal API helpers ---

    def _fetch_copilot_internal_user(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Fetch Copilot user metadata from /copilot_internal/user."""
        if self._internal_user_cache is not None:
            return self._internal_user_cache

        if not self.github_token:
            return None

        internal_headers = dict(headers)
        internal_headers["Authorization"] = f"token {self.github_token}"
        internal_headers["X-GitHub-Api-Version"] = "2025-04-01"

        try:
            resp = requests.get(
                "https://api.github.com/copilot_internal/user",
                headers=internal_headers,
                timeout=DEFAULT_API_TIMEOUT,
            )
            if resp.status_code == 200:
                self._internal_user_cache = resp.json()
                return self._internal_user_cache
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
        """Fetch personal Copilot status within an organization via member endpoint."""
        try:
            username = self._user_login_cache
            if not username:
                user_resp = requests.get(
                    "https://api.github.com/user",
                    headers=headers,
                    timeout=DEFAULT_API_TIMEOUT,
                )
                if user_resp.status_code != 200:
                    return None
                username = user_resp.json().get("login")
                self._user_login_cache = username
            if not username:
                return None

            resp = requests.get(
                f"https://api.github.com/orgs/{organization}/members/{username}/copilot",
                headers=headers,
                timeout=DEFAULT_API_TIMEOUT,
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

    def _get_copilot_usage_via_gh(self) -> Optional[Dict[str, Any]]:
        """Try to fetch Copilot usage via gh CLI."""
        return self._try_gh_internal_usage() or self._try_gh_billing_usage()

    def _try_gh_internal_usage(self) -> Optional[Dict[str, Any]]:
        """Try copilot_internal/user via gh CLI."""
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
                timeout=DEFAULT_GH_CLI_TIMEOUT,
            )
            if result.returncode != 0:
                return None

            import json

            data = json.loads(result.stdout)
            copilot_plan = str(data.get("copilot_plan", "")).lower()
            if copilot_plan == "free":
                return {"usage_percentage": 0.0}
            if copilot_plan not in PERSONAL_PLANS:
                return None

            premium = data.get("quota_snapshots", {}).get("premium_interactions", {})
            percent_remaining = premium.get("percent_remaining")
            if isinstance(percent_remaining, (int, float)):
                return {"usage_percentage": 100.0 - float(percent_remaining)}
        except Exception:
            pass
        return None

    @staticmethod
    def _try_gh_billing_usage() -> Optional[Dict[str, Any]]:
        """Try /user/copilot/billing via gh CLI."""
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
                timeout=DEFAULT_GH_CLI_TIMEOUT,
            )
            if result.returncode != 0:
                return None

            import json

            data = json.loads(result.stdout)
            seat_breakdown = data.get("seat_breakdown", {})
            total = seat_breakdown.get("total", 1)
            active = seat_breakdown.get("active_this_cycle", 0)
            if total > 0:
                return {"usage_percentage": (active / total) * 100}
        except Exception:
            pass
        return None
