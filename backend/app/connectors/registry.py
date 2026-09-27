import logging
from typing import Dict, List, Optional, Type
from app.connectors.base import BaseConnector, ConnectorHealth, ConnectorStatus

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """
    Central registry for Synesis external source connectors.
    Manages connector instantiation, discovery, and health inspection.
    """

    def __init__(self):
        self._connectors: Dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register a connector instance by its provider_name."""
        provider = connector.provider_name.lower()
        self._connectors[provider] = connector
        logger.info(f"Registered connector for provider: '{provider}'")

    def get(self, provider_name: str) -> Optional[BaseConnector]:
        """Retrieve connector instance by provider name."""
        return self._connectors.get(provider_name.lower())

    def list_providers(self) -> List[str]:
        """List all registered provider names."""
        return list(self._connectors.keys())

    def check_all_health(self) -> Dict[str, ConnectorHealth]:
        """Run health checks across all registered connectors."""
        results: Dict[str, ConnectorHealth] = {}
        for name, connector in self._connectors.items():
            try:
                results[name] = connector.health_check()
            except Exception as e:
                logger.error(f"Health check failed for connector '{name}': {e}")
                results[name] = ConnectorHealth(
                    provider=name,
                    status=ConnectorStatus.ERROR,
                    error_message=str(e),
                )
        return results


# Global singleton registry
registry = ConnectorRegistry()
