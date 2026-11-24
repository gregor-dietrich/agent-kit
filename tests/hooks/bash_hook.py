"""Runs a Bash guard's prefilter wrapper on a crafted tool payload."""

import json
import os
import subprocess
from pathlib import Path


def _run_payload(hook: Path, payload: dict[str, object], **env: str) -> str:
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


def run_bash_hook(hook: Path, command: str, **env: str) -> str:
    return _run_payload(
        hook, {"tool_name": "Bash", "tool_input": {"command": command}}, **env
    )


def run_agy_command_hook(hook: Path, command: str, **env: str) -> str:
    payload: dict[str, object] = {
        "hookEventName": "PreToolUse",
        "conversationId": "0000",
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": command},
        },
    }
    return _run_payload(hook, payload, **env)
