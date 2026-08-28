import importlib.util
import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "system"))

from native_execution_backends import build_orca_development_tool  # noqa: E402
from orca_execution_backend import OrcaSession  # noqa: E402


class FakeOrcaBackend:
    def __init__(self):
        self.created = []
        self.waited = []

    def create(self, task):
        self.created.append(task)
        return OrcaSession(
            task_id=task.task_id,
            agent=task.agent,
            worktree_id="repo-1::/tmp/task-1",
            worktree_path="/tmp/task-1",
            terminal_handle="term-1",
            payload={"ok": True},
        )

    def wait_tui_idle(self, handle, *, timeout_ms=60000):
        self.waited.append((handle, timeout_ms))
        return {"status": "idle"}


class OrcaNativeIntegrationTests(unittest.TestCase):
    def test_native_tool_returns_candidate_without_self_promotion(self):
        backend = FakeOrcaBackend()
        tool = build_orca_development_tool(backend=backend, timeout_ms=45000)

        result = tool(
            task_id="task-1",
            agent="codex",
            prompt="Implement the scoped change",
            repo_path="/repo",
            action_category="code_edit",
            classification="INTERNAL",
        )

        self.assertEqual(result["status"], "candidate")
        self.assertFalse(result["verified"])
        self.assertFalse(result["approved_for_promotion"])
        self.assertEqual(result["worktree_id"], "repo-1::/tmp/task-1")
        self.assertEqual(result["terminal_handle"], "term-1")
        self.assertEqual(backend.waited, [("term-1", 45000)])


class OrcaRegistryIntegrationTests(unittest.TestCase):
    def test_registry_exposes_orca_only_as_internal_public_mutating_development_tool(self):
        registry = json.loads((ROOT / "config" / "tool-registry.json").read_text(encoding="utf-8"))
        row = next(tool for tool in registry["tools"] if tool["name"] == "orca.develop")
        self.assertTrue(row["mutating"])
        self.assertEqual(set(row["data_classes"]), {"PUBLIC", "INTERNAL"})
        self.assertEqual(row["source"], "src/system/orca_execution_backend.py")
        self.assertEqual(
            set(row["input_schema"]["required"]),
            {"task_id", "agent", "prompt", "repo_path"},
        )
        self.assertNotIn("FINANCIAL", row["data_classes"])
        self.assertNotIn("LEGAL_PRIVILEGED", row["data_classes"])

    def test_tool_discovery_can_select_orca_for_coding_when_mutation_is_explicitly_allowed(self):
        module_path = ROOT / "src" / "system" / "tool-discovery.py"
        spec = importlib.util.spec_from_file_location("tool_discovery_for_orca", module_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        registry = mod.load_registry(ROOT / "config" / "tool-registry.json")

        rows = mod.search_tools(
            registry,
            "delegate coding implementation to an isolated agent worktree",
            limit=5,
            data_class="INTERNAL",
            allow_mutating=True,
        )
        self.assertIn("orca.develop", [row["name"] for row in rows])


if __name__ == "__main__":
    unittest.main(verbosity=2)
