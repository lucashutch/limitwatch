"""OpenAI Codex provider – monitors Codex plan usage quotas.

Token discovery order:
  1. OpenCode  (~/.local/share/opencode/auth.json)
  2. Codex CLI (~/.codex/auth.json)
  3. Device-code auth flow (fallback)
"""

import base64
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from .base import BaseProvider

logger = logging.getLogger(__name__)

# --- Constants ---

OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_ISSUER = "https://auth.openai.com"
CHATGPT_BACKEND = "https://chatgpt.com/backend-api"

TOKEN_REFRESH_URL = f"{OPENAI_ISSUER}/oauth/token"
DEVICE_CODE_URL = f"{OPENAI_ISSUER}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{OPENAI_ISSUER}/api/accounts/deviceauth/token"
USAGE_URL = f"{CHATGPT_BACKEND}/wham/usage"
USER_INFO_URL = f"{CHATGPT_BACKEND}/me"  # Endpoint to fetch user profile

OPENCODE_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
CODEX_CLI_AUTH_PATH = Path.home() / ".codex" / "auth.json"

DEFAULT_TIMEOUT = 10
FETCH_TIMEOUT = 1.5
DEVICE_POLL_TIMEOUT = 900  # 15 minutes


# --- Helpers ---


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read a JSON file, return None on any failure."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _discover_opencode_token(path: Path = OPENCODE_AUTH_PATH) -> Optional[str]:
    """Try to read an access_token from OpenCode's auth.json."""
    data = _read_json(path)
    if not data:
        return None
    # OpenCode stores per-provider credentials; look for OpenAI
    # Format may vary; common shapes:
    #   {"access_token": "...", "refresh_token": "..."}
    #   {"accounts": {"openai": {"access_token": "..."}}}
    #   {"providers": {"openai": {"access_token": "..."}}}
    for key in ("access_token",):
        if isinstance(data.get(key), str) and data[key]:
            return data[key]
    # Nested lookup
    for container_key in ("accounts", "providers"):
        container = data.get(container_key, {})
        if isinstance(container, dict):
            for provider_key in ("openai", "OpenAI", "chatgpt"):
                entry = container.get(provider_key, {})
                if isinstance(entry, dict) and entry.get("access_token"):
                    return entry["access_token"]
    return None


def _discover_codex_cli_token(
    path: Path = CODEX_CLI_AUTH_PATH,
) -> Optional[Dict[str, str]]:
    """Read tokens from Codex CLI's auth.json.

    Returns dict with 'access_token' and optionally 'refresh_token'.
    """
    data = _read_json(path)
    if not data:
        return None

    # Codex CLI format: {tokens: {access_token, refresh_token, ...}}
    tokens = data.get("tokens", data)
    if isinstance(tokens, dict) and tokens.get("access_token"):
        result: Dict[str, str] = {"access_token": tokens["access_token"]}
        if tokens.get("refresh_token"):
            result["refresh_token"] = tokens["refresh_token"]
        return result
    return None


