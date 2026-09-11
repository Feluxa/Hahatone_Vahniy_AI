from __future__ import annotations

import subprocess
import time
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
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["docker", "build", "-t", tag, "."]
        start_time = time.monotonic()
        digest: str | None = None
        ok = False

        try:
            res = subprocess.run(
                cmd,
                cwd=env_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_sec,
                encoding="utf-8",
                errors="replace",
            )
            duration = time.monotonic() - start_time
            log_path.write_text(res.stdout, encoding="utf-8", errors="replace")
            ok = res.returncode == 0
            if ok:
                try:
                    inspect_res = subprocess.run(
                        ["docker", "inspect", "--format={{index .RepoDigests 0}}", tag],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    if inspect_res.returncode == 0 and inspect_res.stdout.strip():
                        val = inspect_res.stdout.strip()
                        digest = val.split("@", 1)[1] if "@" in val else val
                    if not digest:
                        img_res = subprocess.run(
                            ["docker", "images", "--no-trunc", "--quiet", tag],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            text=True,
                            encoding="utf-8",
                        )
                        if img_res.returncode == 0 and img_res.stdout.strip():
                            digest = img_res.stdout.strip()
                except Exception:
                    digest = None
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start_time
            out = exc.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            log_path.write_text(f"{out}\n[TIMEOUT expired after {timeout_sec}s]\n", encoding="utf-8")
            ok = False

        return BuildOutcome(
            ok=ok,
            image_tag=tag,
            image_digest=digest,
            duration_sec=round(duration, 3),
            log_path=log_path,
        )

    def run(
        self, image: str, command: list[str], *, mounts: list[Mount], limits: Limits,
        timeout_sec: int, log_dir: Path,
    ) -> ContainerOutcome:
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "stdout.log"
        stderr_path = log_dir / "stderr.log"

        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--cpus", str(limits.cpus),
            "--memory", f"{limits.memory_mb}m",
        ]
        for m in mounts:
            ro = ":ro" if m.read_only else ""
            host_p = m.host.resolve().as_posix()
            cmd.extend(["-v", f"{host_p}:{m.container}{ro}"])

        cmd.append(image)
        cmd.extend(command)

        start_time = time.monotonic()
        timed_out = False
        exit_code: int | None = None

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
                encoding="utf-8",
                errors="replace",
            )
            duration = time.monotonic() - start_time
            exit_code = res.returncode
            stdout_path.write_text(res.stdout, encoding="utf-8", errors="replace")
            stderr_path.write_text(res.stderr, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start_time
            timed_out = True
            exit_code = None
            out = getattr(exc, "output", None) or getattr(exc, "stdout", None) or ""
            err = getattr(exc, "stderr", None) or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", errors="replace")
            stdout_path.write_text(f"{out}\n[TIMEOUT expired after {timeout_sec}s]\n", encoding="utf-8")
            stderr_path.write_text(f"{err}\n[TIMEOUT expired after {timeout_sec}s]\n", encoding="utf-8")

        return ContainerOutcome(
            exit_code=exit_code,
            timed_out=timed_out,
            duration_sec=round(duration, 3),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=cmd,
        )

    def remove_image(self, tag: str) -> None:
        try:
            subprocess.run(["docker", "rmi", "-f", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except Exception:
            pass

