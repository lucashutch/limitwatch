import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Configure logger
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


class AuthManager:
    def __init__(self, auth_path: Path):
        self.auth_path = auth_path
        self.accounts = []
        self.active_index = 0
        self.load_accounts()

    def load_accounts(self) -> List[Dict[str, Any]]:
        if not self.auth_path.exists():
            self.accounts = []
            return []

        try:
            with open(self.auth_path, "r") as f:
                data = json.load(f)

            self.accounts = data.get("accounts", [])
            self.active_index = data.get("activeIndex", 0)
            return self.accounts
        except Exception:
            # If it's a legacy file or malformed, we might fail here.
            # For now, let's just return empty if it's not a list/dict we expect.
            self.accounts = []
            return []

    def save_accounts(self):
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"accounts": self.accounts, "activeIndex": self.active_index}
        with open(self.auth_path, "w") as f:
            json.dump(data, f, indent=2)

    def get_credentials(self, index: int) -> Optional[Credentials]:
        if index < 0 or index >= len(self.accounts):
            return None

        account = self.accounts[index]
        refresh_token = account.get("refreshToken")
        if not refresh_token:
            return None

        creds = Credentials(
            token=None,  # Will be refreshed
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=ANTIGRAVITY_CLIENT_ID,
            client_secret=ANTIGRAVITY_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return creds

    def refresh_credentials(self, creds: Credentials) -> bool:
        try:
            request = google.auth.transport.requests.Request()
            creds.refresh(request)
            return True
        except Exception:
            return False

    def get_account_info(self, index: int) -> Dict[str, Any]:
        if index < 0 or index >= len(self.accounts):
            return {}
        return self.accounts[index]

    def login(
        self, services: List[str], manual_project_id: Optional[str] = None
    ) -> Optional[str]:
        """Perform OAuth login flow and return the email of the logged in account."""
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

        # Update or add account
        existing_acc = next(
            (
                a
                for a in self.accounts
                if a.get("email") == email and a.get("type", "google") == "google"
            ),
            None,
        )

        # Try to fetch managed project ID and metadata
        project_ids = {}
        if manual_project_id:
            project_ids["projectId"] = manual_project_id
            project_ids["managedProjectId"] = manual_project_id
        else:
            # 1. Try loadCodeAssist (from NoeFabris/opencode-antigravity-auth)
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
                    logger.debug(f"Checking loadCodeAssist at {url_base}...")
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
                            logger.debug(f"Found project via loadCodeAssist: {p_id}")
                            project_ids["projectId"] = p_id
                            project_ids["managedProjectId"] = p_id
                            break
                except Exception as e:
                    logger.debug(f"loadCodeAssist check failed at {url_base}: {e}")

            # 2. Try getManagedProject (previous logic)
            if "projectId" not in project_ids:
                try:
                    headers = {
                        "User-Agent": "antigravity/1.15.8 linux/x64",
                        "X-Goog-Api-Client": "google-cloud-sdk vscode/1.96.0",
                        "Client-Metadata": '{"ideType":"VSCODE","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
                    }
                    for ide in ["VSCODE", "JETBRAINS", "IDE_UNSPECIFIED"]:
                        logger.debug(f"Checking for managed project ({ide})...")
                        resp = session.post(
                            "https://cloudcode-pa.googleapis.com/v1internal:getManagedProject",
                            headers=headers,
                            json={"ideType": ide},
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            managed_id = resp.json().get("projectId")
                            if managed_id:
                                logger.debug(f"Found managed project: {managed_id}")
                                project_ids["managedProjectId"] = managed_id
                                project_ids["projectId"] = managed_id
                                break
                except Exception as e:
                    logger.debug(f"Managed project check failed: {e}")

            # 3. Try Cloud Resource Manager (previous logic)
            if "projectId" not in project_ids:
                try:
                    all_projects = []
                    next_page_token = None
                    for page in range(1, 4):
                        logger.debug(
                            f"Searching Cloud Resource Manager projects (Page {page})..."
                        )
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
                        logger.debug(
                            f"Found {len(all_projects)} total projects. Matching patterns..."
                        )
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
                            logger.debug(
                                f"Selected project: {p_id} (Match: gen-lang-client)"
                            )
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
                                logger.debug(
                                    f"Selected project: {p_id} (Match: name pattern)"
                                )
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
                                logger.debug(
                                    f"Selected project: {p_id} (Fallback: newest active)"
                                )
                                project_ids["projectId"] = p_id
                                project_ids["managedProjectId"] = p_id
                except Exception as e:
                    logger.debug(f"Project listing failed: {e}")

            # 4. Final Fallback (from NoeFabris/opencode-antigravity-auth)
            if "projectId" not in project_ids:
                default_id = "rising-fact-p41fc"
                logger.debug(f"No project found. Using default fallback: {default_id}")
                project_ids["projectId"] = default_id
                project_ids["managedProjectId"] = default_id

        account_data = {
            "type": "google",
            "email": email,
            "refreshToken": creds.refresh_token,
            "services": services,
        }
        account_data.update(project_ids)

        if existing_acc:
            # We want to preserve existing fields like projectId if our new scan found nothing
            for k, v in account_data.items():
                existing_acc[k] = v
        else:
            self.accounts.append(account_data)

        self.save_accounts()

        # Confirmation message for the user
        final_id = project_ids.get("projectId") or project_ids.get("managedProjectId")
        if final_id:
            print(f"Final Project ID: {final_id}")
        else:
            print(
                "Warning: No Google Cloud project could be automatically associated. CLI quotas might be limited."
            )

        return email

    def login_chutes(self, api_key: str) -> str:
        """Perform Chutes.ai login using an API key and return the email/username."""
        import requests

        url = "https://api.chutes.ai/users/me"
        headers = {"Authorization": api_key}

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            raise Exception(f"Failed to authenticate with Chutes.ai: {resp.text}")

        data = resp.json()
        # Chutes might use 'username' or 'email'. We'll check both.
        identifier = data.get("email") or data.get("username") or "Chutes User"

        # Update or add account
        existing_acc = next(
            (
                a
                for a in self.accounts
                if a.get("email") == identifier and a.get("type") == "chutes"
            ),
            None,
        )

        account_data = {
            "type": "chutes",
            "email": identifier,
            "apiKey": api_key,
            "services": ["CHUTES"],
        }

        if existing_acc:
            existing_acc.update(account_data)
        else:
            self.accounts.append(account_data)

        self.save_accounts()
        return identifier

    def logout(self, email: str) -> bool:
        initial_len = len(self.accounts)
        self.accounts = [a for a in self.accounts if a.get("email") != email]
        if len(self.accounts) < initial_len:
            self.save_accounts()
            return True
        return False

    def logout_all(self):
        self.accounts = []
        self.active_index = 0
        self.save_accounts()
