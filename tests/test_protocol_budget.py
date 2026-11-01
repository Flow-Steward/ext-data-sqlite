"""The subprocess protocol refuses oversized input before reaching a driver."""

import json
from pathlib import Path
import subprocess
import sys


def test_stdin_is_bounded_before_json_parsing():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "main.py")],
        input=b"x" * (256 * 1024 + 1),
        capture_output=True,
        timeout=10,
        check=False,
    )  # nosec B603
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["error_code"] == "invalid_payload"


def test_invalid_utf8_is_a_protocol_error():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "main.py")],
        input=b"\xff",
        capture_output=True,
        timeout=10,
        check=False,
    )  # nosec B603
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["error_code"] == "invalid_json"
