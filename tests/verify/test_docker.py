import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from harness.contracts import Limits
from harness.verify.docker import DockerRunner, Mount


def test_docker_runner_run_constructs_flags() -> None:
    runner = DockerRunner()
    limits = Limits(
        agent_timeout_sec=100,
        verifier_timeout_sec=60,
        build_timeout_sec=300,
        cpus=1.5,
        memory_mb=2048,
        storage_mb=4096,
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        log_dir = tmp_p / "logs"
        host_tests = tmp_p / "tests"
        host_tests.mkdir()

        mounts = [Mount(host=host_tests, container="/tests", read_only=True)]

        fake_res = MagicMock()
        fake_res.returncode = 0
        fake_res.stdout = "all tests passed\n"
        fake_res.stderr = ""

        with patch("subprocess.run", return_value=fake_res) as mock_run:
            outcome = runner.run(
                image="test-img:latest",
                command=["sh", "/tests/test.sh"],
                mounts=mounts,
                limits=limits,
                timeout_sec=60,
                log_dir=log_dir,
            )

            assert outcome.exit_code == 0
            assert outcome.timed_out is False
            assert "all tests passed" in outcome.stdout_path.read_text(encoding="utf-8")

            # Проверяем аргументы docker run
            mock_run.assert_called_once()
            called_cmd = mock_run.call_args[0][0]
            assert "docker" in called_cmd
            assert "run" in called_cmd
            assert "--rm" in called_cmd
            assert "--network" in called_cmd
            assert "none" in called_cmd
            assert "--cpus" in called_cmd
            assert "1.5" in called_cmd
            assert "--memory" in called_cmd
            assert "2048m" in called_cmd
            assert any("/tests:ro" in arg for arg in called_cmd)
            assert "test-img:latest" in called_cmd
            assert called_cmd[-2:] == ["sh", "/tests/test.sh"]


def test_docker_runner_run_handles_timeout() -> None:
    runner = DockerRunner()
    limits = Limits(
        agent_timeout_sec=100,
        verifier_timeout_sec=10,
        build_timeout_sec=300,
        cpus=1,
        memory_mb=1024,
        storage_mb=2048,
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        log_dir = tmp_p / "logs"

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="docker run", timeout=10, output="partial", stderr="")):
            outcome = runner.run(
                image="test-img:latest",
                command=["sh", "/tests/test.sh"],
                mounts=[],
                limits=limits,
                timeout_sec=10,
                log_dir=log_dir,
            )

            assert outcome.timed_out is True
            assert outcome.exit_code is None
            assert "[TIMEOUT expired after 10s]" in outcome.stdout_path.read_text(encoding="utf-8")
