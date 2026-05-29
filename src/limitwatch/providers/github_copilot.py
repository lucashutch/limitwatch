import subprocess
import requests
import concurrent.futures
import logging
import time
import re
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


PERSONAL_PLANS = {"individual", "individual_pro", "pro", "pro+", "pro_plus", "max"}
DEFAULT_API_TIMEOUT = 4
DEFAULT_GH_CLI_TIMEOUT = 6
ENABLE_GH_CLI_FALLBACK_DEFAULT = False
GH_AUTH_STATUS_TIMEOUT = 6
AI_CREDIT_DOLLARS = 0.01
AI_CREDIT_SKU_HINTS = ("ai_credit", "ai credit", "copilot premium", "premium request")
AI_CREDIT_PRODUCT_HINTS = ("copilot",)
PERSONAL_AI_CREDIT_ALLOWANCES = {
    "free": 0,
    "individual": 1500,
    "individual_pro": 1500,
    "pro": 1500,
    "pro+": 7000,
    "pro_plus": 7000,
    "max": 20000,
}
ORG_AI_CREDIT_ALLOWANCES = {
    "business": 1900,
    "enterprise": 3900,
}
ORG_PROMO_AI_CREDIT_ALLOWANCES = {
    "business": 3000,
    "enterprise": 7000,
}
PROMO_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
PROMO_END = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _current_month_window(now: Optional[datetime] = None) -> Tuple[str, str]:
    """Return current UTC month [start, end) date strings for billing APIs."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start.date().isoformat(), end.date().isoformat()


def _billing_usage_urls(owner: str, is_org: bool) -> Tuple[str, str]:
    """Build public billing usage and summary URLs."""
    owner_path = f"organizations/{owner}" if is_org else f"users/{owner}"
    base = f"https://api.github.com/{owner_path}/settings/billing/usage"
    return base, f"{base}/summary"


def _credits_from_amount(amount: Any) -> Optional[float]:
    if isinstance(amount, (int, float)):
        return float(amount) / AI_CREDIT_DOLLARS
    return None


def _looks_like_copilot_ai_credit(row: Dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(k, ""))
        for k in (
            "product",
            "productName",
            "sku",
            "skuName",
            "meter",
            "description",
            "usageType",
        )
    ).lower()
    return any(h in text for h in AI_CREDIT_PRODUCT_HINTS) and any(
        h in text for h in AI_CREDIT_SKU_HINTS
    )


def _iter_billing_rows(payload: Any):
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_billing_rows(item)
    elif isinstance(payload, dict):
        if _looks_like_copilot_ai_credit(payload):
            yield payload
        for key in ("usageItems", "items", "usage", "summary", "products", "lineItems"):
            if key in payload:
                yield from _iter_billing_rows(payload[key])


def _parse_ai_credit_billing_payload(
    payload: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Parse public billing usage/summary payloads for Copilot AI credits."""
    rows = list(_iter_billing_rows(payload))
    if not rows:
        return None

    used = 0.0
    gross = 0.0
    discount = 0.0
    net_amount = 0.0
    parsed_rows = []
    for row in rows:
        row_used = None
        for key in ("netQuantity", "net_quantity"):
            if isinstance(row.get(key), (int, float)):
                row_used = float(row[key])
                break
        if row_used is None:
            for key in ("netAmount", "net_amount"):
                row_used = _credits_from_amount(row.get(key))
                if row_used is not None:
                    break
        if row_used is None:
            for key in ("quantity", "usageQuantity", "amount"):
                if isinstance(row.get(key), (int, float)):
                    row_used = float(row[key])
                    break
        if row_used is None:
            row_used = 0.0
        used += row_used

        row_gross = row.get("grossAmount", row.get("gross_amount", 0))
        row_discount = row.get("discountAmount", row.get("discount_amount", 0))
        row_net = row.get("netAmount", row.get("net_amount", 0))
        gross += float(row_gross) if isinstance(row_gross, (int, float)) else 0.0
        discount += (
            float(row_discount) if isinstance(row_discount, (int, float)) else 0.0
        )
        net_amount += float(row_net) if isinstance(row_net, (int, float)) else 0.0
        parsed_rows.append(
            {
                "product": row.get("product") or row.get("productName"),
                "sku": row.get("sku") or row.get("skuName"),
                "used": row_used,
                "gross_amount": row_gross,
                "discount_amount": row_discount,
                "net_amount": row_net,
            }
        )

    return {
        "used": used,
        "gross_amount": gross,
        "discount_amount": discount,
        "net_amount": net_amount,
        "billing_rows": parsed_rows,
    }


def _is_org_promo_window(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    return PROMO_START <= now < PROMO_END


def _personal_ai_credit_allowance(*sources: Optional[Dict[str, Any]]) -> Optional[int]:
    """Infer personal monthly AI credit allowance from provider-owned data."""
    for source in sources:
        if not source:
            continue
        for key in ("copilot_plan", "plan", "plan_type", "sku", "subscription"):
            plan = str(source.get(key, "")).lower().replace(" ", "_")
            if plan in PERSONAL_AI_CREDIT_ALLOWANCES:
                return PERSONAL_AI_CREDIT_ALLOWANCES[plan]
            if "pro+" in plan or "pro_plus" in plan:
                return PERSONAL_AI_CREDIT_ALLOWANCES["pro+"]
            if "pro" in plan and "enterprise" not in plan:
                return PERSONAL_AI_CREDIT_ALLOWANCES["pro"]
            if "max" in plan:
                return PERSONAL_AI_CREDIT_ALLOWANCES["max"]
    return None


def _org_ai_credit_allowance(
    seats: Optional[int], plan: Optional[str], now: Optional[datetime] = None
) -> Optional[int]:
    """Infer org pooled monthly AI credit allowance."""
    if not isinstance(seats, int) or seats <= 0:
        return None
    plan_key = str(plan or "").lower().replace(" ", "_")
    if "enterprise" in plan_key:
        plan_key = "enterprise"
    elif "business" in plan_key:
        plan_key = "business"
    else:
        return None
    base = ORG_AI_CREDIT_ALLOWANCES.get(plan_key)
    if _is_org_promo_window(now):
        base = ORG_PROMO_AI_CREDIT_ALLOWANCES.get(plan_key, base)
    if not base:
        return None
    return seats * base


def _build_ai_credit_quota(
    name: str,
    display_name: str,
    used: float,
    allowance: Optional[int],
    reset: str,
    **metadata,
) -> Dict[str, Any]:
    """Build a display-generic quota dict for AI credits."""
    quota = {
        "name": name,
        "display_name": display_name,
        "used": used,
        "reset": reset,
        "source_type": "GitHub Copilot",
        "billing_model": "ai_credits",
    }
    if allowance and allowance > 0:
        remaining = max(0.0, allowance - used)
        used_pct = max(0.0, min(100.0, (used / allowance) * 100))
        quota.update(
            {
                "limit": allowance,
                "remaining": remaining,
                "used_pct": used_pct,
                "remaining_pct": max(0.0, 100.0 - used_pct),
            }
        )
    else:
        quota.update(
            {
                "used_pct": 0.0,
                "remaining_pct": 100.0,
                "show_progress": False,
                "allowance_unknown": True,
            }
        )
    quota.update(metadata)
    return quota


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

        token, token_source, github_account = self._prompt_for_token(display_manager)
        org = self._prompt_for_org(display_manager, token)
        return self.login(
            token=token,
            organization=org,
            token_source=token_source,
            github_account=github_account,
        )

    def _prompt_for_token(self, display_manager) -> Tuple[str, str, Optional[str]]:
        """Try gh CLI token first, then prompt user."""
        import click

        try:
            token = self._get_gh_token()
            if token:
                display_manager.console.print("[green]✓ GitHub CLI token found[/green]")
                github_account = None
                gh_accounts = self._discover_gh_accounts()
                if len(gh_accounts) > 1:
                    github_account = self._select_gh_account_from_list(
                        display_manager, gh_accounts
                    )
                    if not github_account:
                        raise Exception("A GitHub account selection is required")
                    selected_token = self._get_gh_token_for_user(github_account)
                    if not selected_token:
                        raise Exception(
                            f"GitHub CLI token unavailable for account {github_account}"
                        )
                    token = selected_token
                elif len(gh_accounts) == 1:
                    github_account = gh_accounts[0]
                return token, "gh_cli", github_account
            display_manager.console.print(
                "[yellow]⚠ Could not load GitHub CLI token[/yellow]"
            )
            token = click.prompt("Enter GitHub token (or press Enter to skip)")
            if not token:
                raise Exception("GitHub token is required")
            return token, "manual", None
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

    @staticmethod
    def _select_gh_account_from_list(display_manager, accounts: list) -> Optional[str]:
        """Display gh account list and let user pick one."""
        import click

        display_manager.console.print(
            "\n[bold blue]Select a GitHub account:[/bold blue]"
        )
        for i, account in enumerate(accounts, 1):
            display_manager.console.print(f"{i}) {account}")

        choice = click.prompt("Enter choice", default=1)
        try:
            choice = int(choice)
        except (TypeError, ValueError):
            choice = 0
        if 1 <= choice <= len(accounts):
            return accounts[choice - 1]
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
        token_source = kwargs.get("token_source", "manual")
        github_account = kwargs.get("github_account")

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
        if github_account:
            account_data["github_account"] = github_account

        if token_source == "gh_cli":
            account_data["githubAuthSource"] = "gh_cli"
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

    def _discover_gh_accounts(self) -> List[str]:
        """Discover all logged-in GitHub CLI accounts for github.com."""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=GH_AUTH_STATUS_TIMEOUT,
            )
            if result.returncode != 0:
                return []

            accounts = []
            pattern = re.compile(r"Logged in to github\.com account\s+([^\s(]+)")
            for line in result.stdout.splitlines():
                match = pattern.search(line)
                if match:
                    accounts.append(match.group(1))
            return accounts
        except Exception:
            return []

    def _get_gh_token_for_user(self, user: str) -> Optional[str]:
        """Attempt to retrieve a GitHub CLI token for a specific account."""
        try:
            result = subprocess.run(
                ["gh", "auth", "token", "--user", user],
                capture_output=True,
                text=True,
                timeout=DEFAULT_GH_CLI_TIMEOUT,
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

        return self._fetch_single_account_quotas()

    def _fetch_single_account_quotas(self) -> List[Dict[str, Any]]:
        start = time.perf_counter()
        email = self.account_data.get("email", "unknown")
        logger.debug(
            f"[github_copilot] fetch_quotas start account={email} org={self.organization or '-'}"
        )

        if not self.has_time_remaining():
            return []

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

        personal_method = self.account_data.get("preferredPersonalQuotaMethod")
        if personal_method:
            self.record_timing(
                "github_copilot_personal_method",
                0.0,
                method=personal_method,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[github_copilot] fetch_quotas done account={email} elapsed_ms={elapsed_ms:.1f} "
            f"quota_count={len(results)}"
        )
        self.record_timing("github_copilot_total", elapsed_ms)
        return results

    # --- Personal quota fetching ---

    def _fetch_personal_copilot_quota(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Fetch personal Copilot quota using AI credits billing only."""
        start = time.perf_counter()
        quota = self._try_personal_via_ai_credits(headers)
        if quota:
            self.account_data["preferredPersonalQuotaMethod"] = "ai_credits"
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] personal method=ai_credits elapsed_ms={elapsed_ms:.1f}"
            )
            return quota

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[github_copilot] personal method=none elapsed_ms={elapsed_ms:.1f}"
        )
        return None

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
        """Legacy premium request quota is no longer returned."""
        return None

    def _github_login(self, headers: Dict[str, str]) -> Optional[str]:
        """Return validated GitHub login for public billing paths."""
        login = self.account_data.get("email") or self.github_login
        if login and login != "GitHub User" and "@" not in str(login):
            return str(login)
        try:
            resp = requests.get(
                "https://api.github.com/user",
                headers=headers,
                timeout=self.time_remaining(DEFAULT_API_TIMEOUT),
            )
            if resp.status_code == 200:
                return resp.json().get("login")
        except Exception:
            pass
        return None

    def _fetch_billing_credit_usage(
        self, headers: Dict[str, str], owner: str, is_org: bool
    ) -> Optional[Dict[str, Any]]:
        """Fetch and parse public billing usage/summary APIs; summary wins."""
        usage_url, summary_url = _billing_usage_urls(owner, is_org)
        start_date, end_date = _current_month_window()
        params = {"start_date": start_date, "end_date": end_date}
        parsed_usage = None

        for url, source in ((summary_url, "summary"), (usage_url, "usage")):
            if not self.has_time_remaining():
                return parsed_usage
            try:
                resp = requests.get(
                    url,
                    headers=headers,
                    timeout=self.time_remaining(DEFAULT_API_TIMEOUT),
                    params=params,
                )
                if resp.status_code != 200:
                    continue
                parsed = _parse_ai_credit_billing_payload(resp.json())
                if parsed:
                    parsed["billing_source"] = source
                    parsed["billing_window"] = {"start": start_date, "end": end_date}
                    if source == "summary":
                        return parsed
                    parsed_usage = parsed
            except Exception:
                continue
        return parsed_usage

    def _try_personal_via_ai_credits(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Try June 2026+ public user billing AI credits APIs."""
        start = time.perf_counter()
        username = self._github_login(headers)
        if not username:
            return None
        billing = self._fetch_billing_credit_usage(headers, username, is_org=False)
        if not billing:
            return None

        internal = self._fetch_copilot_internal_user(headers)
        allowance = _personal_ai_credit_allowance(internal, self.account_data)
        quota = _build_ai_credit_quota(
            "GitHub Copilot Personal",
            "Personal",
            billing["used"],
            allowance,
            _next_month_reset_iso(),
            **{k: v for k, v in billing.items() if k != "used"},
        )
        self.record_timing(
            "github_copilot_personal_ai_credits",
            (time.perf_counter() - start) * 1000,
        )
        return quota

    def _extract_premium_quota(self, internal_data: dict) -> Optional[Dict[str, Any]]:
        """Legacy premium interaction quotas are intentionally ignored."""
        return None

    def _try_personal_via_billing(
        self, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Legacy personal Copilot billing seat quota is no longer returned."""
        return None

    def _try_personal_via_gh_cli(self) -> Optional[Dict[str, Any]]:
        """Legacy gh CLI quota fallback is no longer returned."""
        return None

    # --- Org quota fetching ---

    def _fetch_org_copilot_quota(
        self, headers: Dict[str, str], organization: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch organization Copilot quota using AI credits billing only."""
        start = time.perf_counter()
        if not self.has_time_remaining():
            return None
        try:
            ai_credit_quota = self._try_org_via_ai_credits(headers, organization)
            if ai_credit_quota:
                return ai_credit_quota

            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] org ai_credits unavailable elapsed_ms={elapsed_ms:.1f}"
            )
            return _build_org_error(
                organization, "Could not fetch AI credits billing usage for this org"
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(
                f"[github_copilot] org error elapsed_ms={elapsed_ms:.1f} err={e}"
            )
            return _build_org_error(organization, f"Error fetching org quota: {str(e)}")

    def _try_org_via_ai_credits(
        self, headers: Dict[str, str], organization: str
    ) -> Optional[Dict[str, Any]]:
        """Try public organization billing AI credits APIs."""
        start = time.perf_counter()
        billing = self._fetch_billing_credit_usage(headers, organization, is_org=True)
        if not billing:
            return None

        seats = None
        plan = None
        try:
            resp = requests.get(
                f"https://api.github.com/orgs/{organization}/copilot/billing",
                headers=headers,
                timeout=self.time_remaining(DEFAULT_API_TIMEOUT),
            )
            if resp.status_code == 200:
                org_data = resp.json()
                seat_breakdown = org_data.get("seat_breakdown", {})
                total = seat_breakdown.get("total")
                seats = total if isinstance(total, int) else None
                plan = org_data.get("plan_type") or org_data.get("plan")
        except Exception:
            pass

        allowance = _org_ai_credit_allowance(seats, plan)
        quota = _build_ai_credit_quota(
            f"GitHub Copilot Org ({organization})",
            organization,
            billing["used"],
            allowance,
            _next_month_reset_iso(),
            seats=seats,
            plan_type=plan,
            **{k: v for k, v in billing.items() if k != "used"},
        )
        self.record_timing(
            "github_copilot_org_ai_credits",
            (time.perf_counter() - start) * 1000,
        )
        return quota

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

        if not self.has_time_remaining():
            return None

        internal_headers = dict(headers)
        internal_headers["Authorization"] = f"token {self.github_token}"
        internal_headers["X-GitHub-Api-Version"] = "2025-04-01"

        try:
            resp = requests.get(
                "https://api.github.com/copilot_internal/user",
                headers=internal_headers,
                timeout=self.time_remaining(DEFAULT_API_TIMEOUT),
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
        """Legacy org premium request quota is no longer returned."""
        return None

    def _fetch_member_copilot_quota(
        self, headers: Dict[str, str], organization: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch member status only; do not return legacy quota data."""
        try:
            username = self._user_login_cache
            if not username:
                user_resp = requests.get(
                    "https://api.github.com/user",
                    headers=headers,
                    timeout=self.time_remaining(DEFAULT_API_TIMEOUT),
                )
                if user_resp.status_code != 200:
                    return None
                username = user_resp.json().get("login")
                self._user_login_cache = username
            if not username:
                return None

            requests.get(
                f"https://api.github.com/orgs/{organization}/members/{username}/copilot",
                headers=headers,
                timeout=self.time_remaining(DEFAULT_API_TIMEOUT),
            )
        except Exception:
            pass
        return None

    def _get_copilot_usage_via_gh(self) -> Optional[Dict[str, Any]]:
        """Legacy gh CLI quota fallback is no longer used."""
        return None

    def _try_gh_internal_usage(self) -> Optional[Dict[str, Any]]:
        """Legacy gh copilot_internal premium usage is no longer returned."""
        return None

    @staticmethod
    def _try_gh_billing_usage() -> Optional[Dict[str, Any]]:
        """Legacy gh Copilot billing seat usage is no longer returned."""
        return None
