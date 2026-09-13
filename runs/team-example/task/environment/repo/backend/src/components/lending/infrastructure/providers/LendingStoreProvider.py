from dishka import Provider, Scope, provide
from pydantic import BaseModel

from components.lending.infrastructure.repositories.core.ILendingReadRepository import ILendingReadRepository
from components.lending.infrastructure.repositories.impl.MemoryLendingReadRepository import MemoryLendingReadRepository


class LendingStoreProvider(Provider):
    """Application-scoped local store and read-only repository binding."""

    @provide(scope=Scope.APP)
    def memory_store(self) -> dict[str, dict[tuple[str, ...], BaseModel]]:
        return {"loans": {}, "installments": {}, "payments": {}, "early_funds": {}}

    @provide(scope=Scope.APP, provides=ILendingReadRepository)
    def repository(self, memory_store: dict[str, dict[tuple[str, ...], BaseModel]]) -> MemoryLendingReadRepository:
        return MemoryLendingReadRepository(memory_store)
