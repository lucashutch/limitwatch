from typing import Dict, List, Any, Optional
from .providers.google import GoogleProvider
from .providers.chutes import ChutesProvider
from .providers.github_copilot import GitHubCopilotProvider


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

        account_type = self.account_data.get("type", "google")
        if account_type == "chutes":
            self.provider = ChutesProvider(self.account_data)
        elif account_type == "github_copilot":
            self.provider = GitHubCopilotProvider(self.account_data)
        else:
            self.provider = GoogleProvider(self.account_data, self.credentials)

    def fetch_quotas(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetch quotas using the appropriate provider.
        kwargs are ignored for backward compatibility in some calls but providers use account_data.
        """
        return self.provider.fetch_quotas()

    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        """Filter quotas using the provider's logic."""
        return self.provider.filter_quotas(quotas, show_all)

    def get_sort_key(self, quota: Dict[str, Any]) -> Any:
        """Get sort key for a quota item using the provider's logic."""
        return self.provider.get_sort_key(quota)

    def get_color(self, quota: Dict[str, Any]) -> str:
        """Get color for a quota item using the provider's logic."""
        return self.provider.get_color(quota)

    @property
    def short_indicator(self) -> str:
        """Expose provider short indicator for display rendering."""
        return self.provider.short_indicator

    @property
    def primary_color(self) -> str:
        """Expose provider primary color for display rendering."""
        return self.provider.primary_color

    @staticmethod
    def get_available_providers() -> Dict[str, str]:
        """Return a mapping of provider type to user-friendly name."""
        return {
            "google": GoogleProvider({}, None).provider_name,
            "chutes": ChutesProvider({}).provider_name,
            "github_copilot": GitHubCopilotProvider({}).provider_name,
        }
