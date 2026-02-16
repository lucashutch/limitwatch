from typing import List, Dict, Any
from abc import ABC, abstractmethod


class BaseProvider(ABC):
    def __init__(self, account_data: Dict[str, Any]):
        self.account_data = account_data

    @abstractmethod
    def fetch_quotas(self) -> List[Dict[str, Any]]:
        """Fetch quotas from the provider."""
        pass
