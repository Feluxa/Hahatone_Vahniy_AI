from datetime import datetime

from pydantic import BaseModel, ConfigDict

from components.payments.domain.TransferIntent import TransferIntent


class TransferPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[TransferIntent, ...]
    next_cursor: datetime | None
