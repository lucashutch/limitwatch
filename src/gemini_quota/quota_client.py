import requests
from typing import Dict, List, Any, Optional
import platform
import concurrent.futures
from google.oauth2.credentials import Credentials


class QuotaClient:
    def __init__(self, credentials: Credentials):
        self.credentials = credentials

    def fetch_quotas(
        self, project_id: Optional[str] = None, services: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        # We will make requests to get requested quotas in parallel
        quotas = []
        if services is None:
            services = ["AG", "CLI"]

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(services)
        ) as executor:
            futures = {}
            if "CLI" in services:
                futures["CLI"] = executor.submit(
                    self._fetch_gemini_cli_quotas, project_id
                )
            if "AG" in services:
                futures["AG"] = executor.submit(
                    self._fetch_antigravity_quotas, project_id
                )

            for service, future in futures.items():
                try:
                    res = future.result()
                    quotas.extend(res)
                except Exception:
                    pass

        return quotas

    def _fetch_gemini_cli_quotas(
        self, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetches Gemini CLI quotas using the retrieveUserQuota endpoint."""
        url = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"

        system = platform.system().lower()
        os_name = (
            "win32"
            if system == "windows"
            else ("darwin" if system == "darwin" else "linux")
        )
        arch = platform.machine().lower()
        arch_name = "arm64" if ("arm" in arch or "aarch64" in arch) else "x64"
        user_agent = f"GeminiCLI/1.0.0/gemini-2.5-pro ({os_name}; {arch_name})"

        headers = {
            "Authorization": f"Bearer {self.credentials.token}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        }

        def make_request(p_id):
            body = {"project": p_id} if p_id else {}
            return requests.post(url, headers=headers, json=body, timeout=10)

        try:
            response = make_request(project_id)

            # If failed with project_id, try without it
            if response.status_code != 200 and project_id:
                response = make_request(None)

            if response.status_code == 200:
                data = response.json()
                buckets = data.get("buckets", [])

                groups = {}
                for bucket in buckets:
                    model_id = bucket.get("modelId")
                    if not model_id:
                        continue

                    # Normalize names and group
                    family = None
                    if "gemini-3-pro" in model_id:
                        family = "Gemini 3 Pro"
                    elif "gemini-3-flash" in model_id:
                        family = "Gemini 3 Flash"
                    elif "gemini-2.5-pro" in model_id:
                        family = "Gemini 2.5 Pro"
                    elif "gemini-2.5-flash" in model_id:
                        family = "Gemini 2.5 Flash"
                    elif "gemini-2.0-flash" in model_id:
                        family = "Gemini 2.0 Flash"
                    elif "gemini-1.5-pro" in model_id:
                        family = "Gemini 1.5 Pro"
                    elif "gemini-1.5-flash" in model_id:
                        family = "Gemini 1.5 Flash"

                    if not family:
                        continue

                    remaining_fraction = bucket.get("remainingFraction", 1.0)
                    reset_time = bucket.get("resetTime")

                    if (
                        family not in groups
                        or remaining_fraction < groups[family]["remaining_fraction"]
                    ):
                        groups[family] = {
                            "remaining_fraction": remaining_fraction,
                            "reset": reset_time or "Unknown",
                        }

                results = []
                for family, data in groups.items():
                    results.append(
                        {
                            "name": f"{family} (CLI)",
                            "display_name": f"{family} (CLI)",
                            "remaining_pct": data["remaining_fraction"] * 100,
                            "reset": data["reset"],
                            "source_type": "Gemini CLI",
                        }
                    )
                return results
        except Exception:
            pass
        return []

    def _fetch_antigravity_quotas(
        self, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetches Antigravity quotas using the fetchAvailableModels endpoint."""
        url = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"

        headers = {
            "Authorization": f"Bearer {self.credentials.token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity/1.15.8 linux/x64",
            "X-Goog-Api-Client": "google-cloud-sdk vscode/1.96.0",
            "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
        }

        def make_request(p_id):
            body = {"project": p_id} if p_id else {}
            return requests.post(url, headers=headers, json=body, timeout=10)

        try:
            response = make_request(project_id)

            # If failed with project_id, try without it
            if response.status_code != 200 and project_id:
                response = make_request(None)

            if response.status_code == 200:
                data = response.json()
                models = data.get("models", {})

                groups = {}
                for model_id, info in models.items():
                    display_name = info.get("displayName", model_id)
                    lower_name = display_name.lower()
                    lower_id = model_id.lower()

                    # Filter logic
                    important_keywords = ["gemini", "claude"]
                    exclude_keywords = ["tab_", "chat_", "image", "rev19"]

                    is_important = any(
                        k in lower_name for k in important_keywords
                    ) or any(k in lower_id for k in important_keywords)
                    is_excluded = any(k in lower_name for k in exclude_keywords) or any(
                        k in lower_id for k in exclude_keywords
                    )

                    if is_important and not is_excluded:
                        quota_info = info.get("quotaInfo")
                        if quota_info:
                            remaining_fraction = quota_info.get(
                                "remainingFraction", 1.0
                            )
                            reset_time = quota_info.get("resetTime")

                            # Determine family group
                            family = "Other"
                            if "claude" in lower_name or "claude" in lower_id:
                                family = "Claude"
                            elif (
                                "gemini 3 pro" in lower_name
                                or "gemini-3-pro" in lower_id
                            ):
                                family = "Gemini 3 Pro"
                            elif (
                                "gemini 3 flash" in lower_name
                                or "gemini-3-flash" in lower_id
                            ):
                                family = "Gemini 3 Flash"
                            elif (
                                "gemini 2.5 flash" in lower_name
                                or "gemini-2.5-flash" in lower_id
                            ):
                                family = "Gemini 2.5 Flash"
                            elif (
                                "gemini 2.5 pro" in lower_name
                                or "gemini-2.5-pro" in lower_id
                            ):
                                family = "Gemini 2.5 Pro"
                            else:
                                family = display_name

                            if (
                                family not in groups
                                or remaining_fraction
                                < groups[family]["remaining_fraction"]
                            ):
                                groups[family] = {
                                    "remaining_fraction": remaining_fraction,
                                    "reset": reset_time or "Unknown",
                                }

                results = []
                for family, data in groups.items():
                    results.append(
                        {
                            "name": f"{family} (AG)",
                            "display_name": f"{family} (AG)",
                            "remaining_pct": data["remaining_fraction"] * 100,
                            "reset": data["reset"],
                            "source_type": "Antigravity",
                        }
                    )
                return results
        except Exception:
            pass
        return []