def _refresh_access_token(refresh_token: str) -> Optional[Dict[str, str]]:
    """Exchange a refresh token for a fresh access token."""
    try:
        resp = requests.post(
            TOKEN_REFRESH_URL,
            json={
                "client_id": OPENAI_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid profile email",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
            }
    except Exception as e:
        logger.debug(f"[openai] token refresh failed: {e}")
    return None


def _run_device_code_flow(display_manager: Any = None) -> Dict[str, str]:
    """Run the OpenAI device-code auth flow interactively.

    Returns dict with 'access_token' and 'refresh_token'.
    Raises Exception on failure or timeout.
    """
    # Step 1: Request user code
    resp = requests.post(
        DEVICE_CODE_URL,
        json={"client_id": OPENAI_CLIENT_ID},
        headers={"Content-Type": "application/json"},
        timeout=DEFAULT_TIMEOUT,
    )
    if not resp.ok:
        raise Exception(f"Device code request failed: HTTP {resp.status_code}")

    code_data = resp.json()
    user_code = code_data.get("user_code") or code_data.get("usercode")
    device_auth_id = code_data["device_auth_id"]
    interval = int(code_data.get("interval", 5))

    verification_url = f"{OPENAI_ISSUER}/codex/device"

    # Display instructions
    if display_manager:
        display_manager.console.print(
            f"\n[bold blue]OpenAI Device Authorization[/bold blue]\n"
            f"1. Open this URL in your browser:\n"
            f"   [link={verification_url}]{verification_url}[/link]\n"
            f"2. Enter code: [bold]{user_code}[/bold]\n"
        )
    else:
        print(
            f"\nOpenAI Device Authorization\n"
            f"1. Open: {verification_url}\n"
            f"2. Enter code: {user_code}\n"
        )

    # Step 2: Poll for token
    start = time.monotonic()
    while time.monotonic() - start < DEVICE_POLL_TIMEOUT:
        time.sleep(interval)
        poll_resp = requests.post(
            DEVICE_TOKEN_URL,
            json={"device_auth_id": device_auth_id, "user_code": user_code},
            headers={"Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT,
        )
        if poll_resp.ok:
            poll_data = poll_resp.json()
            authorization_code = poll_data.get("authorization_code")
            code_verifier = poll_data.get("code_verifier")

            if authorization_code and code_verifier:
                # Exchange authorization code for tokens
                return _exchange_code_for_tokens(authorization_code, code_verifier)
            # Some flows return tokens directly
            if poll_data.get("access_token"):
                return {
                    "access_token": poll_data["access_token"],
                    "refresh_token": poll_data.get("refresh_token", ""),
                }
        elif poll_resp.status_code not in (403, 404):
            raise Exception(f"Device auth failed: HTTP {poll_resp.status_code}")

    raise Exception("Device code auth timed out (15 minutes)")


def _exchange_code_for_tokens(
    authorization_code: str, code_verifier: str
) -> Dict[str, str]:
    """Exchange an authorization code + PKCE verifier for tokens."""
    redirect_uri = f"{OPENAI_ISSUER}/deviceauth/callback"
    resp = requests.post(
        f"{OPENAI_ISSUER}/oauth/token",
        json={
            "grant_type": "authorization_code",
            "client_id": OPENAI_CLIENT_ID,
            "code": authorization_code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if not resp.ok:
        raise Exception(f"Token exchange failed: HTTP {resp.status_code}")
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
    }


def _format_reset_time(reset_at: Any) -> str:
    """Convert a reset timestamp (epoch seconds or ISO str) to a human-readable string."""
    try:
        if isinstance(reset_at, (int, float)):
            dt = datetime.fromtimestamp(reset_at, tz=timezone.utc)
        elif isinstance(reset_at, str):
            dt = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
        else:
            return str(reset_at)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(reset_at)


def _build_quota(
    name: str,
    display_name: str,
    remaining_pct: float,
    used_pct: float,
    reset: str,
    **extras: Any,
) -> Dict[str, Any]:
    """Build a standard quota dict."""
    quota: Dict[str, Any] = {
        "name": name,
        "display_name": display_name,
        "remaining_pct": remaining_pct,
        "used_pct": used_pct,
        "reset": reset,
        "source_type": "OpenAI Codex",
    }
    quota.update(extras)
    return quota


def _first_non_empty_identity(*values: Any) -> Optional[str]:
    """Return the first usable user-facing identity value."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if _is_usable_identity(text):
            return text
    return None


def _is_usable_identity(value: str) -> bool:
    """Return True for user-facing identifiers; reject opaque provider IDs."""
    text = value.strip()
    if not text:
        return False

    lower = text.lower()
    if lower in {"openai user", "unknown", "none", "null"}:
        return False

    # Reject common opaque OAuth/Auth0-style subject identifiers.
    if "|" in text:
        provider_prefix = text.split("|", 1)[0].lower()
        if provider_prefix in {
            "google-oauth2",
            "auth0",
            "oauth",
            "samlp",
            "github",
            "microsoft",
        }:
            return False

    # Reject long purely numeric identifiers.
    if text.isdigit() and len(text) >= 8:
        return False

    return True


def _extract_identity_from_payload(payload: Any) -> Optional[str]:
    """Recursively extract a user-facing identifier from nested JSON payloads."""
    if not isinstance(payload, (dict, list)):
        return None

    preferred_keys = (
        "email",
        "preferred_username",
        "username",
        "user_name",
        "login",
        "name",
        "nickname",
    )
    fallback_keys = ("id", "sub")

    preferred_values: List[Any] = []
    fallback_values: List[Any] = []
    stack: List[Any] = [payload]

    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key in preferred_keys:
                if key in current:
                    preferred_values.append(current.get(key))
            for key in fallback_keys:
                if key in current:
                    fallback_values.append(current.get(key))
            for nested_value in current.values():
                if isinstance(nested_value, (dict, list)):
                    stack.append(nested_value)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    stack.append(item)

    return _first_non_empty_identity(*(preferred_values + fallback_values))


def _extract_identity_from_token_claims(access_token: str) -> Optional[str]:
    """Best-effort decode of JWT claims to extract user identity fields.

    This is used as a fallback when /me does not expose email/username.
    """
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return None

        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode(
            "utf-8"
        )
        claims = json.loads(payload_json)
        return _extract_identity_from_payload(claims)
    except Exception:
        return None


def _fetch_user_email_from_api(access_token: str) -> Optional[str]:
    """Fetch user identifier from OpenAI's user info endpoint.

    Prefers email when available, then falls back to username/name/id fields.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(USER_INFO_URL, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return _extract_identity_from_payload(data)
    except Exception:
        pass
    return None


# --- Provider ---


class OpenAIProvider(BaseProvider):
    """Provider for OpenAI Codex plan usage quotas."""

    def __init__(self, account_data: Dict[str, Any]):
        super().__init__(account_data)
        self.access_token: Optional[str] = account_data.get("accessToken")
        self.refresh_token: Optional[str] = account_data.get("refreshToken")

    @property
    def provider_name(self) -> str:
        return "OpenAI Codex"

    @property
    def source_priority(self) -> int:
        return 3

    @property
    def primary_color(self) -> str:
        return "green"

    @property
    def short_indicator(self) -> str:
        return "O"

    def get_color(self, quota: Dict[str, Any]) -> str:
        return "green"

    # --- Auth ---

    def login(self, **kwargs: Any) -> Dict[str, Any]:
        """Login using provided tokens or discover them.

        Accepted kwargs:
          access_token, refresh_token – explicit tokens
        """
        access_token = kwargs.get("access_token") or self.access_token
        refresh_token = kwargs.get("refresh_token") or self.refresh_token

        if not access_token:
            raise Exception(
                "OpenAI access token is required. "
                "Use interactive login or provide tokens."
            )

        # Validate by fetching usage (may refresh tokens internally)
        email = self._validate_token(access_token, refresh_token)

        return {
            "type": "openai",
            "email": email,
            "accessToken": self.access_token or access_token,
            "refreshToken": self.refresh_token or refresh_token or "",
            "services": ["OPENAI_CODEX"],
        }

    def interactive_login(self, display_manager: Any) -> Dict[str, Any]:
        """Interactive login: discover existing tokens or run device code flow."""
        # Strategy 1: OpenCode token
        display_manager.console.print(
            "[dim]Checking for existing OpenAI tokens...[/dim]"
        )
        token = _discover_opencode_token()
        if token:
            display_manager.console.print("[green]✓ Found OpenCode token[/green]")
            try:
                return self.login(access_token=token)
            except Exception:
                display_manager.console.print(
                    "[yellow]⚠ OpenCode token invalid or expired[/yellow]"
                )

        # Strategy 2: Codex CLI token
        cli_tokens = _discover_codex_cli_token()
        if cli_tokens:
            display_manager.console.print("[green]✓ Found Codex CLI token[/green]")
            # Try direct, then refresh if needed
            try:
                return self.login(**cli_tokens)
            except Exception:
                if cli_tokens.get("refresh_token"):
                    display_manager.console.print(
                        "[dim]Refreshing Codex CLI token...[/dim]"
                    )
                    refreshed = _refresh_access_token(cli_tokens["refresh_token"])
                    if refreshed:
                        try:
                            return self.login(**refreshed)
                        except Exception:
                            pass
                display_manager.console.print(
                    "[yellow]⚠ Codex CLI token invalid[/yellow]"
                )

        # Strategy 3: Device code flow
        display_manager.console.print(
            "[bold]Starting device code authorization...[/bold]"
        )
        try:
            tokens = _run_device_code_flow(display_manager)
            result = self.login(**tokens)
            display_manager.console.print(
                f"[green]✓ Logged in as [bold]{result.get('email', 'OpenAI User')}[/bold][/green]"
            )
            return result
        except Exception as e:
            raise Exception(f"OpenAI login failed: {e}")

    def _validate_token(
        self, access_token: str, refresh_token: Optional[str] = None
    ) -> str:
        """Validate token by fetching usage. Returns user email/identifier."""
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(
                USAGE_URL,
                headers=headers,
                timeout=self.time_remaining(FETCH_TIMEOUT),
            )
            if resp.status_code == 200:
                # Fetch account identity from API
                user_identity = _fetch_user_email_from_api(access_token)
                if user_identity:
                    return user_identity
                # Fallback: parse identity from JWT-like token claims
                token_identity = _extract_identity_from_token_claims(access_token)
                if token_identity:
                    return token_identity
                # Fall back to a default identifier
                return "OpenAI User"
            if resp.status_code == 401 and refresh_token:
                refreshed = _refresh_access_token(refresh_token)
                if refreshed:
                    self.access_token = refreshed["access_token"]
                    self.refresh_token = refreshed.get("refresh_token", refresh_token)
                    return self._validate_token(self.access_token)
            raise Exception(f"Token validation failed: HTTP {resp.status_code}")
        except requests.RequestException as e:
            raise Exception(f"OpenAI API request failed: {e}")

    # --- Quota fetching ---

    def fetch_quotas(self) -> List[Dict[str, Any]]:
        """Fetch Codex plan usage quotas."""
        if not self.access_token:
            return []

        start = time.perf_counter()
        email = self.account_data.get("email", "unknown")
        logger.debug(f"[openai] fetch_quotas start account={email}")

        if not self.has_time_remaining():
            return []

        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            resp = requests.get(
                USAGE_URL,
                headers=headers,
                timeout=self.time_remaining(FETCH_TIMEOUT),
            )
        except requests.RequestException as e:
            logger.debug(f"[openai] fetch_quotas request error: {e}")
            return [
                _build_quota(
                    "OpenAI Codex", "Codex", 0, 0, "", is_error=True, message=str(e)
                )
            ]

        # Try token refresh on 401
        if resp.status_code == 401 and self.refresh_token:
            if not self.has_time_remaining():
                return []
            refreshed = _refresh_access_token(self.refresh_token)
            if refreshed:
                self.access_token = refreshed["access_token"]
                self.refresh_token = refreshed.get("refresh_token", self.refresh_token)
                self.account_data["accessToken"] = self.access_token
                self.account_data["refreshToken"] = self.refresh_token
                headers = {"Authorization": f"Bearer {self.access_token}"}
                try:
                    resp = requests.get(
                        USAGE_URL,
                        headers=headers,
                        timeout=self.time_remaining(FETCH_TIMEOUT),
                    )
                except requests.RequestException as e:
                    logger.debug(f"[openai] fetch_quotas retry error: {e}")
                    return []

        if resp.status_code != 200:
            return [
                _build_quota(
                    "OpenAI Codex",
                    "Codex",
                    0,
                    0,
                    "",
                    is_error=True,
                    message=f"HTTP {resp.status_code}",
                )
            ]

        data = resp.json()
        results = self._parse_usage_response(data)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[openai] fetch_quotas done account={email} "
            f"elapsed_ms={elapsed_ms:.1f} quota_count={len(results)}"
        )
        self.record_timing("openai_total", elapsed_ms)
        return results

    def _parse_usage_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse the /wham/usage response into quota dicts."""
        results: List[Dict[str, Any]] = []
        plan_type = data.get("plan_type", "unknown")

        # Normalize rate_limit (handle None)
        rate_limit = data.get("rate_limit") or {}
        if not isinstance(rate_limit, dict):
            rate_limit = {}

        # Primary window (typically 5-hour)
        primary = rate_limit.get("primary_window", {})
        if primary and isinstance(primary, dict):
            results.append(self._parse_window(primary, plan_type, "Primary"))

        # Secondary window (typically weekly)
        secondary = rate_limit.get("secondary_window", {})
        if secondary and isinstance(secondary, dict):
            results.append(self._parse_window(secondary, plan_type, "Secondary"))

        # Additional rate limits (handle None)
        additional_limits = data.get("additional_rate_limits") or []
        if isinstance(additional_limits, list):
            for extra in additional_limits:
                if isinstance(extra, dict):
                    name = extra.get("name", "Additional")
                    window = extra.get("primary_window", extra)
                    results.append(self._parse_window(window, plan_type, name))

        # Credits (handle None)
        credits_data = data.get("credits") or {}
        if isinstance(credits_data, dict) and credits_data.get("has_credits"):
            balance = credits_data.get("balance", 0)
            unlimited = credits_data.get("unlimited", False)
            results.append(
                _build_quota(
                    f"OpenAI Credits ({plan_type})",
                    "Credits",
                    remaining_pct=100.0 if unlimited else min(100.0, balance),
                    used_pct=0.0 if unlimited else max(0.0, 100.0 - balance),
                    reset="",
                    plan_type=plan_type,
                    unlimited=unlimited,
                    balance=balance,
                )
            )

        # If nothing was parsed, return a friendly free tier entry
        if not results:
            # Free tier or no quota data available
            results.append(
                _build_quota(
                    f"OpenAI Codex ({plan_type})",
                    f"Plan: {plan_type.capitalize()}",
                    remaining_pct=100.0,
                    used_pct=0.0,
                    reset="No quota limits",
                    plan_type=plan_type,
                )
            )

        return results

    @staticmethod
    def _parse_window(
        window: Dict[str, Any], plan_type: str, label: str
    ) -> Dict[str, Any]:
        """Parse a rate-limit window into a quota dict."""
        used_pct = float(window.get("used_percent", 0))
        remaining_pct = max(0.0, min(100.0, 100.0 - used_pct))
        limit_seconds = window.get("limit_window_seconds", 0)
        reset_at = window.get("reset_at")

        reset_str = _format_reset_time(reset_at) if reset_at else ""

        # Convert window duration to human-readable
        if limit_seconds:
            hours = limit_seconds / 3600
            if hours >= 24:
                days = hours / 24
                window_label = f"{days:.0f}d" if days == int(days) else f"{days:.1f}d"
            elif hours >= 1:
                window_label = (
                    f"{hours:.0f}h" if hours == int(hours) else f"{hours:.1f}h"
                )
            else:
                window_label = f"{limit_seconds / 60:.0f}m"
        else:
            window_label = ""

        display_name = f"{label} ({window_label})" if window_label else label

        return _build_quota(
            name=f"OpenAI Codex {label} ({plan_type})",
            display_name=display_name,
            remaining_pct=remaining_pct,
            used_pct=used_pct,
            reset=reset_str,
            plan_type=plan_type,
            window_seconds=limit_seconds,
        )

    # --- Filtering / Sorting ---

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        return quotas

    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        name = quota.get("display_name", "")
        # Primary first, then secondary, then others
        if "Primary" in name:
            type_priority = 0
        elif "Secondary" in name:
            type_priority = 1
        elif "Credits" in name:
            type_priority = 2
        else:
            type_priority = 3
        return 0, type_priority, name
