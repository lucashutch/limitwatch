import requests
import concurrent.futures
from datetime import datetime, time, timedelta, timezone
from typing import List, Dict, Any
from .base import BaseProvider


class ChutesProvider(BaseProvider):
    def __init__(self, account_data: Dict[str, Any]):
        super().__init__(account_data)
        self.api_key = account_data.get("apiKey")

    def _get_next_reset_iso(self) -> str:
        """Calculate the next 00:00 UTC reset time."""
        now = datetime.now(timezone.utc)
        next_reset = datetime.combine(
            now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc
        )
        return next_reset.isoformat().replace("+00:00", "Z")

    def fetch_quotas(self) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []

        results = []
        headers = {"Authorization": self.api_key}
        base_url = "https://api.chutes.ai"
        next_reset = self._get_next_reset_iso()

        try:
            # 1. Fetch Balance
            me_resp = requests.get(f"{base_url}/users/me", headers=headers, timeout=10)
            if me_resp.status_code == 200:
                me_data = me_resp.json()
                balance = me_data.get("balance", 0.0)
                if balance > 0:
                    results.append(
                        {
                            "name": "Chutes Balance",
                            "display_name": f"Balance: ${balance:.2f}",
                            "remaining_pct": 100.0,
                            "reset": "N/A",
                            "source_type": "Chutes",
                        }
                    )

            # 2. Fetch Main Quota Usage (using the optimized 'me' endpoint)
            # This endpoint returns the primary/default quota usage for the user
            usage_resp = requests.get(
                f"{base_url}/users/me/quota_usage/me", headers=headers, timeout=10
            )
            if usage_resp.status_code == 200:
                data = usage_resp.json()
                # data is expected to be {"quota": 300, "used": 15, "chute_id": "*"}
                limit = data.get("quota") or data.get("limit") or 0
                used = data.get("used", 0)
                chute_id = data.get("chute_id") or "*"

                if limit > 0:
                    remaining_pct = max(0, (limit - used) / limit) * 100

                    # Clean up display name: remove * and show remaining/total
                    remaining = int(limit - used)
                    if chute_id == "*":
                        display_name = f"Quota ({remaining}/{int(limit)})"
                    else:
                        display_name = f"Quota: {chute_id} ({remaining}/{int(limit)})"

                    results.append(
                        {
                            "name": f"Chutes Quota ({chute_id})",
                            "display_name": display_name,
                            "remaining_pct": remaining_pct,
                            "reset": next_reset,
                            "source_type": "Chutes",
                        }
                    )

            # 3. Fallback/Support for specific quotas if the main one is not enough
            # We only do this if results is still only the balance or empty
            if len(results) <= 1:
                quota_resp = requests.get(
                    f"{base_url}/users/me/quotas", headers=headers, timeout=10
                )
                if quota_resp.status_code == 200:
                    quotas_list = quota_resp.json()
                    if isinstance(quotas_list, list) and len(quotas_list) > 0:
                        # If we found multiple quotas, we fetch their usage
                        # (Keeping the previous logic as fallback for non-standard setups)
                        def fetch_usage(q):
                            cid = q.get("chute_id") or q.get("id")
                            if (
                                not cid or cid == "*"
                            ):  # Already handled by 'me' endpoint effectively
                                return None
                            try:
                                usage_url = f"{base_url}/users/me/quota_usage/{cid}"
                                u_resp = requests.get(
                                    usage_url, headers=headers, timeout=10
                                )
                                if u_resp.status_code == 200:
                                    d = u_resp.json()
                                    if "chute_id" not in d:
                                        d["chute_id"] = cid
                                    return d
                            except Exception:
                                pass
                            return None

                        with concurrent.futures.ThreadPoolExecutor(
                            max_workers=5
                        ) as executor:
                            usages = list(executor.map(fetch_usage, quotas_list))

                        for q_usage in usages:
                            if not q_usage:
                                continue
                            cid = (
                                q_usage.get("chute_id")
                                or q_usage.get("id")
                                or "Unknown"
                            )
                            lim = q_usage.get("quota") or q_usage.get("limit") or 0
                            usd = q_usage.get("used", 0)
                            rem_pct = (
                                max(0, (lim - usd) / lim) * 100 if lim > 0 else 100.0
                            )

                            remaining = int(lim - usd)
                            if cid == "*":
                                display_name = f"Quota ({remaining}/{int(lim)})"
                            else:
                                display_name = f"Quota: {cid} ({remaining}/{int(lim)})"

                            results.append(
                                {
                                    "name": f"Chutes Quota ({cid})",
                                    "display_name": display_name,
                                    "remaining_pct": rem_pct,
                                    "reset": next_reset,
                                    "source_type": "Chutes",
                                }
                            )
        except Exception:
            pass

        return results
