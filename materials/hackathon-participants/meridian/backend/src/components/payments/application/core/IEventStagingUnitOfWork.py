from abc import ABC, abstractmethod

from pydantic import BaseModel

from system.uow.IUnitOfWork import IUnitOfWork


class IEventStagingUnitOfWork(IUnitOfWork, ABC):
    """Payments extension to the shared UoW for after-commit domain events."""

    @abstractmethod
    def register_event(self, event: BaseModel) -> None:
        raise NotImplementedError
