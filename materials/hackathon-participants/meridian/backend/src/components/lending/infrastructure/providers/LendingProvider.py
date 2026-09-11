from dishka import Provider

from components.lending.infrastructure.providers.LendingRequestProvider import LendingRequestProvider
from components.lending.infrastructure.providers.LendingStoreProvider import LendingStoreProvider


def lending_providers() -> tuple[Provider, Provider]:
    """Return app-store and request-service providers for Dishka assembly."""

    return LendingStoreProvider(), LendingRequestProvider()
