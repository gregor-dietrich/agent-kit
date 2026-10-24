"""Runs a Bash guard's prefilter wrapper on a crafted tool payload."""

import json
import os
import subprocess
from pathlib import Path


def run_bash_hook(hook: Path, command: str, **env: str) -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run(
        ["bash", str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env={**os.environ, **env},
    )
    return result.stdout
