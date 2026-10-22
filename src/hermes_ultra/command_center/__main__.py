"""CLI: python -m hermes_ultra.command_center serve|post|task|demo"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .council import Council
from .providers import default_providers
from .server import CommandCenterApp, CommandCenterServer
from .store import CommandCenterStore, StoreError, seed_defaults

DEFAULT_DB = os.environ.get("HERMES_CC_DB", ".hermes/command_center.db")


def seed_demo(store: CommandCenterStore) -> int:
    """Sample work items, every one flagged demo=1 so the UI labels it DEMO."""
    if any(task["demo"] for task in store.list_tasks()):
        return 0
    count = 0

    def task(lane, title, path, **kw):
        nonlocal count
        created = store.create_task(lane, title=title, actor="demo", demo=True, **kw)
        for step in path:
            to, extra = step if isinstance(step, tuple) else (step, {})
            store.transition_task(created["id"], to, actor="demo", **extra)
        count += 1
        return created

    t_bus = task("lane-build", "Lane bus backpressure handling", ["queued", ("running", {"progress": 0.6})], priority=1,
                 assignee="chatgpt", detail="Bounded queue per lane with WAL replay on restart.")
    task("lane-build", "Integration tests for lane switch", ["queued", "running",
         ("done", {"evidence": "pytest tests/test_lane_switch.py: 14 passed (demo record)"})], assignee="claude")
    task("lane-research", "Arena ranking algorithm v2", ["queued"], priority=2, assignee="claude")
    task("lane-content", "Launch announcement variants", [], priority=3, assignee="meta-muse")
    task("lane-ops", "Rotate provider keys for arena lane", ["queued", "running",
         ("blocked", {"blocker": "Waiting on operator approval for new billing project"})], priority=1)
    task("lane-ops", "Nightly cost audit export", ["queued", "running", ("failed", {"note": "S3 upload 403: bucket policy"})])
    task("lane-hermes", "Hermes self-repair prompt ablation", ["queued", ("running", {"progress": 0.35})], assignee="hermes")
    task("lane-arena", "Draft Hermes evaluation rubric", [], priority=4)

    post = lambda lane, **kw: store.post_lane_message(lane, demo=True, **kw)
    post("lane-build", author="chatgpt", model="gpt-5", work_type="code", task_id=t_bus["id"],
         title="feat(lanes): isolated message bus with backpressure", body="Diff: +247 -12 lines across lane_bus.py, queue.py.",
         tokens_in=2100, tokens_out=1020, cost_usd=0.062, latency_ms=6800)
    post("lane-build", author="claude", model="claude-opus-5-5", work_type="test",
         title="Integration tests for lane switching", body="14 tests; 2 flaky tests flagged for root-cause, not quarantined.",
         tokens_in=1800, tokens_out=900, cost_usd=0.025, latency_ms=4100)
    post("lane-build", author="hermes", model="hermes3:70b", work_type="plan",
         title="Proposed refactor of council election to a Raft-like protocol", body="ADR draft attached for review.")
    post("lane-research", author="claude", model="claude-opus-5-5", work_type="research",
         title="Lane isolation vs shared pool: context bleed comparison", body="Method and raw counts in the linked notebook.",
         tokens_in=5200, tokens_out=1400, cost_usd=0.049, latency_ms=9200)
    post("lane-content", author="meta-muse", model="llama-4", work_type="draft",
         title="Launch announcement — 3 variants", body="Dev, exec and thread variants.")
    post("lane-ops", author="cron", work_type="ops", title="Rate limits updated for arena lane", body="No downtime observed.")
    post("lane-arena", author="arena", work_type="eval", title="Arena match #441: Hermes vs Claude, creative coding",
         body="Judge: GPT-5. Hermes 8.7 vs Claude 8.2.")

    match = store.create_experiment("lane-arena", kind="arena_match", title="Match #441 creative coding",
                                    hypothesis="Hermes divergence beats grounded models on open-ended creative tasks.",
                                    status="concluded", metrics={"hermes": 8.7, "claude": 8.2}, actor="demo", demo=True)
    store.update_experiment(match["id"], result_summary="Hermes won creative (8.7 vs 8.2); lost factual (6.1 vs 8.9).")
    store.log_experiment(match["id"], "Judge GPT-5 scored 12 prompts", level="info")
    store.log_experiment(match["id"], "Hermes 8.7 / Claude 8.2", level="result")
    h29 = store.create_experiment("lane-hermes", kind="hypothesis", title="H-29 rotating council seat",
                                  hypothesis="A 2h rotating seat for Hermes during R&D sprints adds divergence without "
                                             "degrading factual accuracy.", status="running", actor="demo", demo=True)
    store.log_experiment(h29["id"], "Sprint window 1 opened", level="info")
    store.log_experiment(h29["id"], "Factual eval below threshold on 2/20 prompts", level="warn")
    store.create_experiment("lane-hermes", kind="ablation", title="Self-repair prompt ablation", status="planned",
                            hypothesis="Removing the critique step lowers repair rate by >10%.", actor="demo", demo=True)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hermes_ultra.command_center")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the command center")
    serve.add_argument("--host", default=os.environ.get("HERMES_CC_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("HERMES_CC_PORT", "4710")))
    serve.add_argument("--demo", action="store_true", help="add sample work items flagged DEMO")
    serve.add_argument("--verbose", action="store_true")

    post = sub.add_parser("post", help="post a lane output")
    post.add_argument("lane")
    post.add_argument("title")
    post.add_argument("--work-type", default="other")
    post.add_argument("--body", default="")
    post.add_argument("--author", default="cli")
    post.add_argument("--model")

    task = sub.add_parser("task", help="create a task or move one")
    task.add_argument("action", choices=["add", "move"])
    task.add_argument("target", help="lane id for add, task id for move")
    task.add_argument("value", help="title for add, target state for move")
    task.add_argument("--note", default="")
    task.add_argument("--evidence")
    task.add_argument("--blocker")
    task.add_argument("--priority", type=int, default=3)

    sub.add_parser("demo", help="add sample work items flagged DEMO")

    args = parser.parse_args(argv)
    store = CommandCenterStore(Path(args.db))
    seed_defaults(store)
    try:
        if args.command == "serve":
            if args.demo:
                seed_demo(store)
            app = CommandCenterApp(store, Council(store, default_providers()), token=os.environ.get("HERMES_CC_TOKEN"))
            server = CommandCenterServer((args.host, args.port), app, verbose=args.verbose)
            print(f"Lane Command Center on http://{args.host}:{server.server_address[1]}  db={args.db}"
                  f"{'  token required' if app.token else ''}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.shutdown()
            return 0
        if args.command == "post":
            message = store.post_lane_message(args.lane, author=args.author, title=args.title, work_type=args.work_type,
                                              body=args.body, model=args.model)
            print(f"posted message {message['id']} to {message['lane_id']}")
        elif args.command == "task" and args.action == "add":
            created = store.create_task(args.target, title=args.value, priority=args.priority, actor="cli")
            print(created["id"])
        elif args.command == "task":
            moved = store.transition_task(args.target, args.value, actor="cli", note=args.note, evidence=args.evidence,
                                          blocker=args.blocker)
            print(f"{moved['id']} -> {moved['state']}")
        elif args.command == "demo":
            print(f"added {seed_demo(store)} demo tasks")
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
