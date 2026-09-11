"""Чтение и валидация входного JSON. Владелец: №1 (перенесено с №4).

Правила (PROTOCOL.md, раздел 1):
  * все поля обязательны; protocol_version == "1.0";
  * относительные пути разрешаются от папки входного JSON;
  * repository существует и является папкой; output_dir НЕ существует;
  * case_id формата "команда/название"; difficulty и language — из Enum;
  * author.name и author.email — непустые строки; все limits > 0; seed — целое (не bool).
Ошибка -> InputError с понятным текстом (все найденные проблемы сразу, а не первая).
"""
from __future__ import annotations

from pathlib import Path

from harness.contracts import CaseInput


class InputError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def load_input(path: Path) -> CaseInput:
    raise NotImplementedError
