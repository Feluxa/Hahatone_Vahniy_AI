from abc import ABC, abstractmethod

from pydantic import BaseModel


class IUnitOfWork(ABC):
    @abstractmethod
    def register_new(self, model: BaseModel) -> None:
        raise NotImplementedError

    @abstractmethod
    def register_dirty(self, model: BaseModel) -> None:
        raise NotImplementedError

    @abstractmethod
    def register_deleted(self, model: BaseModel) -> None:
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError
