"""Durable SQLite state for the Lane Command Center.

Every lane message carries a mandatory ``lane_id`` so lane channels never share a
feed. Task state changes, council promotions and experiment updates append to an
``activity`` log that doubles as the live change feed for the UI.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

OWNERSHIP = ("owned", "observed")
LANE_KINDS = ("production", "rnd")
LANE_STATUSES = ("active", "queued", "idle", "blocked", "offline")
WORK_TYPES = ("code", "research", "draft", "test", "plan", "ops", "eval", "note", "other")
PROVIDERS = ("anthropic", "openai", "openai_compatible", "manual")
SEATS = ("council", "bench")
TASK_STATES = ("backlog", "queued", "running", "blocked", "done", "failed")
EXPERIMENT_KINDS = ("arena_match", "hypothesis", "benchmark", "ablation")
EXPERIMENT_STATUSES = ("planned", "running", "concluded", "abandoned")
COUNCIL_STATUSES = ("ok", "error", "offline", "refused")

# Done is terminal except for an explicit reopen to backlog.
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "backlog": frozenset({"queued", "running", "blocked", "failed"}),
    "queued": frozenset({"running", "backlog", "blocked", "failed"}),
    "running": frozenset({"done", "failed", "blocked", "queued"}),
    "blocked": frozenset({"queued", "running", "backlog", "failed"}),
    "done": frozenset({"backlog"}),
    "failed": frozenset({"queued", "backlog"}),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS lanes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ownership TEXT NOT NULL CHECK (ownership IN ('owned','observed')),
  kind TEXT NOT NULL CHECK (kind IN ('production','rnd')),
  status TEXT NOT NULL CHECK (status IN ('active','queued','idle','blocked','offline')),
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  lane_id TEXT NOT NULL REFERENCES lanes(id),
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL CHECK (state IN ('backlog','queued','running','blocked','done','failed')),
  priority INTEGER NOT NULL DEFAULT 3,
  assignee TEXT,
  blocker TEXT,
  evidence TEXT,
  progress REAL,
  demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS tasks_lane_state ON tasks(lane_id, state);
CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  from_state TEXT,
  to_state TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lane_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lane_id TEXT NOT NULL REFERENCES lanes(id),
  author TEXT NOT NULL,
  model TEXT,
  work_type TEXT NOT NULL CHECK (work_type IN ('code','research','draft','test','plan','ops','eval','note','other')),
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  tokens_in INTEGER,
  tokens_out INTEGER,
  cost_usd REAL,
  latency_ms INTEGER,
  task_id TEXT REFERENCES tasks(id),
  demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lane_messages_lane ON lane_messages(lane_id, id);
CREATE TABLE IF NOT EXISTS council_members (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('anthropic','openai','openai_compatible','manual')),
  model TEXT NOT NULL,
  base_url TEXT,
  credential_env TEXT,
  seat TEXT NOT NULL CHECK (seat IN ('council','bench')),
  rank INTEGER NOT NULL,
  home_lane_id TEXT REFERENCES lanes(id),
  enabled INTEGER NOT NULL DEFAULT 1,
  effort TEXT,
  price_in_per_m REAL,
  price_out_per_m REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS council_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id TEXT NOT NULL,
  speaker_kind TEXT NOT NULL CHECK (speaker_kind IN ('operator','model','system')),
  speaker_id TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','error','offline','refused')),
  model TEXT,
  tokens_in INTEGER,
  tokens_out INTEGER,
  cost_usd REAL,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY,
  lane_id TEXT NOT NULL REFERENCES lanes(id),
  kind TEXT NOT NULL CHECK (kind IN ('arena_match','hypothesis','benchmark','ablation')),
  title TEXT NOT NULL,
  hypothesis TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('planned','running','concluded','abandoned')),
  result_summary TEXT NOT NULL DEFAULT '',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  level TEXT NOT NULL CHECK (level IN ('info','warn','error','result')),
  message TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  subject TEXT NOT NULL,
  actor TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
"""


class StoreError(ValueError):
    """Invalid request against the command center state."""


class NotFound(StoreError):
    pass


