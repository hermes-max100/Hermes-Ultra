"""Orchestrator council: one shared thread, members answer in rank order.

Members reply sequentially so each one sees what the members before it said in
the same round. ``@member`` mentions narrow a round to those members; ``#lane``
mentions attach that lane's recent outputs as context.
"""
from __future__ import annotations

import re
import threading
import uuid
from typing import Any, Callable, Mapping

from .providers import estimate_cost
from .store import CommandCenterStore, StoreError

MENTION_RE = re.compile(r"(?<![\w#@])@([a-z0-9][a-z0-9_.-]*)", re.IGNORECASE)
LANE_RE = re.compile(r"(?<![\w#@])#(lane-[a-z0-9_.-]+)", re.IGNORECASE)
TRANSCRIPT_LIMIT = 40
LANE_CONTEXT_LIMIT = 6

SYSTEM_PROMPT = """You are {name}, a seated member of an orchestrator council in an AI operations command center.
The operator runs several work lanes and talks to the council to decide what happens next.
Other council members: {others}.

Read the transcript, then give your own view in a few short paragraphs or a tight list.
Build on or challenge earlier replies by name when you disagree, and give the evidence or mechanism behind the disagreement.
State uncertainty plainly and say what would settle it. Do not claim work is done unless the transcript shows evidence.
The operator may be listening through text-to-speech, so prefer plain sentences over tables and code unless asked."""


def parse_mentions(body: str, member_ids: set[str]) -> tuple[list[str], list[str]]:
    members: list[str] = []
    lanes: list[str] = []
    for match in MENTION_RE.findall(body or ""):
        candidate = match.lower().rstrip(".")
        if candidate in member_ids and candidate not in members:
            members.append(candidate)
        elif candidate.startswith("lane-") and candidate not in lanes:
            lanes.append(candidate)
    for match in LANE_RE.findall(body or ""):
        candidate = match.lower().rstrip(".")
        if candidate not in lanes:
            lanes.append(candidate)
    return members, lanes


