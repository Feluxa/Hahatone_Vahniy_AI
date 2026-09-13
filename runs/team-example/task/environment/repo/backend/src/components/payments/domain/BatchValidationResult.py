from pydantic import BaseModel, ConfigDict, Field

from components.payments.domain.BatchValidationIssue import BatchValidationIssue


class BatchValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    batch_reference: str
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    issues: tuple[BatchValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return self.rejected_count == 0
