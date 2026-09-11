from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CloseRequestModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    business_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
