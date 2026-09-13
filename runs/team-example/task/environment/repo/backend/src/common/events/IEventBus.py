from abc import ABC, abstractmethod

from pydantic import BaseModel


class IEventBus(ABC):
    @abstractmethod
    async def publish(self, event: BaseModel) -> None:
        raise NotImplementedError
