from abc import ABC, abstractmethod

from components.payments.application.core.ValidateBatchRequest import ValidateBatchRequest
from components.payments.domain.BatchValidationResult import BatchValidationResult


class IValidateBatchCommand(ABC):
    @abstractmethod
    async def execute(self, request: ValidateBatchRequest) -> BatchValidationResult:
        raise NotImplementedError
