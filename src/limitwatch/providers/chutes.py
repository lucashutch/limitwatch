import requests
import concurrent.futures
import logging
from time import perf_counter
from datetime import datetime, time, timedelta, timezone
from typing import List, Dict, Any, Tuple, Optional
from .base import BaseProvider

logger = logging.getLogger(__name__)


# --- Helper functions ---


def _get_next_reset_iso() -> str:
    """Calculate the next 00:00 UTC reset time."""
    now = datetime.now(timezone.utc)
    next_reset = datetime.combine(
        now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    return next_reset.isoformat().replace("+00:00", "Z")


def _build_quota_result(
    chute_id: str, limit: int, used: int, reset: str
) -> Optional[Dict[str, Any]]:
    """Build a quota result dict from usage data, or None if limit is 0."""
    if limit <= 0:
        return None

    remaining_pct = max(0, (limit - used) / limit) * 100
    remaining = int(limit - used)

    if chute_id == "*":
        display_name = f"Quota ({remaining}/{int(limit)})"
    else:
        display_name = f"Quota: {chute_id[:8]}... ({remaining}/{int(limit)})"

    return {
        "name": f"Chutes Quota ({chute_id})",
        "display_name": display_name,
        "remaining_pct": remaining_pct,
        "remaining": remaining,
        "limit": int(limit),
        "used": int(used),
        "reset": reset,
        "source_type": "Chutes",
    }


def _make_chutes_headers(api_key: str) -> Dict[str, str]:
    """Build standard Chutes API headers."""
    return {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }


class ChutesProvider(BaseProvider):
    BASE_URL = "https://api.chutes.ai"
    FETCH_TIMEOUT = 1.5

    def __init__(self, account_data: Dict[str, Any]):
        super().__init__(account_data)
        self.api_key = account_data.get("apiKey")

    @property
    def provider_name(self) -> str:
        return "Chutes"

    @property
    def source_priority(self) -> int:
        return 0

    @property
    def primary_color(self) -> str:
        return "yellow"

    @property
    def short_indicator(self) -> str:
        return "C"

    def get_color(self, quota: Dict[str, Any]) -> str:
        return "yellow"

    def interactive_login(self, display_manager: Any) -> Dict[str, Any]:
        """Perform an interactive login flow with the user."""
        import click

        api_key = click.prompt("Enter Chutes.ai API key", hide_input=True)
        if api_key:
            api_key = api_key.strip()
        return self.login(api_key=api_key)

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        return quotas

    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        name = quota.get("name", "")
        if "Credits" in name:
            return 0, 0, name
        if "Balance" in name:
            return 0, 1, name
        return 1, 0, name

    def login(self, **kwargs) -> Dict[str, Any]:
        """Perform Chutes.ai login using an API key and return account data."""
        api_key = kwargs.get("api_key")
        if not api_key:
            raise Exception("API key is required for Chutes.ai login")

        headers = _make_chutes_headers(api_key)
        resp = requests.get(f"{self.BASE_URL}/users/me", headers=headers, timeout=10)
        if resp.status_code != 200:
            raise Exception(f"Failed to authenticate with Chutes.ai: {resp.text}")

        data = resp.json()
        identifier = (
            data.get("email") or data.get("username") or data.get("id") or "Chutes User"
        )

        return {
            "type": "chutes",
            "email": str(identifier),
            "apiKey": api_key,
            "services": ["CHUTES"],
        }

    def fetch_quotas(self) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []

        headers = _make_chutes_headers(self.api_key)
        next_reset = _get_next_reset_iso()
        start = perf_counter()
        email = self.account_data.get("email", "unknown")
        logger.debug(f"[chutes] fetch_quotas start account={email}")
        strategy = self.account_data.get("chutesQuotaStrategy", "auto")
        logger.debug(f"[chutes] strategy={strategy}")

        if not self.has_time_remaining():
            return []

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                balance_future = executor.submit(self._fetch_balance, headers)
                fallback_future = executor.submit(
                    self._fetch_fallback_quota, headers, next_reset
                )

                balance_item = balance_future.result()
                fallback_quota = fallback_future.result()

            list_quotas: List[Dict[str, Any]] = []
            if strategy == "full":
                list_quotas = self._fetch_quota_list(headers, next_reset)
                if list_quotas:
                    self.account_data["chutesQuotaStrategy"] = "full"
                    self.record_timing("chutes_strategy", 0.0, mode="full")
            elif strategy == "auto":
                if not fallback_quota and self.has_time_remaining():
                    list_quotas = self._fetch_quota_list(headers, next_reset)
                    if list_quotas:
                        self.account_data["chutesQuotaStrategy"] = "full"
                        self.record_timing("chutes_strategy", 0.0, mode="full")
                elif fallback_quota:
                    self.account_data["chutesQuotaStrategy"] = "fallback"
                    self.record_timing("chutes_strategy", 0.0, mode="fallback")
            elif fallback_quota:
                self.account_data["chutesQuotaStrategy"] = "fallback"
                self.record_timing("chutes_strategy", 0.0, mode="fallback")
            else:
                self.record_timing("chutes_strategy", 0.0, mode="auto")

            results: List[Dict[str, Any]] = []
            if balance_item:
                results.append(balance_item)
            if list_quotas:
                results.extend(list_quotas)
            elif fallback_quota:
                results.append(fallback_quota)

            logger.debug(
                f"[chutes] selection list={bool(list_quotas)} fallback={bool(fallback_quota)} "
                f"balance={bool(balance_item)}"
            )

            elapsed_ms = (perf_counter() - start) * 1000
            logger.debug(
                f"[chutes] fetch_quotas done account={email} elapsed_ms={elapsed_ms:.1f} "
                f"quota_count={len(results)}"
            )
            self.record_timing("chutes_total", elapsed_ms)
        except Exception as e:
            if "Unauthorized" in str(e):
                raise
            logger.debug(f"[chutes] fetch_quotas error account={email} err={e}")
            return []
        return results

    def _fetch_balance(self, headers: Dict) -> Optional[Dict[str, Any]]:
        """Fetch user balance and return credits quota item if positive."""
        start = perf_counter()
        if not self.has_time_remaining():
            return None
        resp = requests.get(
            f"{self.BASE_URL}/users/me",
            headers=headers,
            timeout=self.time_remaining(self.FETCH_TIMEOUT),
        )
        if resp.status_code in (401, 403):
            raise Exception("Unauthorized: Invalid Chutes.ai API key")
        if resp.status_code == 200:
            balance = resp.json().get("balance", 0.0)
            if balance > 0:
                elapsed_ms = (perf_counter() - start) * 1000
                logger.debug(
                    f"[chutes] _fetch_balance success elapsed_ms={elapsed_ms:.1f}"
                )
                self.record_timing("chutes_balance", elapsed_ms)
                return {
                    "name": "Chutes Credits",
                    "display_name": f"Credits: ${balance:.2f}",
                    "remaining_pct": 100.0,
                    "reset": "N/A",
                    "source_type": "Chutes",
                    "endpoint": "balance",
                    "show_progress": False,
                }
        elapsed_ms = (perf_counter() - start) * 1000
        logger.debug(
            f"[chutes] _fetch_balance status={resp.status_code} elapsed_ms={elapsed_ms:.1f}"
        )
        self.record_timing("chutes_balance", elapsed_ms, status=resp.status_code)
        return None

    def _fetch_quota_list(self, headers: Dict, next_reset: str) -> List[Dict[str, Any]]:
        """Fetch quota list and usage for each, returning quota items."""
        start = perf_counter()
        if not self.has_time_remaining():
            return []
        resp = requests.get(
            f"{self.BASE_URL}/users/me/quotas",
            headers=headers,
            timeout=self.time_remaining(self.FETCH_TIMEOUT),
        )
        if resp.status_code != 200:
            elapsed_ms = (perf_counter() - start) * 1000
            logger.debug(
                f"[chutes] _fetch_quota_list status={resp.status_code} elapsed_ms={elapsed_ms:.1f}"
            )
            return []

        quotas_list = resp.json()
        if not isinstance(quotas_list, list):
            return []

        usage_timeout = self.time_remaining(self.FETCH_TIMEOUT)
        if usage_timeout <= 0:
            return []
        self.record_timing("chutes_usage_timeout", 0.0, timeout_s=usage_timeout)
        usages = self._fetch_usages_parallel(quotas_list, headers, usage_timeout)
        results = []

        for usage in usages:
            if not usage:
                continue
            quota = _build_quota_result(
                chute_id=usage.get("chute_id") or "Unknown",
                limit=usage.get("quota") or usage.get("limit") or 0,
                used=usage.get("used", 0),
                reset=next_reset,
            )
            if quota:
                results.append(quota)

        elapsed_ms = (perf_counter() - start) * 1000
        logger.debug(
            f"[chutes] _fetch_quota_list done elapsed_ms={elapsed_ms:.1f} "
            f"entries={len(quotas_list)} quotas={len(results)}"
        )
        self.record_timing("chutes_quota_list", elapsed_ms)
        return results

    @staticmethod
    def _fetch_usages_parallel(
        quotas_list: List[Dict], headers: Dict, timeout: float
    ) -> List[Optional[Dict]]:
        """Fetch usage for each quota entry in parallel."""
        start = perf_counter()

        def fetch_one(q):
            cid = q.get("chute_id") or q.get("id")
            if not cid:
                return None
            try:
                url = f"https://api.chutes.ai/users/me/quota_usage/{cid}"
                resp = requests.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    d = resp.json()
                    if "chute_id" not in d:
                        d["chute_id"] = cid
                    return d
            except Exception:
                pass
            return None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(quotas_list) or 1, 4)
        ) as executor:
            result = list(executor.map(fetch_one, quotas_list))

        elapsed_ms = (perf_counter() - start) * 1000
        logger.debug(
            f"[chutes] _fetch_usages_parallel done elapsed_ms={elapsed_ms:.1f} "
            f"requested={len(quotas_list)}"
        )
        return result

    def _fetch_fallback_quota(
        self, headers: Dict, next_reset: str
    ) -> Optional[Dict[str, Any]]:
        """Fallback: fetch /users/me/quota_usage/me and return one quota item."""
        start = perf_counter()

        if not self.has_time_remaining():
            return None

        resp = requests.get(
            f"{self.BASE_URL}/users/me/quota_usage/me",
            headers=headers,
            timeout=self.time_remaining(self.FETCH_TIMEOUT),
        )
        if resp.status_code != 200:
            elapsed_ms = (perf_counter() - start) * 1000
            logger.debug(
                f"[chutes] _fetch_fallback_quota status={resp.status_code} elapsed_ms={elapsed_ms:.1f}"
            )
            return None

        data = resp.json()
        quota = _build_quota_result(
            chute_id=data.get("chute_id") or "*",
            limit=data.get("quota") or data.get("limit") or 0,
            used=data.get("used", 0),
            reset=next_reset,
        )
        elapsed_ms = (perf_counter() - start) * 1000
        logger.debug(
            f"[chutes] _fetch_fallback_quota done elapsed_ms={elapsed_ms:.1f} "
            f"has_quota={bool(quota)}"
        )
        self.record_timing("chutes_fallback", elapsed_ms)
        return quota
