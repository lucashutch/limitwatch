import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import google.auth.transport.requests
from google.oauth2.credentials import Credentials

# Configure logger
logger = logging.getLogger(__name__)

# Hardcoded constants for Antigravity (still needed for get_credentials)
ANTIGRAVITY_CLIENT_ID = (
    "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
)
ANTIGRAVITY_CLIENT_SECRET = "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"


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

    def login(self, account_data: Dict[str, Any]) -> str:
        """Save or update account data from a provider."""
        email = account_data.get("email")
        provider_type = account_data.get("type")
        if not email or not provider_type:
            raise Exception("Account data missing email or type")

        # Update or add account
        existing_acc = next(
            (
                a
                for a in self.accounts
                if a.get("email") == email and a.get("type") == provider_type
            ),
            None,
        )

        if existing_acc:
            existing_acc.update(account_data)
        else:
            self.accounts.append(account_data)

        self.save_accounts()
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
