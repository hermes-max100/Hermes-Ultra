import http.client
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hermes_ultra.command_center import (
    AnthropicProvider,
    CommandCenterStore,
    Conflict,
    Council,
    OpenAICompatibleProvider,
    ProviderReply,
    StoreError,
    parse_mentions,
    seed_defaults,
)
from hermes_ultra.command_center.__main__ import seed_demo
from hermes_ultra.command_center.client import CommandCenterClient, CommandCenterClientError
from hermes_ultra.command_center.providers import Availability, estimate_cost
from hermes_ultra.command_center.store import TASK_TRANSITIONS
from hermes_ultra.command_center.server import CommandCenterApp, CommandCenterServer


class FakeProvider:
    def __init__(self, replies=None, available=True, reason="ready"):
        self.replies = replies or {}
        self.available = available
        self.reason = reason
        self.calls = []

    def availability(self, member):
        return Availability(self.available, self.reason)

    def complete(self, member, system, prompt):
        self.calls.append((member["id"], system, prompt))
        reply = self.replies.get(member["id"], f"{member['display_name']} reply")
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, ProviderReply):
            return reply
        return ProviderReply("ok", reply, member["model"], 100, 50, 12)


def make_store():
    tmp = tempfile.TemporaryDirectory()
    store = CommandCenterStore(Path(tmp.name) / "cc.db")
    seed_defaults(store)
    return tmp, store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.store = make_store()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_defaults_seed_lanes_and_roster_without_work_items(self):
        lanes = {lane["id"]: lane for lane in self.store.list_lanes()}
        self.assertEqual(set(lanes), {"lane-research", "lane-build", "lane-content", "lane-ops", "lane-arena", "lane-hermes"})
        self.assertEqual(lanes["lane-hermes"]["ownership"], "observed")
        self.assertEqual(lanes["lane-hermes"]["kind"], "rnd")
        council = [m["id"] for m in self.store.list_members(seat="council")]
        self.assertEqual(council, ["claude", "chatgpt", "meta-muse"])
        self.assertEqual(self.store.list_tasks(), [])
        seed_defaults(self.store)  # idempotent
        self.assertEqual(len(self.store.list_lanes()), 6)

    def test_lane_channels_are_isolated(self):
        self.store.post_lane_message("lane-build", author="gpt", work_type="code", title="build output")
        self.store.post_lane_message("lane-research", author="claude", work_type="research", title="research output")
        build = self.store.lane_messages("lane-build")
        self.assertEqual([m["title"] for m in build], ["build output"])
        self.assertEqual([m["title"] for m in self.store.lane_messages("lane-research")], ["research output"])
        with self.assertRaises(StoreError):
            self.store.post_lane_message("lane-nope", author="x", title="y")
        with self.assertRaises(StoreError):
            self.store.post_lane_message("lane-build", author="x", title="y", work_type="poetry")

    def test_message_cannot_reference_task_in_another_lane(self):
        task = self.store.create_task("lane-research", title="t")
        with self.assertRaises(StoreError):
            self.store.post_lane_message("lane-build", author="x", title="y", task_id=task["id"])

    def test_work_mix_and_health_follow_lane_work(self):
        self.store.post_lane_message("lane-build", author="a", work_type="code", title="1", tokens_in=10, tokens_out=5, cost_usd=0.01)
        self.store.post_lane_message("lane-build", author="a", work_type="test", title="2")
        task = self.store.create_task("lane-build", title="t", state="queued")
        lane = next(l for l in self.store.list_lanes() if l["id"] == "lane-build")
        self.assertEqual(lane["work_mix"], {"code": 1, "test": 1})
        self.assertEqual(lane["tokens_24h"], 15)
        self.assertEqual(lane["health"], "queued")
        self.store.transition_task(task["id"], "running")
        lane = next(l for l in self.store.list_lanes() if l["id"] == "lane-build")
        self.assertEqual(lane["health"], "active")

    def test_task_lifecycle_enforces_transitions_and_evidence(self):
        task = self.store.create_task("lane-build", title="ship it")
        with self.assertRaises(Conflict):
            self.store.transition_task(task["id"], "done", evidence="x")  # backlog -> done is not allowed
        self.store.transition_task(task["id"], "queued")
        self.store.transition_task(task["id"], "running", progress=0.4)
        with self.assertRaises(StoreError):
            self.store.transition_task(task["id"], "blocked")
        blocked = self.store.transition_task(task["id"], "blocked", blocker="waiting on keys")
        self.assertEqual(blocked["blocker"], "waiting on keys")
        self.store.transition_task(task["id"], "running")
        with self.assertRaises(StoreError):
            self.store.transition_task(task["id"], "done")
        done = self.store.transition_task(task["id"], "done", evidence="pytest: 12 passed")
        self.assertEqual(done["evidence"], "pytest: 12 passed")
        self.assertIsNone(done["blocker"])
        self.assertEqual(done["progress"], 1.0)
        self.assertIsNotNone(done["finished_at"])
        detail = self.store.task_detail(task["id"])
        self.assertEqual([e["to_state"] for e in detail["events"]], ["backlog", "queued", "running", "blocked", "running", "done"])
        with self.assertRaises(Conflict):
            self.store.transition_task(task["id"], "running")

    def test_concurrent_transitions_never_skip_validation(self):
        for _ in range(20):
            task = self.store.create_task("lane-build", title="race", state="queued")
            self.store.transition_task(task["id"], "running")
            barrier = threading.Barrier(2)

            def move(to, **kw):
                barrier.wait()
                try:
                    self.store.transition_task(task["id"], to, **kw)
                except StoreError:
                    pass

            threads = [threading.Thread(target=move, args=("queued",)),
                       threading.Thread(target=move, args=("done",), kwargs={"evidence": "e"})]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            events = self.store.task_detail(task["id"])["events"]
            for prev, cur in zip(events, events[1:]):
                self.assertEqual(cur["from_state"], prev["to_state"])
                self.assertIn(cur["to_state"], TASK_TRANSITIONS[cur["from_state"]])

    def test_failed_requires_note(self):
        task = self.store.create_task("lane-ops", title="t", state="queued")
        with self.assertRaises(StoreError):
            self.store.transition_task(task["id"], "failed")
        self.assertEqual(self.store.transition_task(task["id"], "failed", note="403").get("state"), "failed")

    def test_promote_demote_and_reorder_persist(self):
        promoted = self.store.promote("hermes")
        self.assertEqual((promoted["seat"], promoted["rank"]), ("council", 4))
        self.store.demote("chatgpt")
        self.store.reorder("council", ["hermes", "claude", "meta-muse"])
        path = self.store.path
        self.store.close()
        self.store = CommandCenterStore(path)
        self.assertEqual([m["id"] for m in self.store.list_members(seat="council")], ["hermes", "claude", "meta-muse"])
        bench = self.store.list_members(seat="bench")
        self.assertEqual([m["id"] for m in bench], ["gemini", "chatgpt"])
        self.assertEqual([m["rank"] for m in bench], [1, 2])
        topics = [a["topic"] for a in self.store.activity()]
        self.assertIn("council.promoted", topics)
        self.assertIn("council.demoted", topics)

    def test_reorder_must_list_every_member_once(self):
        with self.assertRaises(Conflict):
            self.store.reorder("council", ["claude", "chatgpt"])
        with self.assertRaises(Conflict):
            self.store.reorder("council", ["claude", "claude", "meta-muse"])

    def test_cannot_demote_last_orchestrator(self):
        self.store.demote("chatgpt")
        self.store.demote("meta-muse")
        with self.assertRaises(Conflict):
            self.store.demote("claude")

    def test_credential_env_must_be_a_variable_name(self):
        with self.assertRaises(StoreError):
            self.store.add_member("leaky", display_name="Leaky", provider="openai", model="m", credential_env="sk-live-abc123")
        with self.assertRaises(StoreError):
            self.store.update_member("chatgpt", {"credential_env": "sk-123"})

    def test_experiment_requires_result_to_conclude(self):
        with self.assertRaises(StoreError):
            self.store.create_experiment("lane-hermes", title="H-0", status="concluded")
        created = self.store.create_experiment("lane-hermes", title="H-0", status="concluded", result_summary="held")
        self.assertEqual(created["result_summary"], "held")
        x = self.store.create_experiment("lane-hermes", title="H-1", hypothesis="h")
        with self.assertRaises(StoreError):
            self.store.update_experiment(x["id"], status="concluded")
        self.store.log_experiment(x["id"], "ran 10 prompts", level="result")
        done = self.store.update_experiment(x["id"], status="concluded", result_summary="held", metrics={"score": 8.1})
        self.assertEqual(done["metrics"], {"score": 8.1})
        self.assertEqual(len(self.store.experiment_detail(x["id"])["events"]), 1)

    def test_demo_seed_is_flagged_and_idempotent(self):
        added = seed_demo(self.store)
        self.assertGreater(added, 0)
        self.assertTrue(all(t["demo"] for t in self.store.list_tasks()))
        self.assertTrue(all(m["demo"] for m in self.store.lane_messages("lane-build")))
        self.assertEqual(seed_demo(self.store), 0)


class CouncilTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.store = make_store()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def council(self, provider):
        return Council(self.store, {"anthropic": provider, "openai": provider, "openai_compatible": provider, "manual": provider})

    def test_members_reply_in_rank_order_and_see_earlier_replies(self):
        provider = FakeProvider({"claude": "Ship the bus first.", "chatgpt": "Agree with Claude.", "meta-muse": "Draft copy now."})
        result = self.council(provider).submit("What next?", mode="council", run_async=False)
        self.assertEqual(result["responders"], ["claude", "chatgpt", "meta-muse"])
        self.assertEqual([c[0] for c in provider.calls], ["claude", "chatgpt", "meta-muse"])
        self.assertIn("Claude: Ship the bus first.", provider.calls[1][2])
        self.assertIn("Operator: What next?", provider.calls[0][2])
        rows = self.store.council_messages()
        self.assertEqual([r["speaker_id"] for r in rows], ["operator", "claude", "chatgpt", "meta-muse"])
        self.assertEqual(self.store.activity()[-1]["topic"], "council.round_finished")
        self.assertTrue(all(r["round_id"] == result["round_id"] for r in rows))

    def test_mentions_address_members_and_pull_lane_context(self):
        self.store.post_lane_message("lane-build", author="gpt", work_type="code", title="isolated bus merged", body="+247 -12")
        provider = FakeProvider()
        result = self.council(provider).submit("@hermes thoughts on #lane-build?", run_async=False)
        self.assertEqual(result["responders"], ["hermes"])  # bench members can be invited ad hoc
        self.assertEqual(result["lanes"], ["lane-build"])
        self.assertIn("[CODE] gpt: isolated bus merged", provider.calls[0][2])

    def test_default_round_is_answered_by_the_lead_only(self):
        provider = FakeProvider()
        result = self.council(provider).submit("What next?", run_async=False)
        self.assertEqual((result["responders"], result["mode"]), (["claude"], "lead"))
        self.assertEqual([c[0] for c in provider.calls], ["claude"])

    def test_lead_falls_back_to_next_available_seat(self):
        provider = FakeProvider()
        provider.availability = lambda m: Availability(m["id"] != "claude", "no key" if m["id"] == "claude" else "ready")
        result = self.council(provider).submit("What next?", run_async=False)
        self.assertEqual(result["responders"], ["chatgpt"])
        self.assertEqual([r["speaker_id"] for r in self.store.council_messages()], ["operator", "chatgpt"])

    def test_council_mention_calls_every_seat_plus_invited_bench(self):
        council = self.council(FakeProvider())
        self.assertEqual(council.submit("@council weigh in", run_async=False)["responders"], ["claude", "chatgpt", "meta-muse"])
        result = council.submit("@all and @hermes too", run_async=False)
        self.assertEqual((result["responders"], result["mode"]), (["claude", "chatgpt", "meta-muse", "hermes"], "council"))
        self.assertEqual(council.submit("@chatgpt only", run_async=False)["mode"], "direct")
        with self.assertRaises(StoreError):
            council.submit("hi", mode="everyone", run_async=False)

    def test_mentioned_members_answer_in_rank_order(self):
        council = self.council(FakeProvider())
        self.assertEqual(council.submit("@chatgpt @claude", run_async=False)["responders"], ["claude", "chatgpt"])
        self.assertEqual(council.submit("@hermes @meta-muse", run_async=False)["responders"], ["meta-muse", "hermes"])

    def test_reserved_member_ids_are_rejected(self):
        for reserved in ("council", "all", "lane-x"):
            with self.assertRaises(StoreError):
                self.store.add_member(reserved, display_name="X", provider="manual", model="m")

    def test_parse_mentions(self):
        members, lanes = parse_mentions("@Claude and @meta-muse, see @lane-ops and #lane-build. email a@b.com", {"claude", "meta-muse"})
        self.assertEqual(members, ["claude", "meta-muse"])
        self.assertEqual(lanes, ["lane-ops", "lane-build"])

    def test_offline_member_records_notice_not_a_fabricated_reply(self):
        provider = FakeProvider(available=False, reason="credential env OPENAI_API_KEY is not set on the server")
        self.council(provider).submit("hello", run_async=False)
        rows = self.store.council_messages()[1:]
        self.assertEqual({r["status"] for r in rows}, {"offline"})
        self.assertEqual({r["speaker_kind"] for r in rows}, {"system"})
        self.assertEqual(provider.calls, [])

    def test_errors_and_refusals_do_not_stop_other_members(self):
        provider = FakeProvider({
            "claude": RuntimeError("boom"),
            "chatgpt": ProviderReply("refused", "Declined", "gpt-5"),
        })
        self.council(provider).submit("go", mode="council", run_async=False)
        rows = {r["speaker_id"]: r for r in self.store.council_messages()[1:]}
        self.assertEqual(rows["claude"]["status"], "error")
        self.assertEqual(rows["chatgpt"]["status"], "refused")
        self.assertEqual(rows["meta-muse"]["status"], "ok")
        self.assertEqual(rows["meta-muse"]["speaker_kind"], "model")

    def test_failed_replies_are_left_out_of_later_transcripts(self):
        provider = FakeProvider({"claude": ProviderReply("error", "HTTP 500: upstream", "m")})
        council = self.council(provider)
        council.submit("first", run_async=False)
        provider.calls.clear()
        council.submit("second", run_async=False)
        self.assertNotIn("HTTP 500", provider.calls[0][2])

    def test_disabled_member_is_offline(self):
        self.store.update_member("claude", {"enabled": False})
        available, reason = self.council(FakeProvider()).availability(self.store.get_member("claude"))
        self.assertFalse(available)
        self.assertEqual(reason, "disabled")


