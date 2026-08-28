from __future__ import annotations

import json
from types import SimpleNamespace

from hermes_ultra.integrations.orca import OrcaClient, OrcaTaskSpec


def test_current_create_response_uses_startup_terminal_handle():
    calls = []
    payload = {
        "worktree": {"id": "repo-1::/tmp/wt", "path": "/tmp/wt"},
        "startupTerminal": {"handle": "term-current"},
    }

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    client = OrcaClient(runner=runner)
    result = client.create(OrcaTaskSpec("t1", "codex", "fix tests", "/repo"))

    assert result.ok
    assert result.value.terminal_handle == "term-current"
    assert calls[0] == [
        "orca", "worktree", "create", "--name", "t1", "--no-parent",
        "--agent", "codex", "--prompt", "fix tests", "--setup", "inherit", "--json",
    ]


def test_missing_create_handle_recovers_from_terminal_list():
    calls = []
    create_payload = {"worktree": {"id": "repo-1::/tmp/wt", "path": "/tmp/wt"}}
    list_payload = {
        "terminals": [
            {"handle": "term-shell", "title": "Shell"},
            {"handle": "term-codex", "title": "Codex"},
        ]
    }

    def runner(cmd, **kwargs):
        calls.append(cmd)
        payload = list_payload if cmd[1:3] == ["terminal", "list"] else create_payload
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    client = OrcaClient(runner=runner)
    result = client.create(OrcaTaskSpec("t1", "codex", "fix tests", "/repo"))

    assert result.ok
    assert result.value.terminal_handle == "term-codex"
    assert calls[1] == [
        "orca", "terminal", "list", "--worktree", "id:repo-1::/tmp/wt", "--json",
    ]


def test_start_task_gates_prompt_on_tui_readiness_and_never_claims_completion():
    calls = []
    create_payload = {
        "worktree": {"id": "repo-1::/tmp/wt", "path": "/tmp/wt"},
        "agentTerminalHandle": "term-codex",
    }

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1:3] == ["worktree", "create"]:
            payload = create_payload
        elif cmd[1:3] == ["terminal", "read"]:
            payload = {"text": "implemented patch; tests not independently verified"}
        else:
            payload = {"ok": True}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    client = OrcaClient(runner=runner)
    result = client.start_task(OrcaTaskSpec("t1", "codex", "fix tests", "/repo"))

    assert result.ok
    assert result.value.worker_claimed_complete is False
    assert calls[0] == [
        "orca", "worktree", "create", "--name", "t1", "--no-parent",
        "--agent", "codex", "--setup", "inherit", "--json",
    ]
    assert calls[1][1:3] == ["terminal", "wait"] and "tui-idle" in calls[1]
    assert calls[2][1:3] == ["terminal", "send"]
    assert calls[3][1:3] == ["terminal", "wait"]
    assert calls[4][1:3] == ["terminal", "read"]


def test_failed_command_redacts_secret_bearing_stderr():
    def runner(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="OPENAI_API_KEY=sk-test-super-secret client_secret=oauth-secret-value",
        )

    result = OrcaClient(runner=runner).status()

    assert not result.ok
    assert "sk-test-super-secret" not in result.message
    assert "oauth-secret-value" not in result.message
    assert result.message.count("[REDACTED]") == 2
