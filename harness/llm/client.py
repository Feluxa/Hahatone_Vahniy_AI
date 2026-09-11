"""Клиент LLM с учётом usage. Владелец: №2.

Каждый вызов добавляет LlmCall в UsageLog (модель, длительность, токены или None).
Ключи берутся только из переменных окружения и никогда не пишутся в файлы и логи.
"""
from __future__ import annotations

from dataclasses import dataclass

from harness.contracts import UsageLog


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    duration_sec: float


class LlmClient:
    def __init__(self, model: str, usage: UsageLog) -> None:
        self.model = model
        self.usage = usage

    def complete(self, system: str, user: str, *, purpose: str, max_tokens: int = 8000) -> LlmResponse:
        raise NotImplementedError
