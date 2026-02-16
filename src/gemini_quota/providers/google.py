import requests
import platform
import logging
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from .base import BaseProvider

logger = logging.getLogger(__name__)

# Hardcoded constants for Antigravity
ANTIGRAVITY_CLIENT_ID = (
    "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
)
ANTIGRAVITY_CLIENT_SECRET = "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"

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


class GoogleProvider(BaseProvider):
    def __init__(self, account_data: Dict[str, Any], credentials=None):
        super().__init__(account_data)
        self.credentials = credentials

    @property
    def provider_name(self) -> str:
        return "Google (Gemini CLI / Antigravity)"

    @property
    def source_priority(self) -> int:
        return 1

    @property
    def primary_color(self) -> str:
        return "cyan"

    def get_color(self, quota: Dict[str, Any]) -> str:
        source = quota.get("source_type", "")
        if source == "Gemini CLI":
            return "cyan"
        return "magenta"

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        if not quotas:
            return []
        if show_all:
            return quotas

        # Group by source to check for premium models per source
        has_premium_cli = any(
            ("3" in q.get("display_name", "") or "Claude" in q.get("display_name", ""))
            and q.get("source_type") == "Gemini CLI"
            for q in quotas
        )
        has_premium_ag = any(
            ("3" in q.get("display_name", "") or "Claude" in q.get("display_name", ""))
            and q.get("source_type") == "Antigravity"
            for q in quotas
        )

        filtered = []
        for q in quotas:
            name = q.get("display_name", "")
            source = q.get("source_type", "")
            if "2.0" in name:
                continue
            is_premium = "3" in name or "Claude" in name
            if is_premium:
                filtered.append(q)
            elif source == "Gemini CLI" and not has_premium_cli:
                filtered.append(q)
            elif source == "Antigravity" and not has_premium_ag:
                filtered.append(q)
        return filtered

    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        source = quota.get("source_type", "")
        name = quota.get("display_name", "")
        source_prio = 0 if source == "Gemini CLI" else 1
        family_prio = 99
        if "Gemini 2.0 Flash" in name:
            family_prio = 0
        elif "Gemini 2.5 Flash" in name:
            family_prio = 1
        elif "Gemini 2.5 Pro" in name:
            family_prio = 2
        elif "Gemini 3 Flash" in name:
            family_prio = 3
        elif "Gemini 3 Pro" in name:
            family_prio = 4
        elif "Claude" in name:
            family_prio = 5
        return source_prio, family_prio, name

    def interactive_login(self, display_manager: Any) -> Dict[str, Any]:
        """Perform an interactive login flow with the user."""
        import click

        display_manager.console.print(
            "\n[bold blue]Select Google services to enable:[/bold blue]"
        )
        display_manager.console.print(
            "1) Both Antigravity and Gemini CLI (Recommended)"
        )
        display_manager.console.print("2) Antigravity only")
        display_manager.console.print("3) Gemini CLI only")

        choice = click.prompt("Enter choice", type=int, default=1)
        services = ["AG", "CLI"]
        if choice == 2:
            services = ["AG"]
        elif choice == 3:
            services = ["CLI"]

        # manual_project_id could be passed from CLI flags if we want to support it
        # but for simplicity in interactive mode we assume None unless we add a prompt
        return self.login(services=services)

    def login(self, **kwargs) -> Dict[str, Any]:
        """Perform OAuth login flow and return account data."""
        services = kwargs.get("services", ["AG", "CLI"])
        manual_project_id = kwargs.get("manual_project_id")

        client_config = {
            "installed": {
                "client_id": ANTIGRAVITY_CLIENT_ID,
                "client_secret": ANTIGRAVITY_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
        creds = flow.run_local_server(port=0, open_browser=False)

        # Fetch email
        session = google.auth.transport.requests.AuthorizedSession(creds)
        userinfo = session.get("https://www.googleapis.com/oauth2/v3/userinfo").json()
        email = userinfo.get("email")

        if not email:
            raise Exception("Failed to retrieve email from Google")

        # Try to fetch managed project ID and metadata
        project_ids = {}
        if manual_project_id:
            project_ids["projectId"] = manual_project_id
            project_ids["managedProjectId"] = manual_project_id
        else:
            # 1. Try loadCodeAssist
            logger.info("Searching for associated Google Cloud project...")
            endpoints = [
                "https://cloudcode-pa.googleapis.com",
                "https://daily-cloudcode-pa.sandbox.googleapis.com",
                "https://autopush-cloudcode-pa.sandbox.googleapis.com",
            ]

            headers = {
                "User-Agent": "google-api-nodejs-client/9.15.1",
                "Content-Type": "application/json",
                "Client-Metadata": '{"ideType":"ANTIGRAVITY","platform":"LINUX","pluginType":"GEMINI"}',
            }

            metadata = {
                "ideType": "ANTIGRAVITY",
                "platform": "LINUX",
                "pluginType": "GEMINI",
            }

            for url_base in endpoints:
                try:
                    resp = session.post(
                        f"{url_base}/v1internal:loadCodeAssist",
                        headers=headers,
                        json={"metadata": metadata},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        project_data = data.get("cloudaicompanionProject")
                        p_id = None
                        if isinstance(project_data, str):
                            p_id = project_data
                        elif isinstance(project_data, dict):
                            p_id = project_data.get("id")

                        if p_id:
                            project_ids["projectId"] = p_id
                            project_ids["managedProjectId"] = p_id
                            break
                except Exception:
                    pass

            # 2. Try getManagedProject
            if "projectId" not in project_ids:
                try:
                    headers = {
                        "User-Agent": "antigravity/1.15.8 linux/x64",
                        "X-Goog-Api-Client": "google-cloud-sdk vscode/1.96.0",
                        "Client-Metadata": '{"ideType":"VSCODE","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
                    }
                    for ide in ["VSCODE", "JETBRAINS", "IDE_UNSPECIFIED"]:
                        resp = session.post(
                            "https://cloudcode-pa.googleapis.com/v1internal:getManagedProject",
                            headers=headers,
                            json={"ideType": ide},
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            managed_id = resp.json().get("projectId")
                            if managed_id:
                                project_ids["managedProjectId"] = managed_id
                                project_ids["projectId"] = managed_id
                                break
                except Exception:
                    pass

            # 3. Try Cloud Resource Manager
            if "projectId" not in project_ids:
                try:
                    all_projects = []
                    next_page_token = None
                    for page in range(1, 4):
                        url = "https://cloudresourcemanager.googleapis.com/v1/projects"
                        if next_page_token:
                            url += f"?pageToken={next_page_token}"
                        resp = session.get(url, timeout=10)
                        if resp.status_code != 200:
                            break
                        data = resp.json()
                        projects = data.get("projects", [])
                        all_projects.extend(projects)
                        next_page_token = data.get("nextPageToken")
                        if not next_page_token or not projects:
                            break

                    if all_projects:
                        # Priority 1: gen-lang-client
                        gen_lang_projects = [
                            p
                            for p in all_projects
                            if "gen-lang-client" in p.get("projectId", "")
                            and p.get("lifecycleState") == "ACTIVE"
                        ]
                        if gen_lang_projects:
                            gen_lang_projects.sort(
                                key=lambda x: x.get("createTime", ""), reverse=True
                            )
                            p_id = gen_lang_projects[0]["projectId"]
                            project_ids["projectId"] = p_id
                            project_ids["managedProjectId"] = p_id
                        # Priority 2: 'gemini' or 'cloud-code'
                        if "projectId" not in project_ids:
                            ai_projects = [
                                p
                                for p in all_projects
                                if (
                                    "gemini" in p.get("projectId", "").lower()
                                    or "cloud-code" in p.get("projectId", "").lower()
                                )
                                and p.get("lifecycleState") == "ACTIVE"
                            ]
                            if ai_projects:
                                ai_projects.sort(
                                    key=lambda x: x.get("createTime", ""), reverse=True
                                )
                                p_id = ai_projects[0]["projectId"]
                                project_ids["projectId"] = p_id
                                project_ids["managedProjectId"] = p_id
                        # Priority 3: Fallback newest active
                        if "projectId" not in project_ids:
                            active_projects = [
                                p
                                for p in all_projects
                                if p.get("lifecycleState") == "ACTIVE"
                            ]
                            if active_projects:
                                active_projects.sort(
                                    key=lambda x: x.get("createTime", ""), reverse=True
                                )
                                p_id = active_projects[0]["projectId"]
                                project_ids["projectId"] = p_id
                                project_ids["managedProjectId"] = p_id
                except Exception:
                    pass

            # 4. Final Fallback
            if "projectId" not in project_ids:
                default_id = "rising-fact-p41fc"
                project_ids["projectId"] = default_id
                project_ids["managedProjectId"] = default_id

        account_data = {
            "type": "google",
            "email": email,
            "refreshToken": creds.refresh_token,
            "services": services,
        }
        account_data.update(project_ids)

        final_id = project_ids.get("projectId") or project_ids.get("managedProjectId")
        if final_id:
            print(f"Final Project ID: {final_id}")
        else:
            print(
                "Warning: No Google Cloud project could be automatically associated. CLI quotas might be limited."
            )

        return account_data

    def fetch_quotas(self) -> List[Dict[str, Any]]:
        services = self.account_data.get("services", ["AG", "CLI"])
        project_id = self.account_data.get("projectId") or self.account_data.get(
            "managedProjectId"
        )

        quotas = []
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

        if not quotas:
            # Fallback to cachedQuota if API call failed or returned empty
            cached = self.account_data.get("cachedQuota", {})
            if cached:
                # Mapping from cached keys to display names
                family_map = {
                    "gemini-pro": "Gemini 3 Pro (AG)",
                    "gemini-flash": "Gemini 3 Flash (AG)",
                    "claude": "Claude (AG)",
                    "gemini-2.5-flash": "Gemini 2.5 Flash (AG)",
                    "gemini-2.5-pro": "Gemini 2.5 Pro (AG)",
                }
                for family, q_data in cached.items():
                    display_name = family_map.get(
                        family, f"{family.replace('-', ' ').title()} (AG)"
                    )
                    quotas.append(
                        {
                            "name": family,
                            "display_name": display_name,
                            "remaining_pct": q_data.get("remainingFraction", 1.0) * 100,
                            "reset": q_data.get("resetTime", "Unknown"),
                            "source_type": "Antigravity",
                        }
                    )
        return quotas

    def _fetch_gemini_cli_quotas(
        self, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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

                return [
                    {
                        "name": f"{family} (CLI)",
                        "display_name": f"{family} (CLI)",
                        "remaining_pct": data["remaining_fraction"] * 100,
                        "reset": data["reset"],
                        "source_type": "Gemini CLI",
                    }
                    for family, data in groups.items()
                ]
        except Exception:
            pass
        return []

    def _fetch_antigravity_quotas(
        self, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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
                    lower_name, lower_id = display_name.lower(), model_id.lower()

                    important_keywords = ["gemini", "claude"]
                    exclude_keywords = ["tab_", "chat_", "image", "rev19"]

                    if (
                        (
                            any(k in lower_name for k in important_keywords)
                            or any(k in lower_id for k in important_keywords)
                        )
                        and not any(k in lower_name for k in exclude_keywords)
                        and not any(k in lower_id for k in exclude_keywords)
                    ):
                        quota_info = info.get("quotaInfo")
                        if quota_info:
                            remaining_fraction = quota_info.get(
                                "remainingFraction", 1.0
                            )
                            reset_time = quota_info.get("resetTime")

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

                return [
                    {
                        "name": f"{family} (AG)",
                        "display_name": f"{family} (AG)",
                        "remaining_pct": data["remaining_fraction"] * 100,
                        "reset": data["reset"],
                        "source_type": "Antigravity",
                    }
                    for family, data in groups.items()
                ]
        except Exception:
            pass
        return []