class Council:
    def __init__(
        self,
        store: CommandCenterStore,
        providers: Mapping[str, Any],
        *,
        spawn: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.store = store
        self.providers = dict(providers)
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._lock = threading.Lock()
        self._active: set[str] = set()

    def roster(self) -> list[dict[str, Any]]:
        members = []
        for member in self.store.list_members():
            availability = self.availability(member)
            members.append({**member, "available": availability[0], "availability_reason": availability[1]})
        return members

    def availability(self, member: Mapping[str, Any]) -> tuple[bool, str]:
        if not member.get("enabled"):
            return False, "disabled"
        provider = self.providers.get(member["provider"])
        if provider is None:
            return False, f"no adapter for provider {member['provider']}"
        result = provider.availability(member)
        return result.available, result.reason

    def active_rounds(self) -> list[str]:
        with self._lock:
            return sorted(self._active)

    def submit(self, body: str, *, speaker_id: str = "operator", run_async: bool = True) -> dict[str, Any]:
        if not (body or "").strip():
            raise StoreError("message body is required")
        round_id = "r-" + uuid.uuid4().hex[:10]
        seated = self.store.list_members(seat="council")
        mentioned, lanes = parse_mentions(body, {m["id"] for m in self.store.list_members()})
        if mentioned:
            # Mentions can address any roster member, including bench seats invited ad hoc.
            by_id = {m["id"]: m for m in self.store.list_members()}
            responders = [by_id[mid] for mid in mentioned]
        else:
            responders = seated
        operator_message = self.store.post_council_message(
            round_id=round_id, speaker_kind="operator", speaker_id=speaker_id, body=body
        )
        with self._lock:
            self._active.add(round_id)

        def run() -> None:
            try:
                self._run_round(round_id, responders, lanes)
            finally:
                with self._lock:
                    self._active.discard(round_id)
                # Tell live clients the round is over so "deliberating" clears.
                self.store.record_activity("council.round_finished", round_id, actor="council")

        if run_async:
            self._spawn(run)
        else:
            run()
        return {
            "round_id": round_id,
            "message": operator_message,
            "responders": [m["id"] for m in responders],
            "lanes": lanes,
        }

    def _lane_context(self, lanes: list[str]) -> str:
        sections = []
        for lane_id in lanes:
            try:
                messages = self.store.lane_messages(lane_id, limit=LANE_CONTEXT_LIMIT)
            except StoreError:
                sections.append(f"#{lane_id}: no such lane.")
                continue
            if not messages:
                sections.append(f"#{lane_id}: no outputs recorded yet.")
                continue
            lines = [f"#{lane_id} latest outputs:"]
            for m in messages:
                body = (m["body"] or "").strip().replace("\n", " ")
                lines.append(
                    f"- [{m['work_type'].upper()}] {m['author']}{' / ' + m['model'] if m['model'] else ''}: "
                    f"{m['title']}{' — ' + body[:400] if body else ''}"
                )
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    def _transcript(self) -> str:
        names = {m["id"]: m["display_name"] for m in self.store.list_members()}
        lines = []
        for message in self.store.council_messages(limit=TRANSCRIPT_LIMIT):
            if message["speaker_kind"] == "operator":
                speaker = "Operator"
            elif message["speaker_kind"] == "system":
                speaker = "System"
            else:
                speaker = names.get(message["speaker_id"], message["speaker_id"])
            if message["status"] != "ok" and message["speaker_kind"] != "operator":
                continue
            lines.append(f"{speaker}: {message['body']}")
        return "\n\n".join(lines)

    def _run_round(self, round_id: str, responders: list[dict[str, Any]], lanes: list[str]) -> None:
        if not responders:
            self.store.post_council_message(
                round_id=round_id, speaker_kind="system", speaker_id="council", status="offline",
                body="No council seats are filled. Promote a model from the bench.",
            )
            return
        lane_context = self._lane_context(lanes)
        all_names = [m["display_name"] for m in responders]
        for member in responders:
            available, reason = self.availability(member)
            if not available:
                self.store.post_council_message(
                    round_id=round_id, speaker_kind="system", speaker_id=member["id"], status="offline",
                    model=member["model"], body=f"{member['display_name']} is offline: {reason}.",
                )
                continue
            others = ", ".join(n for n in all_names if n != member["display_name"]) or "none this round"
            system = SYSTEM_PROMPT.format(name=member["display_name"], others=others)
            prompt = "Council transcript so far:\n\n" + self._transcript()
            if lane_context:
                prompt += "\n\nLane context referenced by the operator:\n\n" + lane_context
            prompt += f"\n\nIt is your turn, {member['display_name']}."
            provider = self.providers[member["provider"]]
            try:
                reply = provider.complete(member, system, prompt)
            except Exception as exc:  # adapter bug must not kill the round for other members
                self.store.post_council_message(
                    round_id=round_id, speaker_kind="system", speaker_id=member["id"], status="error",
                    model=member["model"], body=f"{member['display_name']} adapter failed: {type(exc).__name__}: {exc}",
                )
                continue
            if reply.status == "ok":
                self.store.post_council_message(
                    round_id=round_id, speaker_kind="model", speaker_id=member["id"], status="ok", body=reply.text,
                    model=reply.model, tokens_in=reply.tokens_in, tokens_out=reply.tokens_out,
                    cost_usd=estimate_cost(member, reply.tokens_in, reply.tokens_out), latency_ms=reply.latency_ms,
                )
            else:
                self.store.post_council_message(
                    round_id=round_id, speaker_kind="system", speaker_id=member["id"], status=reply.status,
                    model=reply.model, body=f"{member['display_name']}: {reply.text}",
                    tokens_in=reply.tokens_in, tokens_out=reply.tokens_out,
                    cost_usd=estimate_cost(member, reply.tokens_in, reply.tokens_out), latency_ms=reply.latency_ms,
                )
