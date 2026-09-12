import argparse
import sys
from unittest.mock import patch, MagicMock
from harness.cli import main
from harness.contracts import Status


def test_cli_success():
    with patch("harness.cli.load_input") as mock_load, \
         patch("harness.cli.run") as mock_run, \
         patch.object(sys, "argv", ["harness", "run", "input.json"]):
        
        mock_case = MagicMock()
        mock_load.return_value = mock_case
        
        mock_result = MagicMock()
        mock_result.status = Status.READY
        mock_run.return_value = mock_result
        
        assert main() == 0


def test_cli_failure():
    with patch("harness.cli.load_input") as mock_load, \
         patch("harness.cli.run") as mock_run, \
         patch.object(sys, "argv", ["harness", "run", "input.json"]):
        
        mock_case = MagicMock()
        mock_load.return_value = mock_case
        
        mock_result = MagicMock()
        mock_result.status = Status.FAILED
        mock_run.return_value = mock_result
        
        assert main() == 1


def test_cli_input_error():
    from harness.protocol.input import InputError
    with patch("harness.cli.load_input") as mock_load, \
         patch.object(sys, "argv", ["harness", "run", "input.json"]):
        
        mock_load.side_effect = InputError("Bad input")
        
        assert main() == 2


def test_cli_unexpected_exception():
    with patch("harness.cli.load_input") as mock_load, \
         patch("harness.cli.run") as mock_run, \
         patch.object(sys, "argv", ["harness", "run", "input.json"]):
        
        mock_load.return_value = MagicMock()
        mock_run.side_effect = RuntimeError("Something bad happened")
        
        assert main() == 1
