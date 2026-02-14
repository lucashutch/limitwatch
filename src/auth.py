import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

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
        except Exception as e:
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
        existing_acc = next((a for a in self.accounts if a.get("email") == email), None)

        # Try to fetch managed project ID and metadata
        project_ids = {}
        if manual_project_id:
            project_ids["projectId"] = manual_project_id
            project_ids["managedProjectId"] = manual_project_id
        else:
            # 1. Try getManagedProject
            try:
                headers = {
                    "User-Agent": "antigravity/1.15.8 linux/x64",
                    "X-Goog-Api-Client": "google-cloud-sdk vscode/1.96.0",
                    "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
                }
                resp = session.post(
                    "https://cloudcode-pa.googleapis.com/v1internal:getManagedProject",
                    headers=headers,
                    json={},
                    timeout=10,
                )
                if resp.status_code == 200:
                    managed_id = resp.json().get("projectId")
                    if managed_id:
                        project_ids["managedProjectId"] = managed_id
                        # Also use as default projectId
                        project_ids["projectId"] = managed_id
            except Exception:
                pass

            # 2. Try to find a 'gen-lang-client' project ID using Cloud Resource Manager
            try:
                resp = session.get(
                    "https://cloudresourcemanager.googleapis.com/v1/projects",
                    timeout=10,
                )
                if resp.status_code == 200:
                    projects = resp.json().get("projects", [])
                    gen_lang_projects = [
                        p
                        for p in projects
                        if "gen-lang-client" in p.get("projectId", "")
                    ]
                    if gen_lang_projects:
                        # If we found a gen-lang-client project, it's usually the one for CLI quotas
                        project_ids["projectId"] = gen_lang_projects[0]["projectId"]
                        if "managedProjectId" not in project_ids:
                            project_ids["managedProjectId"] = gen_lang_projects[0][
                                "projectId"
                            ]
                    elif not project_ids and projects:
                        # Fallback to the first project found
                        project_ids["projectId"] = projects[0]["projectId"]
                        project_ids["managedProjectId"] = projects[0]["projectId"]
            except Exception:
                pass

        account_data = {
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
        if "projectId" in project_ids:
            print(f"Associated with project: {project_ids['projectId']}")
        else:
            print(
                "Warning: No Google Cloud project could be automatically associated. CLI quotas might be limited."
            )

        return email

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
