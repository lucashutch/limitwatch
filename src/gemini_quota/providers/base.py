from typing import List, Dict, Any, Tuple
from abc import ABC, abstractmethod


class BaseProvider(ABC):
    def __init__(self, account_data: Dict[str, Any]):
        self.account_data = account_data

    @abstractmethod
    def fetch_quotas(self) -> List[Dict[str, Any]]:
        """Fetch quotas from the provider."""
        ...

    @property
    @abstractmethod
    def source_priority(self) -> int:
        """Priority of this provider's sources in display (lower is higher)."""
        ...

    @property
    @abstractmethod
    def primary_color(self) -> str:
        """Primary color for this provider's output."""
        ...

    @abstractmethod
    def filter_quotas(
        self, quotas: List[Dict[str, Any]], show_all: bool
    ) -> List[Dict[str, Any]]:
        """Filter quotas based on provider-specific rules."""
        ...

    @abstractmethod
    def get_sort_key(self, quota: Dict[str, Any]) -> Tuple[int, int, str]:
        """Return a sort key for a quota item."""
        ...

    @abstractmethod
    def get_color(self, quota: Dict[str, Any]) -> str:
        """Return the color for a quota item."""
        ...

    @abstractmethod
    def login(self, **kwargs) -> Dict[str, Any]:
        """Perform login flow and return account data."""
        ...

    @abstractmethod
    def interactive_login(self, display_manager: Any) -> Dict[str, Any]:
        """Perform an interactive login flow with the user."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """User-friendly name of the provider."""
        ...
