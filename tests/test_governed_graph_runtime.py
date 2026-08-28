import asyncio
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "system"))

from governed_graph_runtime import (  # noqa: E402
    FileCheckpointStore,
    GraphPlan,
    GraphValidationError,
    GovernedGraphRuntime,
    NodeOutput,
    ResourceGovernor,
    optimize_plan,
)


def node(
    node_id,
    *,
    handler=None,
    provider="local",
    input_schema=None,
    output_schema=None,
    security_classification="INTERNAL",
    estimated_latency_ms=100,
    estimated_cost=0,
    estimated_tokens=0,
    require_evidence=False,
    max_retries=0,
    metadata=None,
):
    return {
        "id": node_id,
        "handler": handler or node_id,
        "provider": provider,
        "input_schema": input_schema or {"type": "object"},
        "output_schema": output_schema or {"type": "object"},
        "security_classification": security_classification,
        "estimated_latency_ms": estimated_latency_ms,
        "estimated_cost": estimated_cost,
        "estimated_tokens": estimated_tokens,
        "require_evidence": require_evidence,
        "max_retries": max_retries,
        "metadata": metadata or {},
    }


def edge(edge_id, source, target, *, kind="data", bindings=None, required=True):
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "kind": kind,
        "bindings": bindings or {},
        "required": required,
    }


