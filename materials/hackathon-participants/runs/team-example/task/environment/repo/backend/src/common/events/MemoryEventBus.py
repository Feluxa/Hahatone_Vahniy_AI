from pydantic import BaseModel

from common.events.IEventBus import IEventBus


class MemoryEventBus(IEventBus):
    def __init__(self) -> None:
        self.events: list[BaseModel] = []

    async def publish(self, event: BaseModel) -> None:
        self.events.append(event.model_copy(deep=True))