class Conflict(StoreError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _check_id(value: Any, field: str = "id") -> str:
    text = str(value or "").strip().lower()
    if not ID_RE.match(text):
        raise StoreError(f"invalid {field}: {value!r}")
    return text


def _check_choice(value: Any, choices: Iterable[str], field: str) -> str:
    text = str(value or "").strip().lower()
    if text not in choices:
        raise StoreError(f"invalid {field}: {value!r}; expected one of {', '.join(choices)}")
    return text


def _text(value: Any, field: str, *, required: bool = True, limit: int = 200_000) -> str:
    text = "" if value is None else str(value)
    if required and not text.strip():
        raise StoreError(f"{field} is required")
    if len(text) > limit:
        raise StoreError(f"{field} exceeds {limit} characters")
    return text


def _opt_int(value: Any, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise StoreError(f"{field} must be an integer") from exc
    if number < 0:
        raise StoreError(f"{field} must be non-negative")
    return number


def _opt_float(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise StoreError(f"{field} must be a number") from exc
    if number < 0:
        raise StoreError(f"{field} must be non-negative")
    return number


def _lane_health(lane: Mapping[str, Any]) -> str:
    """Status derived from the lane's work; an operator-set offline or blocked status wins."""
    if lane["status"] in ("offline", "blocked"):
        return lane["status"]
    tasks = lane["tasks"]
    if tasks["running"]:
        return "active"
    if tasks["blocked"]:
        return "blocked"
    if tasks["queued"]:
        return "queued"
    return lane["status"]


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class CommandCenterStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ helpers
    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def _one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            return _row(self._conn.execute(sql, tuple(params)).fetchone())

    def _tx(self):
        store = self

        class _Tx:
            def __enter__(self_inner):
                store._lock.acquire()
                store._conn.execute("BEGIN IMMEDIATE")
                return store._conn

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    store._conn.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store._lock.release()
                return False

        return _Tx()

    @staticmethod
    def _activity(conn: sqlite3.Connection, topic: str, subject: str, actor: str, detail: Mapping[str, Any]) -> None:
        conn.execute(
            "INSERT INTO activity(topic, subject, actor, detail_json, created_at) VALUES (?,?,?,?,?)",
            (topic, subject, actor, json.dumps(dict(detail), sort_keys=True), utc_now()),
        )

    # -------------------------------------------------------------------- lanes
    def create_lane(
        self,
        lane_id: str,
        *,
        name: str | None = None,
        ownership: str = "owned",
        kind: str = "production",
        status: str = "idle",
        description: str = "",
        actor: str = "operator",
    ) -> dict[str, Any]:
        lane_id = _check_id(lane_id, "lane id")
        values = (
            lane_id,
            _text(name or lane_id, "name", limit=120),
            _check_choice(ownership, OWNERSHIP, "ownership"),
            _check_choice(kind, LANE_KINDS, "kind"),
            _check_choice(status, LANE_STATUSES, "status"),
            _text(description, "description", required=False, limit=2000),
        )
        now = utc_now()
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM lanes WHERE id=?", (lane_id,)).fetchone():
                raise Conflict(f"lane {lane_id} already exists")
            conn.execute(
                "INSERT INTO lanes(id,name,ownership,kind,status,description,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                values + (now, now),
            )
            self._activity(conn, "lane.created", lane_id, actor, {"ownership": values[2], "kind": values[3]})
        return self.get_lane(lane_id)

    def get_lane(self, lane_id: str) -> dict[str, Any]:
        lane = self._one("SELECT * FROM lanes WHERE id=?", (str(lane_id).lower(),))
        if lane is None:
            raise NotFound(f"lane {lane_id} not found")
        return lane

    def update_lane(self, lane_id: str, changes: Mapping[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        lane = self.get_lane(lane_id)
        allowed = {
            "name": lambda v: _text(v, "name", limit=120),
            "ownership": lambda v: _check_choice(v, OWNERSHIP, "ownership"),
            "kind": lambda v: _check_choice(v, LANE_KINDS, "kind"),
            "status": lambda v: _check_choice(v, LANE_STATUSES, "status"),
            "description": lambda v: _text(v, "description", required=False, limit=2000),
        }
        updates = {}
        for key, value in changes.items():
            if key not in allowed:
                raise StoreError(f"lane field {key!r} is not editable")
            updates[key] = allowed[key](value)
        if not updates:
            return lane
        with self._tx() as conn:
            assignments = ", ".join(f"{key}=?" for key in updates)
            conn.execute(
                f"UPDATE lanes SET {assignments}, updated_at=? WHERE id=?",
                (*updates.values(), utc_now(), lane["id"]),
            )
            self._activity(conn, "lane.updated", lane["id"], actor, updates)
        return self.get_lane(lane["id"])

    def list_lanes(self) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        lanes = self._query("SELECT * FROM lanes ORDER BY kind, ownership, id")
        counts = {
            (r["lane_id"], r["state"]): r["n"]
            for r in self._query("SELECT lane_id, state, COUNT(*) AS n FROM tasks GROUP BY lane_id, state")
        }
        stats = {
            r["lane_id"]: r
            for r in self._query(
                """SELECT lane_id, COUNT(*) AS messages,
                          SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS outputs_24h,
                          SUM(CASE WHEN created_at >= ? THEN COALESCE(tokens_in,0)+COALESCE(tokens_out,0) ELSE 0 END) AS tokens_24h,
                          SUM(CASE WHEN created_at >= ? THEN cost_usd END) AS cost_24h,
                          AVG(latency_ms) AS avg_latency_ms,
                          MAX(created_at) AS last_output_at
                   FROM lane_messages GROUP BY lane_id""",
                (since, since, since),
            )
        }
        mix = {}
        for r in self._query("SELECT lane_id, work_type, COUNT(*) AS n FROM lane_messages GROUP BY lane_id, work_type"):
            mix.setdefault(r["lane_id"], {})[r["work_type"]] = r["n"]
        for lane in lanes:
            lane["tasks"] = {state: counts.get((lane["id"], state), 0) for state in TASK_STATES}
            lane_stats = stats.get(lane["id"], {})
            lane["messages"] = lane_stats.get("messages") or 0
            lane["outputs_24h"] = lane_stats.get("outputs_24h") or 0
            lane["tokens_24h"] = lane_stats.get("tokens_24h") or 0
            lane["cost_24h"] = lane_stats.get("cost_24h")
            lane["avg_latency_ms"] = lane_stats.get("avg_latency_ms")
            lane["last_output_at"] = lane_stats.get("last_output_at")
            lane["work_mix"] = mix.get(lane["id"], {})
            lane["health"] = _lane_health(lane)
        return lanes

    # ----------------------------------------------------------- lane messages
    def post_lane_message(
        self,
        lane_id: str,
        *,
        author: str,
        title: str,
        work_type: str = "other",
        body: str = "",
        model: str | None = None,
        tokens_in: Any = None,
        tokens_out: Any = None,
        cost_usd: Any = None,
        latency_ms: Any = None,
        task_id: str | None = None,
        demo: bool = False,
    ) -> dict[str, Any]:
        lane = self.get_lane(lane_id)
        if task_id:
            task = self.get_task(task_id)
            if task["lane_id"] != lane["id"]:
                raise StoreError(f"task {task_id} belongs to lane {task['lane_id']}, not {lane['id']}")
        values = (
            lane["id"],
            _text(author, "author", limit=120),
            _text(model, "model", required=False, limit=120) or None,
            _check_choice(work_type, WORK_TYPES, "work_type"),
            _text(title, "title", limit=300),
            _text(body, "body", required=False),
            _opt_int(tokens_in, "tokens_in"),
            _opt_int(tokens_out, "tokens_out"),
            _opt_float(cost_usd, "cost_usd"),
            _opt_int(latency_ms, "latency_ms"),
            task_id or None,
            1 if demo else 0,
            utc_now(),
        )
        with self._tx() as conn:
            cursor = conn.execute(
                """INSERT INTO lane_messages(lane_id,author,model,work_type,title,body,tokens_in,tokens_out,
                   cost_usd,latency_ms,task_id,demo,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            message_id = cursor.lastrowid
            self._activity(conn, "lane.message", lane["id"], values[1], {"message_id": message_id, "work_type": values[3]})
        return self._one("SELECT * FROM lane_messages WHERE id=?", (message_id,))

    def lane_messages(
        self, lane_id: str, *, limit: int = 100, before_id: int | None = None, work_type: str | None = None
    ) -> list[dict[str, Any]]:
        lane = self.get_lane(lane_id)
        sql = "SELECT * FROM lane_messages WHERE lane_id=?"
        params: list[Any] = [lane["id"]]
        if before_id:
            sql += " AND id < ?"
            params.append(int(before_id))
        if work_type:
            sql += " AND work_type = ?"
            params.append(_check_choice(work_type, WORK_TYPES, "work_type"))
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return list(reversed(self._query(sql, params)))

    def get_lane_message(self, message_id: int) -> dict[str, Any]:
        message = self._one("SELECT * FROM lane_messages WHERE id=?", (int(message_id),))
        if message is None:
            raise NotFound(f"message {message_id} not found")
        return message

    # -------------------------------------------------------------------- tasks
    def create_task(
        self,
        lane_id: str,
        *,
        title: str,
        detail: str = "",
        state: str = "backlog",
        priority: Any = 3,
        assignee: str | None = None,
        task_id: str | None = None,
        actor: str = "operator",
        demo: bool = False,
    ) -> dict[str, Any]:
        lane = self.get_lane(lane_id)
        state = _check_choice(state, ("backlog", "queued"), "initial state")
        task_id = _check_id(task_id, "task id") if task_id else "t-" + uuid.uuid4().hex[:10]
        prio = _opt_int(priority, "priority")
        if prio is None or not 1 <= prio <= 5:
            raise StoreError("priority must be 1 (highest) to 5")
        now = utc_now()
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                raise Conflict(f"task {task_id} already exists")
            conn.execute(
                """INSERT INTO tasks(id,lane_id,title,detail,state,priority,assignee,demo,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    lane["id"],
                    _text(title, "title", limit=300),
                    _text(detail, "detail", required=False, limit=20_000),
                    state,
                    prio,
                    _text(assignee, "assignee", required=False, limit=120) or None,
                    1 if demo else 0,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO task_events(task_id,from_state,to_state,note,actor,created_at) VALUES (?,?,?,?,?,?)",
                (task_id, None, state, "created", actor, now),
            )
            self._activity(conn, "task.created", task_id, actor, {"lane_id": lane["id"], "state": state})
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        task = self._one("SELECT * FROM tasks WHERE id=?", (str(task_id),))
        if task is None:
            raise NotFound(f"task {task_id} not found")
        return task

    def task_detail(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        task["events"] = self._query("SELECT * FROM task_events WHERE task_id=? ORDER BY id", (task["id"],))
        task["messages"] = self._query("SELECT * FROM lane_messages WHERE task_id=? ORDER BY id", (task["id"],))
        return task

    def list_tasks(self, *, lane_id: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list[Any] = []
        if lane_id:
            sql += " AND lane_id=?"
            params.append(self.get_lane(lane_id)["id"])
        if state:
            sql += " AND state=?"
            params.append(_check_choice(state, TASK_STATES, "state"))
        sql += " ORDER BY priority, updated_at DESC"
        return self._query(sql, params)

    def transition_task(
        self,
        task_id: str,
        to_state: str,
        *,
        actor: str = "operator",
        note: str = "",
        blocker: str | None = None,
        evidence: str | None = None,
        progress: Any = None,
    ) -> dict[str, Any]:
        to_state = _check_choice(to_state, TASK_STATES, "state")
        task = self.get_task(task_id)
        from_state = task["state"]
        if to_state not in TASK_TRANSITIONS[from_state]:
            raise Conflict(f"task {task_id} cannot move {from_state} -> {to_state}")
        if to_state == "blocked" and not (blocker or "").strip():
            raise StoreError("blocked requires a blocker description")
        if to_state == "done" and not (evidence or "").strip():
            raise StoreError("done requires evidence (test output, artifact path, URL or commit)")
        if to_state == "failed" and not (note or "").strip():
            raise StoreError("failed requires a note describing the failure")
        pct = _opt_float(progress, "progress")
        if pct is not None and pct > 1:
            raise StoreError("progress must be between 0 and 1")
        now = utc_now()
        fields: dict[str, Any] = {"state": to_state, "updated_at": now}
        fields["blocker"] = blocker.strip() if to_state == "blocked" else None
        if to_state == "running" and not task["started_at"]:
            fields["started_at"] = now
        if to_state in ("done", "failed"):
            fields["finished_at"] = now
        if to_state == "done":
            fields["evidence"] = _text(evidence, "evidence", limit=4000)
            fields["progress"] = 1.0
        elif to_state == "backlog":
            fields["finished_at"] = None
        if pct is not None and to_state != "done":
            fields["progress"] = pct
        with self._tx() as conn:
            assignments = ", ".join(f"{key}=?" for key in fields)
            conn.execute(f"UPDATE tasks SET {assignments} WHERE id=?", (*fields.values(), task["id"]))
            conn.execute(
                "INSERT INTO task_events(task_id,from_state,to_state,note,actor,created_at) VALUES (?,?,?,?,?,?)",
                (task["id"], from_state, to_state, _text(note or blocker or evidence or "", "note", required=False, limit=4000), actor, now),
            )
            self._activity(conn, "task.transition", task["id"], actor, {"from": from_state, "to": to_state, "lane_id": task["lane_id"]})
        return self.get_task(task["id"])

    def update_task_progress(self, task_id: str, progress: Any, *, actor: str = "operator") -> dict[str, Any]:
        task = self.get_task(task_id)
        pct = _opt_float(progress, "progress")
        if pct is None or pct > 1:
            raise StoreError("progress must be between 0 and 1")
        with self._tx() as conn:
            conn.execute("UPDATE tasks SET progress=?, updated_at=? WHERE id=?", (pct, utc_now(), task["id"]))
            self._activity(conn, "task.progress", task["id"], actor, {"progress": pct, "lane_id": task["lane_id"]})
        return self.get_task(task["id"])

    # ------------------------------------------------------------------ council
    def add_member(
        self,
        member_id: str,
        *,
        display_name: str,
        provider: str,
        model: str,
        base_url: str | None = None,
        credential_env: str | None = None,
        seat: str = "bench",
        home_lane_id: str | None = None,
        effort: str | None = None,
        price_in_per_m: Any = None,
        price_out_per_m: Any = None,
        actor: str = "operator",
    ) -> dict[str, Any]:
        member_id = _check_id(member_id, "member id")
        seat = _check_choice(seat, SEATS, "seat")
        if home_lane_id:
            home_lane_id = self.get_lane(home_lane_id)["id"]
        env = _text(credential_env, "credential_env", required=False, limit=80).strip() or None
        if env and not re.match(r"^[A-Z][A-Z0-9_]{1,79}$", env):
            raise StoreError("credential_env must name an environment variable, not hold a credential")
        now = utc_now()
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM council_members WHERE id=?", (member_id,)).fetchone():
                raise Conflict(f"member {member_id} already exists")
            rank = conn.execute("SELECT COALESCE(MAX(rank),0)+1 FROM council_members WHERE seat=?", (seat,)).fetchone()[0]
            conn.execute(
                """INSERT INTO council_members(id,display_name,provider,model,base_url,credential_env,seat,rank,
                   home_lane_id,enabled,effort,price_in_per_m,price_out_per_m,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
                (
                    member_id,
                    _text(display_name, "display_name", limit=80),
                    _check_choice(provider, PROVIDERS, "provider"),
                    _text(model, "model", limit=160),
                    _text(base_url, "base_url", required=False, limit=400) or None,
                    env,
                    seat,
                    rank,
                    home_lane_id,
                    _text(effort, "effort", required=False, limit=16) or None,
                    _opt_float(price_in_per_m, "price_in_per_m"),
                    _opt_float(price_out_per_m, "price_out_per_m"),
                    now,
                    now,
                ),
            )
            self._activity(conn, "council.member_added", member_id, actor, {"seat": seat})
        return self.get_member(member_id)

    def get_member(self, member_id: str) -> dict[str, Any]:
        member = self._one("SELECT * FROM council_members WHERE id=?", (str(member_id).lower(),))
        if member is None:
            raise NotFound(f"member {member_id} not found")
        return member

    def list_members(self, *, seat: str | None = None) -> list[dict[str, Any]]:
        if seat:
            return self._query(
                "SELECT * FROM council_members WHERE seat=? ORDER BY rank, id", (_check_choice(seat, SEATS, "seat"),)
            )
        return self._query("SELECT * FROM council_members ORDER BY CASE seat WHEN 'council' THEN 0 ELSE 1 END, rank, id")

    def update_member(self, member_id: str, changes: Mapping[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        member = self.get_member(member_id)

        def env_field(value: Any) -> str | None:
            text = _text(value, "credential_env", required=False, limit=80).strip()
            if text and not re.match(r"^[A-Z][A-Z0-9_]{1,79}$", text):
                raise StoreError("credential_env must name an environment variable, not hold a credential")
            return text or None

        allowed = {
            "display_name": lambda v: _text(v, "display_name", limit=80),
            "provider": lambda v: _check_choice(v, PROVIDERS, "provider"),
            "model": lambda v: _text(v, "model", limit=160),
            "base_url": lambda v: _text(v, "base_url", required=False, limit=400) or None,
            "credential_env": env_field,
            "home_lane_id": lambda v: self.get_lane(v)["id"] if v else None,
            "enabled": lambda v: 1 if v in (True, 1, "1", "true", "on") else 0,
            "effort": lambda v: _text(v, "effort", required=False, limit=16) or None,
            "price_in_per_m": lambda v: _opt_float(v, "price_in_per_m"),
            "price_out_per_m": lambda v: _opt_float(v, "price_out_per_m"),
        }
        updates = {}
        for key, value in changes.items():
            if key not in allowed:
                raise StoreError(f"member field {key!r} is not editable here")
            updates[key] = allowed[key](value)
        if not updates:
            return member
        with self._tx() as conn:
            assignments = ", ".join(f"{key}=?" for key in updates)
            conn.execute(
                f"UPDATE council_members SET {assignments}, updated_at=? WHERE id=?",
                (*updates.values(), utc_now(), member["id"]),
            )
            self._activity(conn, "council.member_updated", member["id"], actor, {k: v for k, v in updates.items()})
        return self.get_member(member["id"])

    def promote(self, member_id: str, *, actor: str = "operator") -> dict[str, Any]:
        member = self.get_member(member_id)
        if member["seat"] == "council":
            return member
        with self._tx() as conn:
            rank = conn.execute("SELECT COALESCE(MAX(rank),0)+1 FROM council_members WHERE seat='council'").fetchone()[0]
            conn.execute(
                "UPDATE council_members SET seat='council', rank=?, updated_at=? WHERE id=?", (rank, utc_now(), member["id"])
            )
            self._renumber(conn, "bench")
            self._activity(conn, "council.promoted", member["id"], actor, {"rank": rank})
        return self.get_member(member["id"])

    def demote(self, member_id: str, *, actor: str = "operator") -> dict[str, Any]:
        member = self.get_member(member_id)
        if member["seat"] == "bench":
            return member
        with self._tx() as conn:
            seated = conn.execute("SELECT COUNT(*) FROM council_members WHERE seat='council'").fetchone()[0]
            if seated <= 1:
                raise Conflict("the council must keep at least one orchestrator; promote a replacement first")
            rank = conn.execute("SELECT COALESCE(MAX(rank),0)+1 FROM council_members WHERE seat='bench'").fetchone()[0]
            conn.execute(
                "UPDATE council_members SET seat='bench', rank=?, updated_at=? WHERE id=?", (rank, utc_now(), member["id"])
            )
            self._renumber(conn, "council")
            self._activity(conn, "council.demoted", member["id"], actor, {"home_lane_id": member["home_lane_id"]})
        return self.get_member(member["id"])

    def reorder(self, seat: str, order: Iterable[str], *, actor: str = "operator") -> list[dict[str, Any]]:
        seat = _check_choice(seat, SEATS, "seat")
        order = [str(item).lower() for item in order]
        with self._tx() as conn:
            current = [r[0] for r in conn.execute("SELECT id FROM council_members WHERE seat=? ORDER BY rank, id", (seat,))]
            if sorted(current) != sorted(order) or len(set(order)) != len(order):
                raise Conflict(f"reorder must list every {seat} member exactly once: {', '.join(current)}")
            for index, member_id in enumerate(order, start=1):
                conn.execute("UPDATE council_members SET rank=?, updated_at=? WHERE id=?", (index, utc_now(), member_id))
            self._activity(conn, "council.reordered", seat, actor, {"order": order})
        return self.list_members(seat=seat)

    @staticmethod
    def _renumber(conn: sqlite3.Connection, seat: str) -> None:
        ids = [r[0] for r in conn.execute("SELECT id FROM council_members WHERE seat=? ORDER BY rank, id", (seat,))]
        for index, member_id in enumerate(ids, start=1):
            conn.execute("UPDATE council_members SET rank=? WHERE id=?", (index, member_id))

    def post_council_message(
        self,
        *,
        round_id: str,
        speaker_kind: str,
        speaker_id: str,
        body: str,
        status: str = "ok",
        model: str | None = None,
        tokens_in: Any = None,
        tokens_out: Any = None,
        cost_usd: Any = None,
        latency_ms: Any = None,
    ) -> dict[str, Any]:
        values = (
            _text(round_id, "round_id", limit=64),
            _check_choice(speaker_kind, ("operator", "model", "system"), "speaker_kind"),
            _text(speaker_id, "speaker_id", limit=80),
            _text(body, "body", limit=100_000),
            _check_choice(status, COUNCIL_STATUSES, "status"),
            model,
            _opt_int(tokens_in, "tokens_in"),
            _opt_int(tokens_out, "tokens_out"),
            _opt_float(cost_usd, "cost_usd"),
            _opt_int(latency_ms, "latency_ms"),
            utc_now(),
        )
        with self._tx() as conn:
            cursor = conn.execute(
                """INSERT INTO council_messages(round_id,speaker_kind,speaker_id,body,status,model,tokens_in,
                   tokens_out,cost_usd,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            message_id = cursor.lastrowid
            self._activity(
                conn, "council.message", values[0], values[2], {"message_id": message_id, "status": values[4]}
            )
        return self._one("SELECT * FROM council_messages WHERE id=?", (message_id,))

    def council_messages(self, *, limit: int = 200, after_id: int | None = None) -> list[dict[str, Any]]:
        if after_id:
            return self._query(
                "SELECT * FROM council_messages WHERE id > ? ORDER BY id LIMIT ?", (int(after_id), max(1, min(int(limit), 1000)))
            )
        rows = self._query("SELECT * FROM council_messages ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 1000)),))
        return list(reversed(rows))

    # -------------------------------------------------------------- experiments
    def create_experiment(
        self,
        lane_id: str,
        *,
        title: str,
        kind: str = "hypothesis",
        hypothesis: str = "",
        status: str = "planned",
        metrics: Mapping[str, Any] | None = None,
        experiment_id: str | None = None,
        actor: str = "operator",
        demo: bool = False,
    ) -> dict[str, Any]:
        lane = self.get_lane(lane_id)
        experiment_id = _check_id(experiment_id, "experiment id") if experiment_id else "x-" + uuid.uuid4().hex[:10]
        now = utc_now()
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM experiments WHERE id=?", (experiment_id,)).fetchone():
                raise Conflict(f"experiment {experiment_id} already exists")
            conn.execute(
                """INSERT INTO experiments(id,lane_id,kind,title,hypothesis,status,metrics_json,demo,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    experiment_id,
                    lane["id"],
                    _check_choice(kind, EXPERIMENT_KINDS, "kind"),
                    _text(title, "title", limit=300),
                    _text(hypothesis, "hypothesis", required=False, limit=8000),
                    _check_choice(status, EXPERIMENT_STATUSES, "status"),
                    json.dumps(dict(metrics or {}), sort_keys=True),
                    1 if demo else 0,
                    now,
                    now,
                ),
            )
            self._activity(conn, "experiment.created", experiment_id, actor, {"lane_id": lane["id"]})
        return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment = self._one("SELECT * FROM experiments WHERE id=?", (str(experiment_id),))
        if experiment is None:
            raise NotFound(f"experiment {experiment_id} not found")
        experiment["metrics"] = json.loads(experiment.pop("metrics_json") or "{}")
        return experiment

    def experiment_detail(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        experiment["events"] = self._query(
            "SELECT * FROM experiment_events WHERE experiment_id=? ORDER BY id", (experiment["id"],)
        )
        return experiment

    def list_experiments(self, *, lane_id: str | None = None) -> list[dict[str, Any]]:
        if lane_id:
            rows = self._query(
                "SELECT * FROM experiments WHERE lane_id=? ORDER BY updated_at DESC", (self.get_lane(lane_id)["id"],)
            )
        else:
            rows = self._query("SELECT * FROM experiments ORDER BY updated_at DESC")
        for row in rows:
            row["metrics"] = json.loads(row.pop("metrics_json") or "{}")
        return rows

    def update_experiment(
        self,
        experiment_id: str,
        *,
        status: str | None = None,
        result_summary: str | None = None,
        metrics: Mapping[str, Any] | None = None,
        actor: str = "operator",
    ) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        fields: dict[str, Any] = {}
        if status is not None:
            fields["status"] = _check_choice(status, EXPERIMENT_STATUSES, "status")
        if result_summary is not None:
            fields["result_summary"] = _text(result_summary, "result_summary", required=False, limit=8000)
        if metrics is not None:
            merged = dict(experiment["metrics"])
            merged.update(dict(metrics))
            fields["metrics_json"] = json.dumps(merged, sort_keys=True)
        if fields.get("status") == "concluded" and not (fields.get("result_summary") or experiment["result_summary"]).strip():
            raise StoreError("concluding an experiment requires a result_summary")
        if not fields:
            return experiment
        with self._tx() as conn:
            assignments = ", ".join(f"{key}=?" for key in fields)
            conn.execute(
                f"UPDATE experiments SET {assignments}, updated_at=? WHERE id=?", (*fields.values(), utc_now(), experiment["id"])
            )
            self._activity(conn, "experiment.updated", experiment["id"], actor, {"status": fields.get("status")})
        return self.get_experiment(experiment["id"])

    def log_experiment(self, experiment_id: str, message: str, *, level: str = "info", actor: str = "operator") -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        with self._tx() as conn:
            cursor = conn.execute(
                "INSERT INTO experiment_events(experiment_id,level,message,created_at) VALUES (?,?,?,?)",
                (
                    experiment["id"],
                    _check_choice(level, ("info", "warn", "error", "result"), "level"),
                    _text(message, "message", limit=20_000),
                    utc_now(),
                ),
            )
            conn.execute("UPDATE experiments SET updated_at=? WHERE id=?", (utc_now(), experiment["id"]))
            self._activity(conn, "experiment.log", experiment["id"], actor, {"level": level})
            event_id = cursor.lastrowid
        return self._one("SELECT * FROM experiment_events WHERE id=?", (event_id,))

    # ----------------------------------------------------------------- activity
    def activity(self, *, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM activity WHERE seq > ? ORDER BY seq LIMIT ?", (int(after_seq), max(1, min(int(limit), 1000)))
        )
        for row in rows:
            row["detail"] = json.loads(row.pop("detail_json") or "{}")
        return rows

    def record_activity(self, topic: str, subject: str, *, actor: str = "system", detail: Mapping[str, Any] | None = None) -> None:
        with self._tx() as conn:
            self._activity(conn, topic, subject, actor, detail or {})

    def latest_seq(self) -> int:
        row = self._one("SELECT COALESCE(MAX(seq),0) AS seq FROM activity")
        return int(row["seq"]) if row else 0

    def summary(self) -> dict[str, Any]:
        totals = {state: 0 for state in TASK_STATES}
        for r in self._query("SELECT state, COUNT(*) AS n FROM tasks GROUP BY state"):
            totals[r["state"]] = r["n"]
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        day = self._one(
            """SELECT COUNT(*) AS outputs, SUM(COALESCE(tokens_in,0)+COALESCE(tokens_out,0)) AS tokens,
                      SUM(cost_usd) AS cost, AVG(latency_ms) AS latency FROM lane_messages WHERE created_at >= ?""",
            (since,),
        ) or {}
        council_day = self._one(
            """SELECT SUM(COALESCE(tokens_in,0)+COALESCE(tokens_out,0)) AS tokens, SUM(cost_usd) AS cost
               FROM council_messages WHERE created_at >= ?""",
            (since,),
        ) or {}
        done_24h = self._one("SELECT COUNT(*) AS n FROM tasks WHERE state='done' AND finished_at >= ?", (since,)) or {}
        lanes = self._query("SELECT status, COUNT(*) AS n FROM lanes GROUP BY status")
        return {
            "tasks": totals,
            "done_24h": done_24h.get("n") or 0,
            "lanes": {r["status"]: r["n"] for r in lanes},
            "outputs_24h": day.get("outputs") or 0,
            "tokens_24h": (day.get("tokens") or 0) + (council_day.get("tokens") or 0),
            "cost_24h": round((day.get("cost") or 0) + (council_day.get("cost") or 0), 6),
            "avg_latency_ms": day.get("latency"),
            "seq": self.latest_seq(),
        }


DEFAULT_LANES = (
    ("lane-research", "Research", "owned", "production", "Source-grounded research and synthesis."),
    ("lane-build", "Build", "owned", "production", "Code, tests and release engineering."),
    ("lane-content", "Content", "owned", "production", "Drafts, launch copy and media briefs."),
    ("lane-ops", "Ops", "owned", "production", "Infrastructure, cron, keys and reliability."),
    ("lane-arena", "Arena R&D", "observed", "rnd", "Head-to-head model matches and benchmarks."),
    ("lane-hermes", "Hermes", "observed", "rnd", "Hermes runtime experiments and hypotheses."),
)

# Model ids, endpoints and credential env names are starting points; edit them in
# the roster panel or with PATCH /api/council/members/{id}. Keys stay in the
# server environment and never reach the browser.
DEFAULT_MEMBERS = (
    dict(member_id="claude", display_name="Claude", provider="anthropic", model="claude-opus-5-5",
         credential_env="ANTHROPIC_API_KEY", seat="council", home_lane_id="lane-build", effort="medium"),
    dict(member_id="chatgpt", display_name="ChatGPT", provider="openai", model="gpt-5",
         base_url="https://api.openai.com/v1", credential_env="OPENAI_API_KEY", seat="council",
         home_lane_id="lane-research"),
    dict(member_id="meta-muse", display_name="Meta Muse", provider="openai_compatible",
         model="Llama-4-Maverick-17B-128E-Instruct-FP8", base_url="https://api.llama.com/compat/v1",
         credential_env="LLAMA_API_KEY", seat="council", home_lane_id="lane-content"),
    dict(member_id="hermes", display_name="Hermes", provider="openai_compatible", model="hermes3:70b",
         base_url="http://127.0.0.1:11434/v1", credential_env=None, seat="bench", home_lane_id="lane-hermes"),
    dict(member_id="gemini", display_name="Gemini", provider="openai_compatible", model="gemini-2.5-pro",
         base_url="https://generativelanguage.googleapis.com/v1beta/openai", credential_env="GEMINI_API_KEY",
         seat="bench", home_lane_id="lane-research"),
)


def seed_defaults(store: CommandCenterStore) -> None:
    """Create the default lanes and roster if they do not exist. Never adds work items."""
    existing_lanes = {lane["id"] for lane in store.list_lanes()}
    for lane_id, name, ownership, kind, description in DEFAULT_LANES:
        if lane_id not in existing_lanes:
            store.create_lane(lane_id, name=name, ownership=ownership, kind=kind, description=description, actor="seed")
    existing_members = {member["id"] for member in store.list_members()}
    for spec in DEFAULT_MEMBERS:
        if spec["member_id"] not in existing_members:
            store.add_member(actor="seed", **spec)
