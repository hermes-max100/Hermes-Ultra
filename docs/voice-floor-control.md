# Voice floor control (Hermes Council Bot)

Strict one-speaker-at-a-time voice for the Council's Discord voice channel. Code: `src/hermes_ultra/voice/floor.py`. Tests: `tests/test_voice_floor.py`.

## Rules

- **One holder.** Only the floor holder transmits. The bot's audio source checks `can_transmit(speaker)` on every 20 ms frame and stops on the next frame once the floor is lost.
- **Queue.** Anyone else who asks is queued first in, first out until the holder releases. Asking again does nothing. A queued human goes ahead of queued agents (`humans_first`).
- **Push-to-talk** (default). The floor is held while the talk key is down (`press`/`release`). `max_turn_s` (default 60 s) ends a stuck key.
- **Hands-free** (optional). Talking requests the floor. It is released after `silence_release_s` (default 1.5 s) with no voice activity, or at `max_turn_s`.
- **Interrupt.** Humans only, by default. The holder is cut immediately and the interrupter takes the floor. `requeue_interrupted=True` puts the cut speaker back at the front of the queue.
- **Mute.** A muted participant can't hold or queue. Muting the holder passes the floor on. `mute_agents` silences every agent and leaves humans alone.
- **Events.** Every grant, queue, release, expiry, interrupt, mute and mode change is recorded as a `FloorEvent`. A listener can post them to the text channel. A failing listener never blocks floor control.

## Agent usage

```python
floor = AsyncFloor(controller)
async with floor.turn("claude", timeout=30) as turn:   # waits in queue
    for frame in tts_frames:
        if not turn.active:        # interrupted, muted or expired
            break
        send(frame)
```

For discord.py playback, `make_gated_pcm_source(discord, controller, "claude", frames)` returns an `AudioSource` that yields audio only while Claude holds the floor.

## Discord commands (`handle_floor_command`)

| Command | Who | Effect |
|---|---|---|
| `/floor` | anyone | mode, holder, queue, muted |
| `/talk` | anyone | take the floor or join the queue (push-to-talk key down) |
| `/done` | anyone | release the floor or leave the queue |
| `/interrupt` | operator | cut the holder, take the floor |
| `/mute <who>` / `/unmute <who>` | operator | mute control |
| `/mute-agents` | operator | mute every agent |
| `/ptt` / `/handsfree` | operator | switch mode |

## Verified

- 20 tests, run 30 times with no flaky results.
- Multi-agent simulation, run in both modes: six agents and the operator talk at once while one agent is muted and the operator interrupts. No frame ever comes from a non-holder, no two speakers' frames interleave, the muted agent never transmits, and every other agent gets a turn.
- Thread stress test: 16 threads, 400 turns, never more than one transmitter at a time.
- Deliberately breaking the gate makes 8 tests fail.

## Not yet done

Live wiring into the running Hermes Council Bot on `hermes-max-primary` waits on Tailscale SSH approval for that host.
