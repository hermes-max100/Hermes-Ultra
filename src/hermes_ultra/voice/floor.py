"""Floor control for multi-agent voice rooms (Hermes Council Bot on Discord).

One speaker at a time, strictly: only the floor holder may transmit, everyone
else who asks is queued until the floor is released. The audio path calls
``can_transmit(speaker)`` for every frame, so a revoked floor (release, mute,
interrupt, timeout) silences the speaker on the next frame.

Modes
- push-to-talk: the floor is held while the speaker's talk key is down
  (``press``/``release``); ``max_turn_s`` still caps a stuck key.
- hands-free: speakers request the floor by talking; the floor is released
  after ``silence_release_s`` without ``activity`` or after ``max_turn_s``.

Humans (the operator) can interrupt: the holder is cut immediately and the
interrupter takes the floor. Muted participants can neither hold nor queue.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Callable, Deque, Iterator


class FloorMode(str, Enum):
    PUSH_TO_TALK = "push_to_talk"
    HANDS_FREE = "hands_free"


class ParticipantKind(str, Enum):
    HUMAN = "human"
    AGENT = "agent"


class FloorError(ValueError):
    pass


@dataclass(frozen=True)
class FloorEvent:
    sequence: int
    at: float
    kind: str  # granted | queued | released | expired | interrupted | muted | unmuted | mode | cancelled
    speaker: str
    detail: str = ""


@dataclass(frozen=True)
class FloorDecision:
    granted: bool
    position: int  # 0 when holding the floor, 1.. queue position otherwise
    holder: str | None


@dataclass
class _Participant:
    id: str
    kind: ParticipantKind
    can_interrupt: bool
    muted: bool = False


@dataclass(frozen=True)
class FloorConfig:
    mode: FloorMode = FloorMode.PUSH_TO_TALK
    max_turn_s: float = 60.0
    silence_release_s: float = 1.5
    humans_first: bool = True  # queued humans go ahead of queued agents


class FloorController:
    """Thread-safe single-holder floor with a FIFO queue."""

    def __init__(self, config: FloorConfig | None = None, *, clock: Callable[[], float] = time.monotonic,
                 listener: Callable[[FloorEvent], None] | None = None) -> None:
        self.config = config or FloorConfig()
        self._mode = self.config.mode
        self._clock = clock
        self._listener = listener
        self._lock = threading.RLock()
        self._participants: dict[str, _Participant] = {}
        self._holder: str | None = None
        self._granted_at = 0.0
        self._last_activity = 0.0
        self._queue: Deque[str] = deque()
        self._events: list[FloorEvent] = []
        self._sequence = 0

    # ----------------------------------------------------------- roster
    def join(self, speaker: str, kind: ParticipantKind | str = ParticipantKind.AGENT,
             *, can_interrupt: bool | None = None) -> None:
        kind = ParticipantKind(kind)
        with self._lock:
            if speaker not in self._participants:
                interrupt = kind is ParticipantKind.HUMAN if can_interrupt is None else can_interrupt
                self._participants[speaker] = _Participant(speaker, kind, interrupt)

    def leave(self, speaker: str) -> None:
        with self._lock:
            self._expire()
            self._drop_from_queue(speaker, "left")
            if self._holder == speaker:
                self._release_holder("released", "left")
            self._participants.pop(speaker, None)

    # ------------------------------------------------------------ state
    @property
    def mode(self) -> FloorMode:
        return self._mode

    @property
    def holder(self) -> str | None:
        with self._lock:
            self._expire()
            return self._holder

    def queue(self) -> tuple[str, ...]:
        with self._lock:
            self._expire()
            return tuple(self._queue)

    def events(self) -> tuple[FloorEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def can_interrupt(self, speaker: str) -> bool:
        with self._lock:
            return self._get(speaker).can_interrupt

    def is_muted(self, speaker: str) -> bool:
        with self._lock:
            return self._get(speaker).muted

    def can_transmit(self, speaker: str) -> bool:
        """The per-frame gate. True only for the current, unmuted holder."""
        with self._lock:
            self._expire()
            participant = self._participants.get(speaker)
            return self._holder == speaker and participant is not None and not participant.muted

    def status(self) -> dict[str, object]:
        with self._lock:
            self._expire()
            return {
                "mode": self._mode.value,
                "holder": self._holder,
                "queue": list(self._queue),
                "muted": sorted(p.id for p in self._participants.values() if p.muted),
                "held_for_s": round(self._clock() - self._granted_at, 2) if self._holder else 0.0,
            }

    # -------------------------------------------------------- transitions
    def request(self, speaker: str) -> FloorDecision:
        """Ask for the floor: granted if free, otherwise queued (idempotent)."""
        with self._lock:
            self._expire()
            participant = self._get(speaker)
            if participant.muted:
                raise FloorError(f"{speaker} is muted")
            if self._holder == speaker:
                return FloorDecision(True, 0, speaker)
            if self._holder is None and not self._queue:
                self._grant(speaker, "free floor")
                return FloorDecision(True, 0, speaker)
            if speaker not in self._queue:
                self._enqueue(participant)
                self._emit("queued", speaker, f"behind {self._holder}")
            if self._holder is None:
                self._grant_next()
            return self._decision(speaker)

    def press(self, speaker: str) -> FloorDecision:
        """Push-to-talk key down."""
        return self.request(speaker)

    def release(self, speaker: str) -> bool:
        """Talk key up / end of utterance. Leaving the queue also counts as release."""
        with self._lock:
            self._expire()
            if self._holder == speaker:
                self._release_holder("released", "released by speaker")
                return True
            return self._drop_from_queue(speaker, "cancelled")

    def activity(self, speaker: str) -> None:
        """Voice activity from the holder; keeps a hands-free turn alive."""
        with self._lock:
            if self._holder == speaker:
                self._last_activity = self._clock()

    def interrupt(self, by: str, *, requeue_interrupted: bool = False) -> str | None:
        """Cut the current holder and give the floor to ``by``. Returns who was cut."""
        with self._lock:
            self._expire()
            interrupter = self._get(by)
            if not interrupter.can_interrupt:
                raise FloorError(f"{by} is not allowed to interrupt")
            if interrupter.muted:
                raise FloorError(f"{by} is muted")
            cut = self._holder if self._holder != by else None
            self._drop_from_queue(by, None)
            if cut is not None:
                self._holder = None
                self._emit("interrupted", cut, f"by {by}")
                if requeue_interrupted:
                    self._queue.appendleft(cut)
            if self._holder != by:
                self._grant(by, "interrupt")
            return cut

    def mute(self, speaker: str, *, by: str | None = None) -> None:
        with self._lock:
            self._expire()
            participant = self._get(speaker)
            participant.muted = True
            self._drop_from_queue(speaker, None)
            self._emit("muted", speaker, f"by {by}" if by else "")
            if self._holder == speaker:
                self._release_holder("released", "muted")

    def unmute(self, speaker: str, *, by: str | None = None) -> None:
        with self._lock:
            self._get(speaker).muted = False
            self._emit("unmuted", speaker, f"by {by}" if by else "")

    def mute_agents(self, *, by: str | None = None) -> list[str]:
        with self._lock:
            agents = [p.id for p in self._participants.values() if p.kind is ParticipantKind.AGENT and not p.muted]
            for agent in agents:
                self.mute(agent, by=by)
            return agents

    def set_mode(self, mode: FloorMode | str, *, by: str | None = None) -> None:
        with self._lock:
            self._mode = FloorMode(mode)
            self._last_activity = self._clock()
            self._emit("mode", by or "system", self._mode.value)

    # ------------------------------------------------------------ internals
    def _get(self, speaker: str) -> _Participant:
        participant = self._participants.get(speaker)
        if participant is None:
            raise FloorError(f"{speaker} has not joined the room")
        return participant

    def _decision(self, speaker: str) -> FloorDecision:
        if self._holder == speaker:
            return FloorDecision(True, 0, speaker)
        position = list(self._queue).index(speaker) + 1 if speaker in self._queue else -1
        return FloorDecision(False, position, self._holder)

    def _enqueue(self, participant: _Participant) -> None:
        if participant.kind is ParticipantKind.HUMAN and self.config.humans_first:
            index = next((i for i, queued in enumerate(self._queue)
                          if self._participants[queued].kind is not ParticipantKind.HUMAN), len(self._queue))
            self._queue.insert(index, participant.id)
        else:
            self._queue.append(participant.id)

    def _drop_from_queue(self, speaker: str, event: str | None) -> bool:
        if speaker in self._queue:
            self._queue.remove(speaker)
            if event:
                self._emit(event, speaker, "left queue")
            return True
        return False

    def _grant(self, speaker: str, reason: str) -> None:
        self._holder = speaker
        self._granted_at = self._last_activity = self._clock()
        self._emit("granted", speaker, reason)

    def _grant_next(self) -> None:
        while self._queue and self._holder is None:
            candidate = self._queue.popleft()
            participant = self._participants.get(candidate)
            if participant is not None and not participant.muted:
                self._grant(candidate, "next in queue")

    def _release_holder(self, kind: str, detail: str) -> None:
        released = self._holder
        self._holder = None
        if released is not None:
            self._emit(kind, released, detail)
        self._grant_next()

    def _expire(self) -> None:
        if self._holder is None:
            return
        now = self._clock()
        if now - self._granted_at >= self.config.max_turn_s:
            self._release_holder("expired", f"max turn {self.config.max_turn_s}s")
        elif self._mode is FloorMode.HANDS_FREE and now - self._last_activity >= self.config.silence_release_s:
            self._release_holder("expired", f"silent {self.config.silence_release_s}s")

    def _emit(self, kind: str, speaker: str, detail: str) -> None:
        self._sequence += 1
        event = FloorEvent(self._sequence, self._clock(), kind, speaker, detail)
        self._events.append(event)
        if len(self._events) > 2000:
            del self._events[:1000]
        if self._listener is not None:
            try:
                self._listener(event)
            except Exception:  # a broken announcer must never break floor control
                pass


class Turn:
    """Handle for one held floor; ``active`` turns False the frame the floor is lost."""

    def __init__(self, controller: FloorController, speaker: str) -> None:
        self._controller = controller
        self.speaker = speaker

    @property
    def active(self) -> bool:
        return self._controller.can_transmit(self.speaker)


class AsyncFloor:
    """asyncio front end: ``async with floor.turn("claude") as turn: ...``.

    Waiters are woken on every floor event, so a queued agent starts within one
    scheduler pass of the floor being released to it.
    """

    def __init__(self, controller: FloorController, *, poll_s: float = 0.02) -> None:
        self.controller = controller
        self._poll_s = poll_s

    @asynccontextmanager
    async def turn(self, speaker: str, *, timeout: float | None = None) -> AsyncIterator[Turn]:
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        self.controller.request(speaker)
        try:
            while not self.controller.can_transmit(speaker):
                if self.controller.is_muted(speaker):
                    raise FloorError(f"{speaker} was muted while waiting")
                if speaker not in self.controller.queue() and self.controller.holder != speaker:
                    self.controller.request(speaker)  # floor expired before we noticed; ask again
                if deadline is not None and loop.time() >= deadline:
                    raise asyncio.TimeoutError(f"{speaker} did not get the floor in {timeout}s")
                await asyncio.sleep(self._poll_s)
            yield Turn(self.controller, speaker)
        finally:
            self.controller.release(speaker)


def make_gated_pcm_source(discord_module, controller: FloorController, speaker: str, frames: Iterator[bytes]):
    """Build a discord.py ``AudioSource`` that only yields audio while ``speaker`` holds the floor.

    Returning ``b""`` ends playback, so an interrupt, mute or expiry stops the
    bot's audio on the next 20 ms frame. discord.py is passed in so this module
    imports without it.
    """

    class FloorGatedPCMSource(discord_module.AudioSource):
        def read(self) -> bytes:
            if not controller.can_transmit(speaker):
                return b""
            controller.activity(speaker)
            return next(frames, b"")

        def is_opus(self) -> bool:
            return False

    return FloorGatedPCMSource()


OPERATOR_COMMANDS = ("floor", "talk", "done", "interrupt", "mute", "unmute", "mute-agents", "ptt", "handsfree")


def handle_floor_command(controller: FloorController, actor: str, command: str, target: str | None = None) -> str:
    """Text/slash command surface for the Discord bot. Returns a one-line reply."""
    command = command.strip().lower().lstrip("/")
    try:
        if command == "floor":
            s = controller.status()
            queue = ", ".join(s["queue"]) or "empty"
            return f"Mode {s['mode']}; floor: {s['holder'] or 'free'}; queue: {queue}; muted: {', '.join(s['muted']) or 'none'}"
        if command == "talk":
            d = controller.request(actor)
            return f"{actor} has the floor" if d.granted else f"{actor} queued at position {d.position}"
        if command == "done":
            return f"{actor} released the floor" if controller.release(actor) else f"{actor} was not holding or queued"
        if command == "interrupt":
            cut = controller.interrupt(actor)
            return f"{actor} interrupted {cut}" if cut else f"{actor} has the floor"
        if command in ("mute", "unmute", "mute-agents", "ptt", "handsfree"):
            if not controller.can_interrupt(actor):  # operator-only controls
                return f"{actor} is not allowed to {command}"
            if command == "mute-agents":
                return "muted: " + (", ".join(controller.mute_agents(by=actor)) or "none")
            if command in ("ptt", "handsfree"):
                controller.set_mode(FloorMode.PUSH_TO_TALK if command == "ptt" else FloorMode.HANDS_FREE, by=actor)
                return f"mode set to {controller.mode.value}"
            if not target:
                return f"{command} needs a target"
            (controller.mute if command == "mute" else controller.unmute)(target, by=actor)
            return f"{target} {command}d"
        return f"unknown command {command}; try: {', '.join(OPERATOR_COMMANDS)}"
    except FloorError as exc:
        return str(exc)
