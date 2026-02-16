from typing import Dict, List, Any, Optional
from .providers.google import GoogleProvider
from .providers.chutes import ChutesProvider


class QuotaClient:
    def __init__(
        self,
        account_data: Optional[Dict[str, Any]] = None,
        credentials: Optional[Any] = None,
        # Legacy parameters for backward compatibility during transition
        api_key: Optional[str] = None,
    ):
        self.account_data = account_data or {}
        self.credentials = credentials

        # If legacy api_key is provided and not in account_data, inject it
        if api_key and "apiKey" not in self.account_data:
            self.account_data["apiKey"] = api_key
            self.account_data["type"] = "chutes"

    def fetch_quotas(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetch quotas using the appropriate provider.
        kwargs are ignored for backward compatibility in some calls but providers use account_data.
        """
        account_type = self.account_data.get("type", "google")

        if account_type == "chutes":
            provider = ChutesProvider(self.account_data)
        else:
            provider = GoogleProvider(self.account_data, self.credentials)

        return provider.fetch_quotas()
