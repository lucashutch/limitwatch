"""Shell completion support for LimitWatch CLI.

This module provides dynamic completion callbacks for shell autocompletion.
Completions are read directly from the accounts.json file for fast performance.
"""

import json
import os
from pathlib import Path
from typing import List, Any


def get_config_dir() -> Path:
    """Get the configuration directory for LimitWatch."""
    if os.environ.get("LIMITWATCH_CONFIG_DIR"):
        return Path(os.environ["LIMITWATCH_CONFIG_DIR"])

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "limitwatch"

    return Path.home() / ".config" / "limitwatch"


def load_accounts_data() -> dict:
    """Load accounts data directly from accounts.json."""
    auth_path = get_config_dir() / "accounts.json"

    if not auth_path.exists():
        return {"accounts": []}

    try:
        with open(auth_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"accounts": []}


def complete_accounts(ctx: Any, param: Any, incomplete: str) -> List[str]:
    """Complete account emails and aliases.

    Returns both email addresses and aliases for matching accounts.
    """
    data = load_accounts_data()
    accounts = data.get("accounts", [])

    seen = set()
    results = []
    for account in accounts:
        # Add email
        email = account.get("email", "")
        if email and email.startswith(incomplete) and email not in seen:
            seen.add(email)
            results.append(email)

        # Add alias if present and different from email
        alias = account.get("alias", "")
        if alias and alias.startswith(incomplete) and alias not in seen:
            seen.add(alias)
            results.append(alias)

    return results


def complete_providers(ctx: Any, param: Any, incomplete: str) -> List[str]:
    """Complete provider types.

    Returns provider types from configured accounts plus all available providers.
    """
    data = load_accounts_data()
    accounts = data.get("accounts", [])

    # Get unique provider types from accounts
    provider_types = set()
    for account in accounts:
        ptype = account.get("type", "")
        if ptype and ptype.startswith(incomplete):
            provider_types.add(ptype)

    # Also include all available provider types
    all_providers = ["google", "chutes", "github_copilot", "openai", "openrouter"]
    for ptype in all_providers:
        if ptype.startswith(incomplete) and ptype not in provider_types:
            provider_types.add(ptype)

    return sorted(provider_types)


def complete_groups(ctx: Any, param: Any, incomplete: str) -> List[str]:
    """Complete group names.

    Returns unique group values from configured accounts.
    """
    data = load_accounts_data()
    accounts = data.get("accounts", [])

    groups = set()
    for account in accounts:
        group = account.get("group", "")
        if group and group.startswith(incomplete) and group not in groups:
            groups.add(group)

    return sorted(groups)


def complete_quota_names(ctx: Any, param: Any, incomplete: str) -> List[str]:
    """Complete quota/model names.

    Returns quota names from cached quotas in accounts.
    """
    data = load_accounts_data()
    accounts = data.get("accounts", [])

    names = set()
    for account in accounts:
        cached_quotas = account.get("cachedQuotas", [])
        for quota in cached_quotas:
            # Check name field
            name = quota.get("name", "")
            if name and name.startswith(incomplete) and name not in names:
                names.add(name)

            # Check display_name field
            display_name = quota.get("display_name", "")
            if (
                display_name
                and display_name.startswith(incomplete)
                and display_name not in names
            ):
                names.add(display_name)

    return sorted(names)


def complete_preset_ranges(ctx: Any, param: Any, incomplete: str) -> List[str]:
    """Complete preset time ranges."""
    presets = ["24h", "7d", "30d", "90d"]
    return [preset for preset in presets if preset.startswith(incomplete)]


def complete_export_formats(ctx: Any, param: Any, incomplete: str) -> List[str]:
    """Complete export format options."""
    formats = ["csv", "markdown"]
    return [fmt for fmt in formats if fmt.startswith(incomplete)]


def complete_history_view_types(ctx: Any, param: Any, incomplete: str) -> List[str]:
    """Complete history view type options."""
    view_types = ["heatmap", "chart", "calendar", "bars", "stats"]
    return [view for view in view_types if view.startswith(incomplete)]