class ProviderTests(unittest.TestCase):
    member = {"id": "claude", "display_name": "Claude", "provider": "anthropic", "model": "claude-opus-5-5",
              "effort": "high", "price_in_per_m": None, "price_out_per_m": None, "credential_env": "ANTHROPIC_API_KEY"}

    def test_anthropic_request_uses_fallbacks_and_effort(self):
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                                   usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
                                   content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Hello.")])

        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        reply = AnthropicProvider(lambda api_key: client).complete(self.member, "sys", "prompt")
        self.assertEqual(reply.status, "ok")
        self.assertEqual(reply.text, "Hello.")
        self.assertEqual(captured["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(captured["fallbacks"], "default")
        self.assertEqual(captured["output_config"], {"effort": "high"})
        self.assertNotIn("thinking", captured)
        self.assertEqual(estimate_cost(self.member, reply.tokens_in, reply.tokens_out), 0.014)

    def test_anthropic_client_uses_each_seats_credential_env(self):
        made = []

        def factory(api_key):
            made.append(api_key)
            return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: SimpleNamespace(
                model="claude-opus-5-5", stop_reason="end_turn", usage=None, content=[SimpleNamespace(type="text", text="ok")]))))

        provider = AnthropicProvider(factory)
        with mock.patch.dict(os.environ, {"CC_KEY_A": "key-a", "CC_KEY_B": "key-b"}):
            provider.complete({**self.member, "credential_env": "CC_KEY_A"}, "s", "p")
            provider.complete({**self.member, "credential_env": "CC_KEY_A"}, "s", "p")
            provider.complete({**self.member, "credential_env": "CC_KEY_B"}, "s", "p")
            provider.complete({**self.member, "credential_env": "CC_UNSET"}, "s", "p")
        self.assertEqual(made, ["key-a", "key-b", None])  # cached per key; unset falls back to SDK resolution

    def test_anthropic_refusal_is_reported(self):
        response = SimpleNamespace(model="claude-opus-5-5", stop_reason="refusal", usage=None, content=[],
                                   stop_details=SimpleNamespace(category="cyber"))
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: response)))
        reply = AnthropicProvider(lambda api_key: client).complete(self.member, "s", "p")
        self.assertEqual(reply.status, "refused")
        self.assertIn("cyber", reply.text)

    def test_openai_compatible_sends_bearer_from_env_and_parses_usage(self):
        seen = {}

        def transport(url, headers, body, timeout):
            seen.update(url=url, headers=headers, body=json.loads(body))
            return 200, json.dumps({"model": "gpt-5", "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()

        member = {"id": "chatgpt", "model": "gpt-5", "base_url": "https://api.openai.com/v1/", "credential_env": "CC_TEST_KEY"}
        provider = OpenAICompatibleProvider(transport)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CC_TEST_KEY", None)
            self.assertFalse(provider.availability(member).available)
            os.environ["CC_TEST_KEY"] = "test-value"
            self.assertTrue(provider.availability(member).available)
            reply = provider.complete(member, "sys", "prompt")
        self.assertEqual(seen["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer test-value")
        self.assertEqual(seen["body"]["messages"][0], {"role": "system", "content": "sys"})
        self.assertEqual((reply.status, reply.text, reply.tokens_in, reply.tokens_out), ("ok", "hi", 7, 3))
        self.assertIsNone(estimate_cost({**member, "provider": "openai"}, 7, 3))

    def test_openai_compatible_http_error(self):
        provider = OpenAICompatibleProvider(lambda *a: (401, b'{"error": {"message": "bad key"}}'))
        reply = provider.complete({"id": "x", "model": "m", "base_url": "http://h", "credential_env": None}, "s", "p")
        self.assertEqual(reply.status, "error")
        self.assertIn("HTTP 401: bad key", reply.text)

    @unittest.skipUnless(__import__("importlib").util.find_spec("anthropic"), "anthropic SDK not installed")
    def test_real_sdk_request_against_local_stub(self):
        import anthropic
        from http.server import BaseHTTPRequestHandler, HTTPServer

        captured = {}

        class Stub(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                captured["path"] = self.path
                captured["beta"] = self.headers.get("anthropic-beta")
                captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data = json.dumps({"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                   "content": [{"type": "text", "text": "stub ok"}], "stop_reason": "end_turn",
                                   "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 2}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        stub = HTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=stub.serve_forever, daemon=True).start()
        try:
            factory = lambda api_key: anthropic.Anthropic(api_key="test", base_url=f"http://127.0.0.1:{stub.server_port}", max_retries=0)
            reply = AnthropicProvider(factory).complete(self.member, "sys", "prompt")
        finally:
            stub.shutdown()
        self.assertEqual(reply.status, "ok", reply.text)
        self.assertEqual(captured["path"].split("?")[0], "/v1/messages")
        self.assertIn("server-side-fallback-2026-07-01", captured["beta"])
        self.assertEqual(captured["body"]["fallbacks"], "default")
        self.assertEqual(captured["body"]["output_config"], {"effort": "high"})


class ServerTests(unittest.TestCase):
    token = None

    def setUp(self):
        self.tmp, self.store = make_store()
        self.provider = FakeProvider()
        council = Council(self.store, {k: self.provider for k in ("anthropic", "openai", "openai_compatible", "manual")},
                          spawn=lambda fn: fn())
        self.app = CommandCenterApp(self.store, council, token=self.token)
        self.server = CommandCenterServer(("127.0.0.1", 0), self.app, stream_poll=0.05)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        if self.token:
            hdrs["X-CC-Token"] = self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        try:
            return res.status, json.loads(raw)
        except json.JSONDecodeError:
            return res.status, raw.decode()

    def test_serves_ui_and_state(self):
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Lane Command Center", page)
        status, state = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(len(state["lanes"]), 6)
        self.assertEqual([m["id"] for m in state["council"] if m["seat"] == "council"], ["claude", "chatgpt", "meta-muse"])
        self.assertEqual(self.request("GET", "/../store.py")[0], 404)

    def test_end_to_end_lane_task_and_council_flow(self):
        status, task = self.request("POST", "/api/tasks", {"lane_id": "lane-build", "title": "bus", "state": "queued"})
        self.assertEqual(status, 201)
        status, msg = self.request("POST", "/api/lanes/lane-build/messages",
                                   {"title": "bus diff", "work_type": "code", "model": "gpt-5", "task_id": task["id"], "tokens_in": 5})
        self.assertEqual(status, 201)
        self.assertEqual(self.request("GET", "/api/lanes/lane-research/messages")[1], [])
        self.assertEqual(self.request("GET", "/api/lanes/lane-build/messages?work_type=code")[1][0]["id"], msg["id"])
        self.assertEqual(self.request("POST", f"/api/tasks/{task['id']}/transition", {"to": "running"})[0], 201)
        status, err = self.request("POST", f"/api/tasks/{task['id']}/transition", {"to": "done"})
        self.assertEqual(status, 400)
        self.assertIn("evidence", err["error"])
        self.assertEqual(self.request("POST", f"/api/tasks/{task['id']}/transition", {"to": "backlog"})[0], 409)
        detail = self.request("GET", f"/api/tasks/{task['id']}")[1]
        self.assertEqual(detail["messages"][0]["title"], "bus diff")

        self.assertEqual(self.request("POST", "/api/council/members/gemini/promote", {})[1]["seat"], "council")
        self.assertEqual(self.request("POST", "/api/council/members/claude/demote", {})[1]["seat"], "bench")
        status, accepted = self.request("POST", "/api/council/messages", {"body": "status?"})
        self.assertEqual(status, 202)
        self.assertEqual(accepted["responders"], ["chatgpt"])  # lead only by default
        status, accepted = self.request("POST", "/api/council/messages", {"body": "debate it", "mode": "council"})
        self.assertEqual(accepted["responders"], ["chatgpt", "meta-muse", "gemini"])
        rows = self.request("GET", "/api/council/messages")[1]
        self.assertEqual([r["speaker_id"] for r in rows], ["operator", "chatgpt", "operator", "chatgpt", "meta-muse", "gemini"])
        self.assertEqual(self.request("POST", "/api/council/messages", {"body": "x", "mode": "loud"})[0], 400)
        self.assertEqual(self.request("GET", "/api/nope")[0], 404)

    def test_keep_alive_connection_survives_bodies_handlers_ignore(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"}
        if self.token:
            headers["X-CC-Token"] = self.token
        conn.request("POST", "/api/council/members/hermes/promote", body=b"{}", headers=headers)
        first = conn.getresponse()
        self.assertEqual((first.status, json.loads(first.read())["seat"]), (201, "council"))
        conn.request("GET", "/api/state", headers=headers)
        second = conn.getresponse()
        self.assertEqual(second.status, 200)
        seated = [m["id"] for m in json.loads(second.read())["council"] if m["seat"] == "council"]
        self.assertIn("hermes", seated)
        conn.close()

    def test_external_seat_can_post_only_when_seated(self):
        status, _ = self.request("POST", "/api/council/messages", {"speaker_kind": "model", "speaker_id": "hermes", "body": "hi"})
        self.assertEqual(status, 409)
        status, row = self.request("POST", "/api/council/messages", {"speaker_kind": "model", "speaker_id": "claude", "body": "hi"})
        self.assertEqual(status, 201)
        self.assertEqual(row["speaker_id"], "claude")

    def test_rejects_non_json_cross_origin_and_foreign_host(self):
        status, _ = self.request("POST", "/api/lanes/lane-build/messages", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _ = self.request("POST", "/api/lanes/lane-build/messages", {"title": "x"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.request("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.store.lane_messages("lane-build"), [])

    def test_stream_delivers_activity(self):
        seq = self.store.latest_seq()
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        token = f"&token={self.token}" if self.token else ""
        sock.sendall(f"GET /api/stream?after={seq}{token} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
        time.sleep(0.1)
        self.store.post_lane_message("lane-ops", author="cron", work_type="ops", title="rotated keys")
        buffer = b""
        deadline = time.time() + 5
        while b"lane.message" not in buffer and time.time() < deadline:
            buffer += sock.recv(4096)
        sock.close()
        self.assertIn(b"text/event-stream", buffer)
        self.assertIn(b"event: activity", buffer)
        self.assertIn(b'"subject": "lane-ops"', buffer)

    def test_client_reports_into_lane(self):
        client = CommandCenterClient(f"http://127.0.0.1:{self.port}", token=self.token, actor="hermes")
        out = client.report_output("lane-hermes", title="H-29 window closed", work_type="eval", model="hermes3:70b", latency_ms=900)
        self.assertEqual(out["author"], "hermes")
        task = client.create_task("lane-hermes", "ablation", state="queued")
        self.assertEqual(client.move_task(task["id"], "running")["state"], "running")
        with self.assertRaises(CommandCenterClientError) as ctx:
            client.move_task(task["id"], "done")
        self.assertEqual(ctx.exception.status, 400)


class TokenServerTests(ServerTests):
    token = "local-test-token-value"

    def test_token_required(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/state")
        res = conn.getresponse()
        res.read()
        conn.close()
        self.assertEqual(res.status, 401)
        status, _ = self.request("GET", "/api/state", headers={"X-CC-Token": "wrong"})
        self.assertEqual(status, 401)
        self.assertEqual(self.request("GET", "/")[0], 200)  # static shell carries no data

    def test_rejects_non_json_cross_origin_and_foreign_host(self):
        # With a token configured, a non-loopback Host (e.g. a tailnet name) is allowed.
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "hermes.tailnet.ts.net"})[0], 200)
        status, _ = self.request("POST", "/api/lanes/lane-build/messages", {"title": "x"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)


class BindPolicyTests(unittest.TestCase):
    def test_refuses_public_bind_without_token(self):
        tmp, store = make_store()
        try:
            app = CommandCenterApp(store, Council(store, {}))
            with self.assertRaises(ValueError):
                CommandCenterServer(("0.0.0.0", 0), app)
        finally:
            store.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
