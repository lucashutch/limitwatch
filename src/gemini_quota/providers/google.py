import requests
import platform
import logging
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
import google.auth.transport.requests
from google_auth_oauthlib.flow import InstalledAppFlow
from .base import BaseProvider

logger = logging.getLogger(__name__)

# Hardcoded constants for Antigravity
ANTIGRAVITY_CLIENT_ID = (
    "1071006060591-" + "tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
)
ANTIGRAVITY_CLIENT_SECRET = "GOCSPX-" + "K58FWR486LdLJ1mLB8sXC4z6qDAf"

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

# --- Model family classification (shared between CLI and AG) ---

CLI_MODEL_FAMILIES = [
    ("gemini-3.1-pro", "Gemini Pro"),
    ("gemini-3-pro", "Gemini Pro"),
    ("gemini-3.1-flash", "Gemini Flash"),
    ("gemini-3-flash", "Gemini Flash"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("gemini-2.0-flash", "Gemini 2.0 Flash"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro"),
    ("gemini-1.5-flash", "Gemini 1.5 Flash"),
]

AG_MODEL_FAMILIES = [
    ("claude", "Claude"),
    ("gemini 3.1 pro", "Gemini Pro"),
    ("gemini-3.1-pro", "Gemini Pro"),
    ("gemini 3 pro", "Gemini Pro"),
    ("gemini-3-pro", "Gemini Pro"),
    ("gemini 3.1 flash", "Gemini Flash"),
    ("gemini-3.1-flash", "Gemini Flash"),
    ("gemini 3 flash", "Gemini Flash"),
    ("gemini-3-flash", "Gemini Flash"),
    ("gemini 2.5 flash", "Gemini 2.5 Flash"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("gemini 2.5 pro", "Gemini 2.5 Pro"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro"),
]

PREMIUM_KEYWORDS = ("Gemini Pro", "Gemini Flash", "Claude")

FAMILY_SORT_ORDER = {
    "Gemini 2.0 Flash": 0,
    "Gemini 2.5 Flash": 1,
    "Gemini 2.5 Pro": 2,
    "Gemini Flash": 3,
    "Gemini Pro": 4,
    "Claude": 5,
}

# Cached family map for display names from cachedQuota keys
CACHED_FAMILY_MAP = {
    "gemini-pro": "Gemini Pro (AG)",
    "gemini-flash": "Gemini Flash (AG)",
    "claude": "Claude (AG)",
    "gemini-2.5-flash": "Gemini 2.5 Flash (AG)",
    "gemini-2.5-pro": "Gemini 2.5 Pro (AG)",
}

# Endpoints for loadCodeAssist discovery
LOAD_CODE_ASSIST_ENDPOINTS = [
    "https://cloudcode-pa.googleapis.com",
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
    "https://autopush-cloudcode-pa.sandbox.googleapis.com",
]

DEFAULT_QUOTA_TIMEOUT = 3


def classify_cli_model(model_id: str) -> Optional[str]:
    """Classify a CLI model ID into a family name, or None."""
    for pattern, family in CLI_MODEL_FAMILIES:
        if pattern in model_id:
            return family
    return None


def classify_ag_model(display_name: str, model_id: str) -> Optional[str]:
    """Classify an Antigravity model into a family name, or None."""
    lower_name = display_name.lower()
    lower_id = model_id.lower()
    for pattern, family in AG_MODEL_FAMILIES:
        if pattern in lower_name or pattern in lower_id:
            return family
    return None


def is_ag_model_relevant(display_name: str, model_id: str) -> bool:
    """Check if an AG model is relevant (Gemini/Claude, not tab/chat/image)."""
    lower_name = display_name.lower()
    lower_id = model_id.lower()
    important = ("gemini", "claude")
    exclude = ("tab_", "chat_", "image", "rev19")
    has_important = any(k in lower_name or k in lower_id for k in important)
    has_excluded = any(k in lower_name or k in lower_id for k in exclude)
    return has_important and not has_excluded


def is_premium_model(name: str) -> bool:
    """Check if a model name contains a premium keyword."""
    return any(kw in name for kw in PREMIUM_KEYWORDS)


def _get_user_agent() -> str:
    """Build a user agent string for Gemini CLI requests."""
    system = platform.system().lower()
    os_name = (
        "win32"
        if system == "windows"
        else ("darwin" if system == "darwin" else "linux")
    )
    arch = platform.machine().lower()
    arch_name = "arm64" if ("arm" in arch or "aarch64" in arch) else "x64"
    return f"GeminiCLI/1.0.0/gemini-2.5-pro ({os_name}; {arch_name})"


def _group_by_family(entries):
    """Group quota entries by family, keeping the lowest remaining fraction per family.

    entries: list of (family, remaining_fraction, reset_time) tuples.
    Returns: dict of {family: {"remaining_fraction": ..., "reset": ...}}
    """
    groups = {}
    for family, remaining_fraction, reset_time in entries:
        if (
            family not in groups
            or remaining_fraction < groups[family]["remaining_fraction"]
        ):
            groups[family] = {
                "remaining_fraction": remaining_fraction,
                "reset": reset_time or "Unknown",
            }
    return groups


class GoogleProvider(BaseProvider):
    def __init__(self, account_data: Dict[str, Any], credentials=None):
        super().__init__(account_data)
        self.credentials = credentials
        self._prefer_no_project = bool(
            self.account_data.get("preferNoProjectForQuota", False)
        )

    @property
    def provider_name(self) -> str:
        return "Google"

    @property
    def source_priority(self) -> int:
        return 1

    @property
    def primary_color(self) -> str:
        return "cyan"

    @property
    def short_indicator(self) -> str:
        return "G"

    def get_color(self, quota: Dict[str, Any]) -> str:
        source = quota.get("source_type", "")
        return "cyan" if source == "Gemini CLI" else "magenta"

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        if not quotas:
            return []
        if show_all:
            return quotas

        has_premium = {
            "Gemini CLI": False,
            "Antigravity": False,
        }
        for q in quotas:
            if is_premium_model(q.get("display_name", "")):
                source = q.get("source_type", "")
                if source in has_premium:
                    has_premium[source] = True

        filtered = []
        for q in quotas:
            name = q.get("display_name", "")
            source = q.get("source_type", "")
            if "2.0" in name:
                continue
            if is_premium_model(name):
                filtered.append(q)
            elif not has_premium.get(source, False):
                filtered.append(q)
        return filtered

    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        source = quota.get("source_type", "")
        name = quota.get("display_name", "")
        source_prio = 0 if source == "Gemini CLI" else 1
        family_prio = FAMILY_SORT_ORDER.get(
            next((k for k in FAMILY_SORT_ORDER if k in name), ""), 99
        )
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

        return self.login(services=services)

    def login(self, **kwargs) -> Dict[str, Any]:
        """Perform OAuth login flow and return account data."""
        services = kwargs.get("services", ["AG", "CLI"])
        manual_project_id = kwargs.get("manual_project_id")

        creds, session = self._run_oauth_flow()
        email = self._fetch_email(session)
        project_ids = self._discover_project_ids(session, manual_project_id)

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
                "Warning: No Google Cloud project could be automatically associated. "
                "CLI quotas might be limited."
            )

        return account_data

    def _run_oauth_flow(self):
        """Run the OAuth installed app flow and return (credentials, session)."""
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
        session = google.auth.transport.requests.AuthorizedSession(creds)
        return creds, session

    def _fetch_email(self, session) -> str:
        """Fetch the authenticated user's email from Google."""
        userinfo = session.get("https://www.googleapis.com/oauth2/v3/userinfo").json()
        email = userinfo.get("email")
        if not email:
            raise Exception("Failed to retrieve email from Google")
        return email

    def _discover_project_ids(
        self, session, manual_project_id: Optional[str] = None
    ) -> Dict[str, str]:
        """Discover the Google Cloud project ID, using multiple fallback strategies."""
        if manual_project_id:
            return {
                "projectId": manual_project_id,
                "managedProjectId": manual_project_id,
            }

        logger.info("Searching for associated Google Cloud project...")

        project_ids = (
            self._try_load_code_assist(session)
            or self._try_get_managed_project(session)
            or self._try_cloud_resource_manager(session)
            or {
                "projectId": "rising-fact-p41fc",
                "managedProjectId": "rising-fact-p41fc",
            }
        )
        return project_ids

    def _try_load_code_assist(self, session) -> Optional[Dict[str, str]]:
        """Try loadCodeAssist endpoints to discover project ID."""
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

        for url_base in LOAD_CODE_ASSIST_ENDPOINTS:
            try:
                resp = session.post(
                    f"{url_base}/v1internal:loadCodeAssist",
                    headers=headers,
                    json={"metadata": metadata},
                    timeout=10,
                )
                if resp.status_code == 200:
                    p_id = self._extract_project_id(resp.json())
                    if p_id:
                        return {"projectId": p_id, "managedProjectId": p_id}
            except Exception:
                pass
        return None

    @staticmethod
    def _extract_project_id(data: dict) -> Optional[str]:
        """Extract project ID from a loadCodeAssist response."""
        project_data = data.get("cloudaicompanionProject")
        if isinstance(project_data, str):
            return project_data
        if isinstance(project_data, dict):
            return project_data.get("id")
        return None

    def _try_get_managed_project(self, session) -> Optional[Dict[str, str]]:
        """Try getManagedProject endpoint to discover project ID."""
        headers = {
            "User-Agent": "antigravity/1.15.8 linux/x64",
            "X-Goog-Api-Client": "google-cloud-sdk vscode/1.96.0",
            "Client-Metadata": '{"ideType":"VSCODE","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
        }
        try:
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
                        return {"projectId": managed_id, "managedProjectId": managed_id}
        except Exception:
            pass
        return None

    def _try_cloud_resource_manager(self, session) -> Optional[Dict[str, str]]:
        """Try Cloud Resource Manager to discover project ID via project listing."""
        try:
            projects = self._list_crm_projects(session)
            if not projects:
                return None
            return self._pick_best_project(projects)
        except Exception:
            return None

    @staticmethod
    def _list_crm_projects(session, max_pages=3) -> List[Dict]:
        """List projects from Cloud Resource Manager, paginating up to max_pages."""
        all_projects = []
        next_page_token = None

        for _ in range(max_pages):
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
        return all_projects

    @staticmethod
    def _pick_best_project(projects: List[Dict]) -> Optional[Dict[str, str]]:
        """Pick the best project from a list using priority rules."""
        active = [p for p in projects if p.get("lifecycleState") == "ACTIVE"]

        # Priority 1: gen-lang-client
        gen_lang = [p for p in active if "gen-lang-client" in p.get("projectId", "")]
        if gen_lang:
            gen_lang.sort(key=lambda x: x.get("createTime", ""), reverse=True)
            pid = gen_lang[0]["projectId"]
            return {"projectId": pid, "managedProjectId": pid}

        # Priority 2: gemini or cloud-code
        ai_projects = [
            p
            for p in active
            if "gemini" in p.get("projectId", "").lower()
            or "cloud-code" in p.get("projectId", "").lower()
        ]
        if ai_projects:
            ai_projects.sort(key=lambda x: x.get("createTime", ""), reverse=True)
            pid = ai_projects[0]["projectId"]
            return {"projectId": pid, "managedProjectId": pid}

        # Priority 3: newest active
        if active:
            active.sort(key=lambda x: x.get("createTime", ""), reverse=True)
            pid = active[0]["projectId"]
            return {"projectId": pid, "managedProjectId": pid}

        return None

    def fetch_quotas(self) -> List[Dict[str, Any]]:
        services = self.account_data.get("services", ["AG", "CLI"])
        project_id = self.account_data.get("projectId") or self.account_data.get(
            "managedProjectId"
        )

        if not services:
            return []

        quotas = self._fetch_services_parallel(services, project_id)

        if not quotas:
            quotas = self._load_cached_quotas()

        return quotas

    def _fetch_services_parallel(self, services, project_id) -> List[Dict[str, Any]]:
        """Fetch CLI and AG quotas in parallel."""
        quotas = []
        fetchers = {}
        if "CLI" in services:
            fetchers["CLI"] = lambda: self._fetch_gemini_cli_quotas(project_id)
        if "AG" in services:
            fetchers["AG"] = lambda: self._fetch_antigravity_quotas(project_id)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(fetchers) or 1
        ) as executor:
            futures = {name: executor.submit(fn) for name, fn in fetchers.items()}
            for name, future in futures.items():
                try:
                    quotas.extend(future.result())
                except Exception:
                    pass
        return quotas

    def _load_cached_quotas(self) -> List[Dict[str, Any]]:
        """Load quotas from cachedQuota in account_data as fallback."""
        cached = self.account_data.get("cachedQuota", {})
        if not cached:
            return []

        quotas = []
        for family, q_data in cached.items():
            display_name = CACHED_FAMILY_MAP.get(
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
        headers = {
            "Authorization": f"Bearer {self.credentials.token}",
            "Content-Type": "application/json",
            "User-Agent": _get_user_agent(),
        }

        try:
            response = self._make_quota_request(url, headers, project_id)
            if response.status_code == 200:
                return self._parse_cli_quota_response(response.json())
            if response.status_code == 403:
                return self._parse_cli_403_error(response)
        except Exception:
            pass
        return []

    def _make_quota_request(self, url, headers, project_id):
        """Make a quota request, falling back to no project_id on failure."""
        if project_id and not self._prefer_no_project:
            response = requests.post(
                url,
                headers=headers,
                json={"project": project_id},
                timeout=DEFAULT_QUOTA_TIMEOUT,
            )
            if response.status_code == 200:
                self._prefer_no_project = False
                return response

            logger.debug(
                f"Quota Error ({project_id}) [{response.status_code}]: {response.text}"
            )

            self._prefer_no_project = True

        response = requests.post(
            url,
            headers=headers,
            json={},
            timeout=DEFAULT_QUOTA_TIMEOUT,
        )
        if response.status_code == 200:
            self._prefer_no_project = True
        return response

    @staticmethod
    def _parse_cli_quota_response(data: dict) -> List[Dict[str, Any]]:
        """Parse a successful CLI quota response into quota dicts."""
        logger.debug(f"CLI Quota Success: {data}")
        buckets = data.get("buckets", [])

        entries = []
        for bucket in buckets:
            model_id = bucket.get("modelId")
            if not model_id:
                continue
            family = classify_cli_model(model_id)
            if not family:
                continue
            entries.append(
                (
                    family,
                    bucket.get("remainingFraction", 1.0),
                    bucket.get("resetTime"),
                )
            )

        groups = _group_by_family(entries)
        return [
            {
                "name": f"{family} (CLI)",
                "display_name": f"{family} (CLI)",
                "remaining_pct": info["remaining_fraction"] * 100,
                "reset": info["reset"],
                "source_type": "Gemini CLI",
            }
            for family, info in groups.items()
        ]

    @staticmethod
    def _parse_cli_403_error(response) -> List[Dict[str, Any]]:
        """Parse a 403 error from the CLI quota endpoint."""
        try:
            err_data = response.json()
            details = err_data.get("error", {}).get("details", [])
            for d in details:
                if d.get("reason") == "VALIDATION_REQUIRED":
                    val_url = d.get("metadata", {}).get("validation_url")
                    if val_url:
                        return [
                            {
                                "name": "Validation Required",
                                "display_name": "Validation Required",
                                "is_error": True,
                                "message": "Verify your account to continue.",
                                "url": val_url,
                                "source_type": "Gemini CLI",
                            }
                        ]
                elif d.get("reason") == "SUBSCRIPTION_REQUIRED":
                    return [
                        {
                            "name": "Subscription Required",
                            "display_name": "License Missing",
                            "is_error": True,
                            "message": " No Code Assist license found. Set a valid project with --project-id",
                            "source_type": "Gemini CLI",
                        }
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

        try:
            response = self._make_quota_request(url, headers, project_id)
            if response.status_code == 200:
                return self._parse_ag_quota_response(response.json())
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_ag_quota_response(data: dict) -> List[Dict[str, Any]]:
        """Parse a successful Antigravity quota response into quota dicts."""
        logger.debug(f"AG Quota Success: {data}")
        models = data.get("models", {})

        entries = []
        for model_id, info in models.items():
            display_name = info.get("displayName", model_id)
            if not is_ag_model_relevant(display_name, model_id):
                continue

            quota_info = info.get("quotaInfo")
            if not quota_info:
                continue

            family = classify_ag_model(display_name, model_id) or display_name
            entries.append(
                (
                    family,
                    quota_info.get("remainingFraction", 1.0),
                    quota_info.get("resetTime"),
                )
            )

        groups = _group_by_family(entries)
        return [
            {
                "name": f"{family} (AG)",
                "display_name": f"{family} (AG)",
                "remaining_pct": info["remaining_fraction"] * 100,
                "reset": info["reset"],
                "source_type": "Antigravity",
            }
            for family, info in groups.items()
        ]
