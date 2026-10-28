import asyncio
import random
import threading
import types
import unittest

from hermes_ultra.voice.floor import (
    AsyncFloor,
    FloorConfig,
    FloorController,
    FloorError,
    FloorMode,
    ParticipantKind,
    handle_floor_command,
    make_gated_pcm_source,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def room(mode=FloorMode.PUSH_TO_TALK, **config):
    clock = FakeClock()
    ctrl = FloorController(FloorConfig(mode=mode, **config), clock=clock)
    ctrl.join("carmelo", ParticipantKind.HUMAN)
    for agent in ("claude", "chatgpt", "muse", "hermes"):
        ctrl.join(agent)
    return ctrl, clock


class FloorControllerTests(unittest.TestCase):
    def test_only_holder_transmits_and_others_queue_fifo(self):
        ctrl, _ = room()
        self.assertTrue(ctrl.press("claude").granted)
        self.assertEqual(ctrl.press("chatgpt").position, 1)
        self.assertEqual(ctrl.press("muse").position, 2)
        self.assertEqual(ctrl.press("chatgpt").position, 1)  # idempotent
        self.assertEqual([a for a in ("claude", "chatgpt", "muse", "hermes") if ctrl.can_transmit(a)], ["claude"])
        ctrl.release("claude")
        self.assertEqual(ctrl.holder, "chatgpt")
        self.assertFalse(ctrl.can_transmit("claude"))
        ctrl.release("chatgpt")
        self.assertEqual(ctrl.holder, "muse")
        ctrl.release("muse")
        self.assertIsNone(ctrl.holder)

    def test_humans_queue_ahead_of_agents(self):
        ctrl, _ = room()
        ctrl.press("claude")
        ctrl.press("chatgpt")
        ctrl.press("muse")
        self.assertEqual(ctrl.press("carmelo").position, 1)
        self.assertEqual(ctrl.queue(), ("carmelo", "chatgpt", "muse"))

    def test_cancel_leaves_queue(self):
        ctrl, _ = room()
        ctrl.press("claude")
        ctrl.press("chatgpt")
        self.assertTrue(ctrl.release("chatgpt"))
        ctrl.release("claude")
        self.assertIsNone(ctrl.holder)

    def test_interrupt_cuts_holder_immediately(self):
        ctrl, _ = room()
        ctrl.press("claude")
        ctrl.press("chatgpt")
        self.assertEqual(ctrl.interrupt("carmelo"), "claude")
        self.assertFalse(ctrl.can_transmit("claude"))
        self.assertTrue(ctrl.can_transmit("carmelo"))
        self.assertEqual(ctrl.queue(), ("chatgpt",))
        ctrl.release("carmelo")
        self.assertEqual(ctrl.holder, "chatgpt")

    def test_interrupt_can_requeue_the_cut_speaker_first(self):
        ctrl, _ = room()
        ctrl.press("claude")
        ctrl.press("chatgpt")
        ctrl.interrupt("carmelo", requeue_interrupted=True)
        self.assertEqual(ctrl.queue(), ("claude", "chatgpt"))

    def test_agents_cannot_interrupt_by_default(self):
        ctrl, _ = room()
        ctrl.press("claude")
        with self.assertRaises(FloorError):
            ctrl.interrupt("chatgpt")
        self.assertEqual(ctrl.holder, "claude")

    def test_mute_revokes_floor_and_blocks_requests(self):
        ctrl, _ = room()
        ctrl.press("claude")
        ctrl.press("chatgpt")
        ctrl.mute("claude", by="carmelo")
        self.assertFalse(ctrl.can_transmit("claude"))
        self.assertEqual(ctrl.holder, "chatgpt")
        with self.assertRaises(FloorError):
            ctrl.press("claude")
        ctrl.mute("muse")
        self.assertNotIn("muse", ctrl.queue())
        ctrl.unmute("claude")
        self.assertEqual(ctrl.press("claude").position, 1)

    def test_mute_agents_leaves_humans(self):
        ctrl, _ = room()
        ctrl.press("claude")
        muted = ctrl.mute_agents(by="carmelo")
        self.assertEqual(sorted(muted), ["chatgpt", "claude", "hermes", "muse"])
        self.assertIsNone(ctrl.holder)
        self.assertTrue(ctrl.press("carmelo").granted)

    def test_push_to_talk_stuck_key_expires_at_max_turn(self):
        ctrl, clock = room(max_turn_s=30)
        ctrl.press("claude")
        ctrl.press("chatgpt")
        clock.advance(29)
        self.assertTrue(ctrl.can_transmit("claude"))  # silence does not end a PTT turn
        clock.advance(1)
        self.assertFalse(ctrl.can_transmit("claude"))
        self.assertEqual(ctrl.holder, "chatgpt")
        self.assertEqual(ctrl.events()[-2].kind, "expired")

    def test_hands_free_releases_after_silence(self):
        ctrl, clock = room(mode=FloorMode.HANDS_FREE, silence_release_s=1.5)
        ctrl.request("claude")
        ctrl.request("muse")
        for _ in range(5):
            clock.advance(1.0)
            ctrl.activity("claude")
        self.assertEqual(ctrl.holder, "claude")
        clock.advance(1.5)
        self.assertEqual(ctrl.holder, "muse")

    def test_mode_switch_and_status(self):
        ctrl, _ = room()
        ctrl.set_mode("hands_free", by="carmelo")
        ctrl.request("claude")
        self.assertEqual(ctrl.status()["mode"], "hands_free")
        self.assertEqual(ctrl.status()["holder"], "claude")

    def test_leaving_holder_passes_floor(self):
        ctrl, _ = room()
        ctrl.press("claude")
        ctrl.press("chatgpt")
        ctrl.leave("claude")
        self.assertEqual(ctrl.holder, "chatgpt")

    def test_unknown_speaker_rejected(self):
        ctrl, _ = room()
        with self.assertRaises(FloorError):
            ctrl.press("stranger")
        self.assertFalse(ctrl.can_transmit("stranger"))

    def test_listener_failure_does_not_break_floor(self):
        ctrl = FloorController(listener=lambda e: 1 / 0)
        ctrl.join("claude")
        self.assertTrue(ctrl.press("claude").granted)


class CommandTests(unittest.TestCase):
    def test_operator_and_agent_commands(self):
        ctrl, _ = room()
        self.assertEqual(handle_floor_command(ctrl, "claude", "/talk"), "claude has the floor")
        self.assertEqual(handle_floor_command(ctrl, "chatgpt", "talk"), "chatgpt queued at position 1")
        self.assertIn("floor: claude; queue: chatgpt", handle_floor_command(ctrl, "carmelo", "floor"))
        self.assertEqual(handle_floor_command(ctrl, "chatgpt", "mute", "claude"), "chatgpt is not allowed to mute")
        self.assertEqual(handle_floor_command(ctrl, "carmelo", "interrupt"), "carmelo interrupted claude")
        self.assertEqual(handle_floor_command(ctrl, "carmelo", "mute", "chatgpt"), "chatgpt muted")
        self.assertEqual(handle_floor_command(ctrl, "carmelo", "handsfree"), "mode set to hands_free")
        self.assertEqual(handle_floor_command(ctrl, "carmelo", "ptt"), "mode set to push_to_talk")
        self.assertEqual(handle_floor_command(ctrl, "carmelo", "done"), "carmelo released the floor")
        self.assertIn("unknown command", handle_floor_command(ctrl, "carmelo", "dance"))


class DiscordSourceTests(unittest.TestCase):
    def test_gated_source_stops_on_the_next_frame_after_interrupt(self):
        fake_discord = types.SimpleNamespace(AudioSource=object)
        ctrl, _ = room()
        ctrl.press("claude")
        frames = iter([b"\x01" * 3840] * 100)
        source = make_gated_pcm_source(fake_discord, ctrl, "claude", frames)
        self.assertEqual(len(source.read()), 3840)
        self.assertFalse(source.is_opus())
        ctrl.interrupt("carmelo")
        self.assertEqual(source.read(), b"")  # discord.py ends playback on empty read

    def test_queued_speaker_source_is_silent(self):
        fake_discord = types.SimpleNamespace(AudioSource=object)
        ctrl, _ = room()
        ctrl.press("claude")
        ctrl.press("muse")
        source = make_gated_pcm_source(fake_discord, ctrl, "muse", iter([b"x" * 3840]))
        self.assertEqual(source.read(), b"")


class MultiAgentSimulationTests(unittest.TestCase):
    """Six agents and the operator all try to talk at once; the floor must serialize them."""

    def run_room(self, mode):
        ctrl = FloorController(FloorConfig(mode=mode, max_turn_s=5.0, silence_release_s=0.05))
        floor = AsyncFloor(ctrl, poll_s=0.001)
        agents = ["claude", "chatgpt", "muse", "hermes", "gemini", "grok"]
        ctrl.join("carmelo", ParticipantKind.HUMAN)
        for agent in agents:
            ctrl.join(agent)
        on_air = []          # every transmitted frame, in order
        violations = []
        cut_short = set()

        async def speak(agent, frames=8, start_delay=0.0):
            await asyncio.sleep(start_delay)
            async with floor.turn(agent, timeout=10) as turn:
                for i in range(frames):
                    if not turn.active:
                        cut_short.add(agent)
                        break
                    if ctrl.holder != agent:
                        violations.append((agent, ctrl.holder))
                    on_air.append(agent)
                    ctrl.activity(agent)
                    await asyncio.sleep(0.002)  # one "20 ms" frame, scaled down

        async def operator():
            await asyncio.sleep(0.02)
            ctrl.mute("grok", by="carmelo")
            await asyncio.sleep(0.01)
            cut = ctrl.interrupt("carmelo")
            if cut:
                cut_short.add(cut)
            for _ in range(5):
                on_air.append("carmelo")
                if ctrl.holder != "carmelo":
                    violations.append(("carmelo", ctrl.holder))
                await asyncio.sleep(0.002)
            ctrl.release("carmelo")

        async def main():
            tasks = [speak(a) for a in agents if a != "grok"]
            tasks.append(speak("grok", start_delay=0.05))  # asks after being muted
            tasks.append(operator())
            return await asyncio.gather(*tasks, return_exceptions=True)

        results = asyncio.run(main())
        return ctrl, on_air, violations, cut_short, results

    def check(self, mode):
        ctrl, on_air, violations, cut_short, results = self.run_room(mode)
        self.assertEqual(violations, [], "a non-holder transmitted")
        # Each speaker's frames form one contiguous block: nobody talked over anybody.
        runs = [s for i, s in enumerate(on_air) if i == 0 or on_air[i - 1] != s]
        self.assertEqual(len(runs), len(set(runs)), f"interleaved speech: {runs}")
        self.assertNotIn("grok", on_air)  # muted agent never transmitted
        self.assertIsInstance(results[5], FloorError)  # grok's request was refused
        self.assertIn("carmelo", on_air)  # interrupt took effect
        self.assertEqual(len(cut_short), 1)  # exactly the holder at interrupt time was cut
        for agent in ("claude", "chatgpt", "muse", "hermes", "gemini"):
            self.assertIn(agent, on_air, f"{agent} starved")
        self.assertIsNone(ctrl.holder)
        self.assertEqual(ctrl.queue(), ())

    def test_push_to_talk_room(self):
        self.check(FloorMode.PUSH_TO_TALK)

    def test_hands_free_room(self):
        self.check(FloorMode.HANDS_FREE)


class ThreadStressTests(unittest.TestCase):
    def test_never_two_transmitters_under_thread_contention(self):
        ctrl = FloorController(FloorConfig(max_turn_s=60))
        speakers = [f"agent{i}" for i in range(16)]
        for s in speakers:
            ctrl.join(s)
        stats = {"active": 0, "max": 0, "turns": 0}
        stats_lock = threading.Lock()

        def worker(name):
            rng = random.Random(name)
            turns = 0
            while turns < 25:
                ctrl.press(name)
                if ctrl.can_transmit(name):
                    with stats_lock:
                        stats["active"] += 1
                        stats["max"] = max(stats["max"], stats["active"])
                        stats["turns"] += 1
                    if rng.random() < 0.5:
                        threading.Event().wait(0.0005)
                    with stats_lock:
                        stats["active"] -= 1
                    ctrl.release(name)
                    turns += 1
                else:
                    threading.Event().wait(0.0002)

        threads = [threading.Thread(target=worker, args=(s,)) for s in speakers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(stats["max"], 1)
        self.assertEqual(stats["turns"], 16 * 25)
        self.assertIsNone(ctrl.holder)


if __name__ == "__main__":
    unittest.main()