class GraphOptimizationTests(unittest.TestCase):
    def test_fake_data_edge_without_consumption_is_pruned(self):
        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a"), node("b")], "edges": [edge("fake", "a", "b")]})
        optimized = optimize_plan(plan)
        self.assertEqual(optimized.pruned_edge_ids, ("fake",))
        self.assertEqual(optimized.plan.edges, ())

    def test_real_data_edge_is_kept(self):
        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [
                node("a", output_schema={"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}}),
                node("b", input_schema={"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}, "additionalProperties": False}),
            ],
            "edges": [edge("real", "a", "b", bindings={"x": "$.value"})],
        })
        optimized = optimize_plan(plan)
        self.assertEqual(optimized.pruned_edge_ids, ())
        self.assertEqual(tuple(e.id for e in optimized.plan.edges), ("real",))

    def test_authority_and_order_edges_are_never_pruned(self):
        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [node("policy"), node("worker"), node("merge")],
            "edges": [edge("authority", "policy", "worker", kind="authority"), edge("order", "worker", "merge", kind="order")],
        })
        self.assertEqual(tuple(e.id for e in optimize_plan(plan).plan.edges), ("authority", "order"))

    def test_cycle_in_effective_graph_is_rejected(self):
        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [node("a"), node("b")],
            "edges": [edge("a-b", "a", "b", kind="order"), edge("b-a", "b", "a", kind="authority")],
        })
        with self.assertRaises(GraphValidationError):
            optimize_plan(plan)

    def test_binding_to_undeclared_target_field_is_rejected(self):
        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [node("a"), node("b", input_schema={"type": "object", "properties": {"known": {"type": "integer"}}, "additionalProperties": False})],
            "edges": [edge("bad", "a", "b", bindings={"unknown": "$.x"})],
        })
        with self.assertRaises(GraphValidationError):
            optimize_plan(plan)

    def test_resource_governor_rejects_fractional_integer_limits(self):
        with self.assertRaises(GraphValidationError):
            ResourceGovernor.from_dict({"max_concurrency": 1.5})
        with self.assertRaises(GraphValidationError):
            ResourceGovernor.from_dict({"max_concurrency": 2, "provider_limits": {"p": 1.25}})
        with self.assertRaises(GraphValidationError):
            ResourceGovernor(max_concurrency=1.5)
        with self.assertRaises(GraphValidationError):
            ResourceGovernor(max_concurrency=2, provider_limits={"p": 1.25})


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_nodes_execute_in_parallel(self):
        active = 0
        peak = 0
        lock = asyncio.Lock()
        release = asyncio.Event()
        both_started = asyncio.Event()

        async def handler(ctx):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    both_started.set()
            await release.wait()
            async with lock:
                active -= 1
            return NodeOutput(data={"id": ctx.node.id})

        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a"), node("b")], "edges": []})
        runtime = GovernedGraphRuntime(ResourceGovernor(max_concurrency=2))
        task = asyncio.create_task(runtime.run(plan, {"a": handler, "b": handler}))
        await asyncio.wait_for(both_started.wait(), timeout=1)
        release.set()
        report = await asyncio.wait_for(task, timeout=1)
        self.assertEqual(peak, 2)
        self.assertEqual(report.telemetry.max_parallelism, 2)
        self.assertEqual(report.status, "success")

    async def test_provider_limit_is_enforced(self):
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def handler(ctx):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.02)
            async with lock:
                active -= 1
            return NodeOutput(data={})

        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a", provider="same"), node("b", provider="same"), node("c", provider="same")], "edges": []})
        report = await GovernedGraphRuntime(ResourceGovernor(max_concurrency=3, provider_limits={"same": 1})).run(plan, {"a": handler, "b": handler, "c": handler})
        self.assertEqual(peak, 1)
        self.assertEqual(report.status, "success")

    async def test_global_concurrency_limit_is_enforced_across_providers(self):
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def handler(ctx):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.02)
            async with lock:
                active -= 1
            return NodeOutput(data={})

        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a", provider="p1"), node("b", provider="p2"), node("c", provider="p3")], "edges": []})
        report = await GovernedGraphRuntime(ResourceGovernor(max_concurrency=2)).run(plan, {"a": handler, "b": handler, "c": handler})
        self.assertEqual(report.status, "success")
        self.assertEqual(peak, 2)
        self.assertEqual(report.telemetry.max_parallelism, 2)

    async def test_schema_rejection_blocks_required_downstream(self):
        called = False

        async def source(ctx):
            return NodeOutput(data={"value": "not-an-integer"})

        async def downstream(ctx):
            nonlocal called
            called = True
            return NodeOutput(data={})

        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [
                node("source", output_schema={"type": "object", "required": ["value"], "properties": {"value": {"type": "integer"}}}),
                node("downstream", input_schema={"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}, "additionalProperties": False}),
            ],
            "edges": [edge("source-downstream", "source", "downstream", bindings={"x": "$.value"})],
        })
        report = await GovernedGraphRuntime().run(plan, {"source": source, "downstream": downstream})
        self.assertFalse(called)
        self.assertEqual(report.nodes["source"].status, "rejected")
        self.assertEqual(report.nodes["downstream"].status, "blocked")
        self.assertEqual(report.telemetry.verifier_failures["schema"], 1)

    async def test_evidence_and_policy_are_enforced_before_fan_in(self):
        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a", require_evidence=True)], "edges": []})

        async def no_evidence(ctx):
            return NodeOutput(data={})

        report = await GovernedGraphRuntime().run(plan, {"a": no_evidence})
        self.assertEqual(report.nodes["a"].status, "rejected")
        self.assertEqual(report.telemetry.verifier_failures["evidence"], 1)

        async def with_evidence(ctx):
            return NodeOutput(data={}, evidence=("sha256:abc",))

        report2 = await GovernedGraphRuntime(policy_verifier=lambda ctx: (False, "policy-denied-for-test")).run(plan, {"a": with_evidence})
        self.assertEqual(report2.nodes["a"].status, "rejected")
        self.assertEqual(report2.telemetry.verifier_failures["policy"], 1)
        self.assertIn("policy-denied-for-test", report2.nodes["a"].error)

    async def test_classification_flow_is_fail_closed(self):
        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [
                node("legal", security_classification="LEGAL_PRIVILEGED"),
                node("internal", security_classification="INTERNAL", input_schema={"type": "object", "properties": {"x": {"type": "integer"}}}),
            ],
            "edges": [edge("legal-internal", "legal", "internal", bindings={"x": "$.x"})],
        })

        async def legal(ctx):
            return NodeOutput(data={"x": 1}, classification="LEGAL_PRIVILEGED")

        async def internal(ctx):
            return NodeOutput(data={})

        report = await GovernedGraphRuntime().run(plan, {"legal": legal, "internal": internal})
        self.assertEqual(report.nodes["legal"].status, "success")
        self.assertEqual(report.nodes["internal"].status, "rejected")
        self.assertEqual(report.telemetry.verifier_failures["trust"], 1)

    async def test_fan_in_is_deterministic_independent_of_completion_order(self):
        observed = []

        async def a(ctx):
            await asyncio.sleep(0.03)
            return NodeOutput(data={"value": "A"})

        async def b(ctx):
            await asyncio.sleep(0.001)
            return NodeOutput(data={"value": "B"})

        async def merge(ctx):
            observed.extend(ctx.dependencies.keys())
            return NodeOutput(data={"joined": ctx.inputs["a"] + ctx.inputs["b"]})

        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [node("a"), node("b"), node("merge", input_schema={"type": "object", "required": ["a", "b"], "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "additionalProperties": False})],
            "edges": [edge("a-m", "a", "merge", bindings={"a": "$.value"}), edge("b-m", "b", "merge", bindings={"b": "$.value"})],
        })
        report = await GovernedGraphRuntime().run(plan, {"a": a, "b": b, "merge": merge})
        self.assertEqual(observed, ["a", "b"])
        self.assertEqual(report.nodes["merge"].output.data["joined"], "AB")
        self.assertEqual([x["node_id"] for x in report.nodes["merge"].output.dependency_provenance], ["a", "b"])

    async def test_checkpoint_resume_and_graph_hash_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            calls = 0

            async def handler(ctx):
                nonlocal calls
                calls += 1
                return NodeOutput(data={"call": calls})

            store = FileCheckpointStore(Path(td))
            plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a")], "edges": []})
            runtime = GovernedGraphRuntime(checkpoint_store=store)
            first = await runtime.run(plan, {"a": handler})
            second = await runtime.run(plan, {"a": handler})
            self.assertEqual(calls, 1)
            self.assertFalse(first.nodes["a"].checkpoint_hit)
            self.assertTrue(second.nodes["a"].checkpoint_hit)
            changed = GraphPlan.from_dict({"version": "2", "nodes": [node("a", metadata={"revision": 2})], "edges": []})
            third = await runtime.run(changed, {"a": handler})
            self.assertEqual(calls, 2)
            self.assertFalse(third.nodes["a"].checkpoint_hit)

    async def test_tampered_checkpoint_is_never_reused(self):
        with tempfile.TemporaryDirectory() as td:
            calls = 0

            async def handler(ctx):
                nonlocal calls
                calls += 1
                return NodeOutput(data={"call": calls})

            store = FileCheckpointStore(Path(td))
            plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a")], "edges": []})
            runtime = GovernedGraphRuntime(checkpoint_store=store)
            await runtime.run(plan, {"a": handler})
            checkpoint = next(Path(td).rglob("a.json"))
            raw = json.loads(checkpoint.read_text())
            raw["output"]["data"]["call"] = 999
            checkpoint.write_text(json.dumps(raw))
            second = await runtime.run(plan, {"a": handler})
            self.assertEqual(calls, 2)
            self.assertFalse(second.nodes["a"].checkpoint_hit)
            self.assertEqual(second.nodes["a"].output.data["call"], 2)

    async def test_retries_are_bounded_and_telemetry_records_them(self):
        attempts = 0

        async def flaky(ctx):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient")
            return NodeOutput(data={})

        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a", max_retries=1)], "edges": []})
        report = await GovernedGraphRuntime().run(plan, {"a": flaky})
        self.assertEqual(attempts, 2)
        self.assertEqual(report.nodes["a"].status, "success")
        self.assertEqual(report.telemetry.retries, 1)

    async def test_parallelism_economics_can_force_serial_execution(self):
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def handler(ctx):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            return NodeOutput(data={})

        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a", estimated_latency_ms=10), node("b", estimated_latency_ms=10)], "edges": []})
        report = await GovernedGraphRuntime(ResourceGovernor(max_concurrency=2, parallel_value_threshold_ms=1000)).run(plan, {"a": handler, "b": handler})
        self.assertEqual(peak, 1)
        self.assertEqual(report.telemetry.max_parallelism, 1)

    async def test_resource_budget_rejects_before_any_handler_runs(self):
        called = False

        async def handler(ctx):
            nonlocal called
            called = True
            return NodeOutput(data={})

        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a", estimated_cost=2.0, estimated_tokens=1000)], "edges": []})
        runtime = GovernedGraphRuntime(ResourceGovernor(max_total_estimated_cost=1.0, max_total_estimated_tokens=500))
        with self.assertRaises(GraphValidationError):
            await runtime.run(plan, {"a": handler})
        self.assertFalse(called)

    async def test_optional_failed_branch_is_explicitly_visible_to_fan_in(self):
        observed = {}

        async def optional(ctx):
            raise RuntimeError("optional branch failed")

        async def merge(ctx):
            observed.update(ctx.dependency_status)
            self.assertNotIn("maybe", ctx.inputs)
            return NodeOutput(data={"degraded": True})

        plan = GraphPlan.from_dict({
            "version": "1",
            "nodes": [node("optional"), node("merge", input_schema={"type": "object", "properties": {"maybe": {"type": "integer"}}, "additionalProperties": False})],
            "edges": [edge("optional-merge", "optional", "merge", bindings={"maybe": "$.value"}, required=False)],
        })
        report = await GovernedGraphRuntime().run(plan, {"optional": optional, "merge": merge})
        self.assertEqual(report.nodes["optional"].status, "failed")
        self.assertEqual(report.nodes["merge"].status, "success")
        self.assertEqual(report.status, "degraded")
        self.assertEqual(observed, {"optional": "failed"})

    async def test_missing_handler_fails_node_without_crashing_run(self):
        plan = GraphPlan.from_dict({"version": "1", "nodes": [node("a", handler="missing")], "edges": []})
        report = await GovernedGraphRuntime().run(plan, {})
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.nodes["a"].status, "failed")
        self.assertIn("handler", report.nodes["a"].error)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class NativeExecutionBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_programmatic_backend_runs_bounded_tool_sequence_and_records_trace(self):
        from native_execution_backends import ProgrammaticToolExecutor
        calls=[]
        async def lookup(x): calls.append(('lookup',x)); return {'v':x+1}
        async def finish(v): calls.append(('finish',v)); return {'answer':v*2}
        ex=ProgrammaticToolExecutor({'lookup':lookup,'finish':finish}, allowed_tools={'lookup','finish'}, max_calls=4)
        result=await ex.run([{'tool':'lookup','args':{'x':2},'save_as':'a'},{'tool':'finish','args':{'v':{'$ref':'a.v'}}}])
        self.assertEqual(result.data, {'answer':6}); self.assertEqual(calls,[('lookup',2),('finish',3)])
        self.assertEqual([x['tool'] for x in result.trace],['lookup','finish'])

    async def test_programmatic_backend_rejects_unapproved_tool_without_calling_it(self):
        from native_execution_backends import ProgrammaticToolExecutor, ExecutionBackendError
        called=False
        async def dangerous():
            nonlocal called; called=True
        ex=ProgrammaticToolExecutor({'dangerous':dangerous}, allowed_tools=set())
        with self.assertRaises(ExecutionBackendError): await ex.run([{'tool':'dangerous','args':{}}])
        self.assertFalse(called)

    async def test_native_multiagent_executor_parallelizes_bounded_subtasks_and_synthesizes(self):
        from native_execution_backends import NativeMultiAgentExecutor
        active=0; peak=0; lock=asyncio.Lock()
        async def worker(task):
            nonlocal active,peak
            async with lock: active+=1; peak=max(peak,active)
            await asyncio.sleep(.02)
            async with lock: active-=1
            return task.upper()
        async def synthesize(rows): return '|'.join(rows)
        out=await NativeMultiAgentExecutor(worker,synthesize,max_subagents=2).run(['a','b'])
        self.assertEqual(out.data,'A|B'); self.assertEqual(peak,2); self.assertEqual(len(out.subagent_results),2)

class ExecutionStateIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_execution_ledger_reuses_verified_node_without_checkpoint(self):
        from execution_state import ExecutionStateLedger
        calls = 0
        async def handler(ctx):
            nonlocal calls
            calls += 1
            return NodeOutput(data={'call': calls})

        ledger = ExecutionStateLedger()
        runtime = GovernedGraphRuntime(execution_state_ledger=ledger)
        plan = GraphPlan.from_dict({'version': '1', 'nodes': [node('a', metadata={'execution_state_reusable': True})], 'edges': []})
        first = await runtime.run(plan, {'a': handler})
        second = await runtime.run(plan, {'a': handler})
        self.assertEqual(calls, 1)
        self.assertEqual(first.telemetry.execution_state_hits, 0)
        self.assertEqual(second.telemetry.execution_state_hits, 1)
        self.assertEqual(second.nodes['a'].output.data, {'call': 1})


    async def test_execution_ledger_does_not_reuse_node_without_reusable_contract(self):
        from execution_state import ExecutionStateLedger
        calls = 0
        async def handler(ctx):
            nonlocal calls
            calls += 1
            return NodeOutput(data={'call': calls})
        ledger = ExecutionStateLedger()
        runtime = GovernedGraphRuntime(execution_state_ledger=ledger)
        plan = GraphPlan.from_dict({'version': '1', 'nodes': [node('a')], 'edges': []})
        await runtime.run(plan, {'a': handler})
        second = await runtime.run(plan, {'a': handler})
        self.assertEqual(calls, 2)
        self.assertEqual(second.telemetry.execution_state_hits, 0)

    async def test_verified_progress_is_visible_to_next_node_as_fresh_context(self):
        from execution_state import DurableTaskStateStore
        with tempfile.TemporaryDirectory() as td:
            store = DurableTaskStateStore(Path(td))
            observed = {}
            async def build(ctx):
                self.assertEqual(ctx.continuation_state['completed_requirements'], [])
                return NodeOutput(data={'git_head': 'abc123'}, evidence=('sha256:build-proof',))
            async def verify(ctx):
                observed.update(ctx.continuation_state)
                return NodeOutput(data={'ok': True}, evidence=('sha256:verify-proof',))

            plan = GraphPlan.from_dict({
                'version': '1',
                'metadata': {'long_horizon': {
                    'task_id': 'upgrade-1', 'objective': 'finish upgrade',
                    'requirements': [{'id': 'r1', 'text': 'build complete'}, {'id': 'r2', 'text': 'verification complete'}]
                }},
                'nodes': [
                    node('build', require_evidence=True, metadata={'completes_requirement': 'r1', 'environment_fields': ['git_head'], 'next_subtask': 'run verification'}),
                    node('verify', require_evidence=True, metadata={'completes_requirement': 'r2'}),
                ],
                'edges': [edge('build-verify', 'build', 'verify', kind='order')],
            })
            report = await GovernedGraphRuntime(task_state_store=store).run(plan, {'build': build, 'verify': verify})
            self.assertEqual(report.status, 'success')
            self.assertEqual(observed['completed_requirements'][0]['id'], 'r1')
            self.assertEqual(observed['environment_state']['git_head'], 'abc123')
            self.assertEqual(observed['next_subtask'], 'run verification')
            final = store.load('upgrade-1')
            self.assertEqual({x['id'] for x in final['completed_requirements']}, {'r1', 'r2'})
            self.assertEqual(final['remaining_requirements'], [])

    async def test_rejected_node_is_recorded_as_attempt_but_never_completes_requirement(self):
        from execution_state import DurableTaskStateStore
        with tempfile.TemporaryDirectory() as td:
            store = DurableTaskStateStore(Path(td))
            async def bad(ctx):
                return NodeOutput(data={'ok': False})
            plan = GraphPlan.from_dict({
                'version': '1',
                'metadata': {'long_horizon': {
                    'task_id': 'upgrade-2', 'objective': 'finish upgrade',
                    'requirements': [{'id': 'r1', 'text': 'evidence backed success'}]
                }},
                'nodes': [node('bad', require_evidence=True, metadata={'completes_requirement': 'r1'})],
                'edges': [],
            })
            report = await GovernedGraphRuntime(task_state_store=store).run(plan, {'bad': bad})
            self.assertEqual(report.nodes['bad'].status, 'rejected')
            state = store.load('upgrade-2')
            self.assertEqual(state['completed_requirements'], [])
            self.assertEqual(state['remaining_requirements'][0]['id'], 'r1')
            self.assertEqual(state['rejected_attempts'][0]['requirement_id'], 'r1')

class ProgrammaticExecutionStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_programmatic_tools_reuse_success_only_until_required_resource_changes(self):
        from execution_state import ExecutionStateLedger
        from native_execution_backends import ProgrammaticToolExecutor
        ledger = ExecutionStateLedger()
        ledger.observe('repo', 'sha256:r1', source='git')
        calls = 0
        async def inspect_repo():
            nonlocal calls
            calls += 1
            return {'count': calls}
        executor = ProgrammaticToolExecutor({'inspect': inspect_repo}, allowed_tools={'inspect'}, state_ledger=ledger)
        steps = [{'tool': 'inspect', 'args': {}, 'requires': ['repo']}]
        first = await executor.run(steps)
        second = await executor.run(steps)
        self.assertEqual(first.data, {'count': 1})
        self.assertEqual(second.data, {'count': 1})
        self.assertEqual(calls, 1)
        self.assertTrue(second.trace[0]['reused'])
        ledger.record_mutation('repo', 'sha256:r2', source='git')
        third = await executor.run(steps)
        self.assertEqual(third.data, {'count': 2})
        self.assertEqual(calls, 2)
        self.assertFalse(third.trace[0]['reused'])

class ProgrammaticReuseContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_programmatic_tool_without_state_dependencies_is_not_reused_by_default(self):
        from execution_state import ExecutionStateLedger
        from native_execution_backends import ProgrammaticToolExecutor
        calls = 0
        async def current_time_like():
            nonlocal calls
            calls += 1
            return {'value': calls}
        ex = ProgrammaticToolExecutor({'current': current_time_like}, allowed_tools={'current'}, state_ledger=ExecutionStateLedger())
        await ex.run([{'tool': 'current', 'args': {}}])
        second = await ex.run([{'tool': 'current', 'args': {}}])
        self.assertEqual(calls, 2)
        self.assertFalse(second.trace[0]['reused'])

class DefaultStateWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_execution_state_ledger_is_active_by_default_without_enabling_reuse(self):
        seen = {}
        async def a(ctx):
            return NodeOutput(data={'x': 1})
        async def b(ctx):
            seen.update(ctx.execution_state)
            return NodeOutput(data={'ok': True})
        plan = GraphPlan.from_dict({
            'version': '1',
            'nodes': [node('a'), node('b')],
            'edges': [edge('a-b', 'a', 'b', kind='order')],
        })
        report = await GovernedGraphRuntime().run(plan, {'a': a, 'b': b})
        self.assertEqual(report.status, 'success')
        self.assertEqual(seen['schema_version'], 'hermes-execution-state-v1')
        self.assertTrue(any(x['operation'] == 'graph-node:a' for x in seen['attempts']))

    async def test_long_horizon_uses_default_durable_store_path_from_environment(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {'HERMES_TASK_STATE_DIR': td}):
            async def handler(ctx):
                return NodeOutput(data={'ok': True}, evidence=('sha256:proof',))
            plan = GraphPlan.from_dict({
                'version': '1',
                'metadata': {'long_horizon': {
                    'task_id': 'default-store', 'objective': 'finish',
                    'requirements': [{'id': 'r1', 'text': 'complete'}],
                }},
                'nodes': [node('a', require_evidence=True, metadata={'completes_requirement': 'r1'})],
                'edges': [],
            })
            report = await GovernedGraphRuntime().run(plan, {'a': handler})
            self.assertEqual(report.status, 'success')
            state_path = Path(td) / 'default-store.json'
            self.assertTrue(state_path.is_file())
            raw = json.loads(state_path.read_text())
            self.assertEqual(raw['completed_requirements'][0]['id'], 'r1')
