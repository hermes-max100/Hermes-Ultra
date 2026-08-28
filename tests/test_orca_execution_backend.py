import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "system"))

from orca_execution_backend import (  # noqa: E402
    OrcaDevelopmentPolicy,
    OrcaExecutionBackend,
    OrcaPolicyError,
    OrcaTask,
    verify_candidate,
)


class OrcaPolicyTests(unittest.TestCase):
    def test_internal_code_edit_is_allowed(self):
        decision = OrcaDevelopmentPolicy().authorize("code_edit", "INTERNAL")
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.human_approval_required)

    def test_consequential_and_nondevelopment_authority_fails_closed(self):
        policy = OrcaDevelopmentPolicy()
        blocked = (
            ("production_deploy", "INTERNAL"),
            ("financial_transfer", "FINANCIAL"),
            ("legal_filing", "LEGAL_PRIVILEGED"),
            ("unknown_action", "INTERNAL"),
        )
        for action, classification in blocked:
            with self.subTest(action=action, classification=classification):
                with self.assertRaises(OrcaPolicyError):
                    policy.authorize(action, classification)


class OrcaClientTests(unittest.TestCase):
    def test_linux_binary_prefers_explicit_command_then_orca_ide(self):
        with patch.dict(os.environ, {"ORCA_CLI_COMMAND": "/opt/hermes/bin/orca"}, clear=False):
            self.assertEqual(OrcaExecutionBackend.resolve_binary(), "/opt/hermes/bin/orca")
        with patch.dict(os.environ, {}, clear=True), patch("platform.system", return_value="Linux"):
            self.assertEqual(OrcaExecutionBackend.resolve_binary(), "orca-ide")

    def test_create_uses_agent_first_and_current_terminal_handle(self):
        calls = []
        payload = {
            "worktree": {"id": "repo-1::/tmp/task-1", "path": "/tmp/task-1"},
            "agentTerminalHandle": "term-current",
            "startupTerminal": {"handle": "term-legacy"},
        }

        def runner(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        backend = OrcaExecutionBackend(binary="orca-ide", runner=runner)
        session = backend.create(
            OrcaTask(
                task_id="task-1",
                agent="codex",
                prompt="Implement the verified patch",
                repo_path="/repo",
            )
        )

        self.assertEqual(session.worktree_id, "repo-1::/tmp/task-1")
        self.assertEqual(session.terminal_handle, "term-current")
        self.assertEqual(
            calls[0][0],
            [
                "orca-ide", "worktree", "create",
                "--name", "task-1", "--no-parent",
                "--agent", "codex", "--prompt", "Implement the verified patch",
                "--setup", "inherit", "--json",
            ],
        )
        self.assertEqual(calls[0][1]["cwd"], "/repo")

    def test_wait_targets_tui_idle_not_process_exit(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout='{"status":"idle"}', stderr="")

        backend = OrcaExecutionBackend(binary="orca-ide", runner=runner)
        backend.wait_tui_idle("term-current", timeout_ms=45000)
        self.assertEqual(
            calls[0],
            [
                "orca-ide", "terminal", "wait", "--terminal", "term-current",
                "--for", "tui-idle", "--timeout-ms", "45000", "--json",
            ],
        )

    def test_missing_handle_fails_instead_of_guessing(self):
        def runner(cmd, **kwargs):
            payload = {"worktree": {"id": "repo-1::/tmp/task-1"}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        backend = OrcaExecutionBackend(binary="orca-ide", runner=runner)
        with self.assertRaises(RuntimeError):
            backend.create(OrcaTask(task_id="task-1", agent="codex", prompt="x", repo_path="/repo"))


class OrcaVerificationTests(unittest.TestCase):
    def test_worker_done_is_not_hermes_success(self):
        result = verify_candidate(worker_done=True, tests_passed=False, policy_passed=True)
        self.assertFalse(result.verified)
        self.assertFalse(result.approved_for_promotion)

    def test_independent_tests_and_policy_are_required_for_promotion(self):
        result = verify_candidate(worker_done=True, tests_passed=True, policy_passed=True)
        self.assertTrue(result.verified)
        self.assertTrue(result.approved_for_promotion)


if __name__ == "__main__":
    unittest.main()
