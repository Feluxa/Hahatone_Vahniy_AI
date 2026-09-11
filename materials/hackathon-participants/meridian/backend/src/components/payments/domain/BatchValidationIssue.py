from pydantic import BaseModel, ConfigDict


class BatchValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_reference: str
    code: str
    message: str
