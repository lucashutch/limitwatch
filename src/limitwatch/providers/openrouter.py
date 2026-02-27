"""OpenRouter provider – monitors credit balance.

Endpoint discovery order:
  1. GET /api/v1/credits  (management key) – returns total_credits / total_usage
  2. GET /api/v1/auth/key (regular key)   – returns label / usage / limit
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .base import BaseProvider

logger = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"
FETCH_TIMEOUT = 2


def _make_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _pct(remaining: float, limit: float) -> float:
    if limit <= 0:
        return 100.0
    return max(0.0, min(100.0, remaining / limit * 100))


class OpenRouterProvider(BaseProvider):
    def __init__(self, account_data: Dict[str, Any]):
        super().__init__(account_data)
        self.api_key: Optional[str] = account_data.get("apiKey")

    # ------------------------------------------------------------------
    # BaseProvider identity
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "OpenRouter"

    @property
    def source_priority(self) -> int:
        return 0

    @property
    def primary_color(self) -> str:
        return "cyan"

    @property
    def short_indicator(self) -> str:
        return "R"

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def get_color(self, quota: Dict[str, Any]) -> str:
        pct = quota.get("remaining_pct", 100.0)
        if pct >= 50:
            return "cyan"
        if pct >= 20:
            return "yellow"
        return "red"

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        return quotas

    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        return (0, 0, quota.get("name", ""))

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self, **kwargs) -> Dict[str, Any]:
        """Validate the API key against /auth/key and return account data.

        Optional kwargs:
          api_key (str): The OpenRouter API key.
          name    (str): A friendly display name. If omitted, the key's label
                         from the API is used (which may be a redacted key string).
        """
        api_key = kwargs.get("api_key", "").strip()
        if not api_key:
            raise ValueError("API key is required for OpenRouter login")

        resp = requests.get(
            f"{BASE_URL}/auth/key",
            headers=_make_headers(api_key),
            timeout=10,
        )
        if resp.status_code in (401, 403):
            raise ValueError(f"Invalid OpenRouter API key: {resp.text}")
        resp.raise_for_status()

        data = resp.json().get("data", {})
        api_label = data.get("label") or data.get("name") or "OpenRouter Key"

        # Prefer an explicit name kwarg; fall back to the API label.
        custom_name = (kwargs.get("name") or "").strip()
        identifier = custom_name if custom_name else api_label

        return {
            "type": "openrouter",
            "email": identifier,
            "apiKey": api_key,
            "services": ["OPENROUTER"],
        }

    def interactive_login(self, display_manager: Any) -> Dict[str, Any]:
        import click

        api_key = click.prompt("Enter OpenRouter API key", hide_input=True)
        account = self.login(api_key=api_key)

        # If OpenRouter returned a redacted key as the label (e.g. "sk-or-v1-abc...xyz"),
        # the user never set a name for this key on the dashboard. Offer to set one now.
        current_label = account["email"]
        if "..." in current_label:
            friendly = click.prompt(
                f"Key validated ({current_label}). Enter a friendly name for this account",
                default=current_label,
            ).strip()
            if friendly and friendly != current_label:
                account["email"] = friendly

        return account

    # ------------------------------------------------------------------
    # Quota fetching
    # ------------------------------------------------------------------

    def fetch_quotas(self) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []

        headers = _make_headers(self.api_key)
        email = self.account_data.get("email", "unknown")
        logger.debug(f"[openrouter] fetch_quotas account={email}")

        start = time.perf_counter()

        if not self.has_time_remaining():
            return []

        # Try management-key credits endpoint first
        result = self._fetch_credits(headers)
        if result is not None:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_timing("openrouter_total", elapsed_ms)
            return [result]

        # Fall back to regular key-info endpoint
        result = self._fetch_key_info(headers)
        if result is not None:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_timing("openrouter_total", elapsed_ms)
            return [result]

        elapsed_ms = (time.perf_counter() - start) * 1000
        self.record_timing("openrouter_total", elapsed_ms)
        return []

    def _fetch_credits(self, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Try GET /credits (management key). Returns None if not authorised."""
        start = time.perf_counter()
        if not self.has_time_remaining():
            return None
        try:
            resp = requests.get(
                f"{BASE_URL}/credits",
                headers=headers,
                timeout=self.time_remaining(FETCH_TIMEOUT),
            )
            if resp.status_code in (401, 403):
                logger.debug("[openrouter] /credits not authorised, falling back")
                return None
            resp.raise_for_status()

            data = resp.json().get("data", {})
            total = float(data.get("total_credits", 0.0))
            used = float(data.get("total_usage", 0.0))
            remaining = max(0.0, total - used)
            pct = _pct(remaining, total)

            logger.debug(
                f"[openrouter] credits total={total:.4f} used={used:.4f} remaining={remaining:.4f}"
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_timing("openrouter_credits", elapsed_ms)
            return {
                "name": "OpenRouter Credits",
                "display_name": f"Credits: ${remaining:.2f} remaining",
                "show_progress": False,
                "remaining_pct": pct,
                "remaining": remaining,
                "limit": total,
                "used": used,
                "source_type": "OpenRouter",
                "endpoint": "credits",
            }
        except Exception as exc:
            logger.debug(f"[openrouter] _fetch_credits error: {exc}")
            return None

    def _fetch_key_info(self, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Try GET /auth/key (regular key). Surfaces usage vs optional limit."""
        start = time.perf_counter()
        if not self.has_time_remaining():
            return None
        try:
            resp = requests.get(
                f"{BASE_URL}/auth/key",
                headers=headers,
                timeout=self.time_remaining(FETCH_TIMEOUT),
            )
            if resp.status_code in (401, 403):
                raise ValueError("Unauthorized: Invalid OpenRouter API key")
            resp.raise_for_status()

            data = resp.json().get("data", {})
            usage = float(data.get("usage", 0.0))
            limit: Optional[float] = data.get("limit")
            label = data.get("label") or data.get("name") or "Key"

            if limit is not None:
                limit = float(limit)
                remaining = max(0.0, limit - usage)
                pct = _pct(remaining, limit)
                display = f"{label}: ${remaining:.2f} remaining"
            else:
                # No credit limit set – show spend only
                remaining = 0.0
                pct = 100.0
                limit = 0.0
                display = f"{label}: ${usage:.2f} spent"

            logger.debug(
                f"[openrouter] key_info label={label} usage={usage:.4f} limit={limit}"
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_timing("openrouter_key", elapsed_ms)
            return {
                "name": "OpenRouter Key",
                "display_name": display,
                "show_progress": False,
                "remaining_pct": pct,
                "remaining": remaining,
                "limit": limit,
                "used": usage,
                "source_type": "OpenRouter",
                "endpoint": "auth/key",
            }
        except ValueError:
            raise
        except Exception as exc:
            logger.debug(f"[openrouter] _fetch_key_info error: {exc}")
            return None
