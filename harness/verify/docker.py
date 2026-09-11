"""Тонкая обёртка над docker CLI. Владелец: №3.

Каждый run — свежий контейнер: --rm, --network none, --cpus/--memory из Limits, таймаут.
/tests монтируется read-only, /logs — отдельная папка evidence, /solution read-only только для oracle.
Секреты и переменные окружения хоста в контейнер не пробрасываются.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.contracts import Limits


@dataclass(frozen=True)
class Mount:
    host: Path
    container: str
    read_only: bool = True


@dataclass(frozen=True)
class BuildOutcome:
    ok: bool
    image_tag: str
    image_digest: str | None
    duration_sec: float
    log_path: Path


@dataclass(frozen=True)
class ContainerOutcome:
    exit_code: int | None      # None при таймауте
    timed_out: bool
    duration_sec: float
    stdout_path: Path
    stderr_path: Path
    command: list[str]


class DockerRunner:
    def build(self, env_dir: Path, tag: str, *, timeout_sec: int, log_path: Path) -> BuildOutcome:
        raise NotImplementedError

    def run(
        self, image: str, command: list[str], *, mounts: list[Mount], limits: Limits,
        timeout_sec: int, log_dir: Path,
    ) -> ContainerOutcome:
        raise NotImplementedError

    def remove_image(self, tag: str) -> None:
        raise NotImplementedError
