# TODO

Backlog for work that came up but is out of scope for the current task.
Do these soon — before they grow too large.

## Server Side

### [x] `FIXServer` — overseer for concurrent client sessions

**Shipped:** transport-agnostic `serve_connection(transport)` with an
identity registry and duplicate-logon rejection; listener wiring belongs
to the application. The sketch below is the original plan.

**Problem:** nothing manages server-side sessions. `WebSocketServer` only
tracks raw sockets, keyed by `"ip:port"`. Each connection handler must
build its own adapter + `FIXSession` + `FIXSessionRunner` and remember to
`disconnect()` — the only working example is inline in
`tests/integration/test_runner_e2e.py`. That means: no FIX session
registry, no duplicate-logon detection, no connection cap, no
centralized cleanup, no way to list active sessions.

**Why the socket key is not enough:** FIX sessions are identified by
`(SenderCompID, TargetCompID)`. On the server the client's
`SenderCompID` is our `TargetCompID`. Two connections from the same
counterparty are the *same* FIX session, and running both corrupts the
sequence numbers of both. Duplicate logon must log out the old session
(or refuse the new one) per spec.

**Shape:**

```python
class FIXServer:
    def __init__(self, config_factory, config: ServerConfig | None = None): ...
    async def start(self): ...
    async def stop(self): ...            # stop every runner
    async def _on_connection(self, ws):
        adapter = WebSocketTransportAdapter(ws)
        session = FIXSession(config_factory())
        runner  = FIXSessionRunner(session, adapter)
        # register by (sender, target) -> duplicate policy -> try/finally disconnect
    def sessions(self) -> list[FIXSessionRunner]: ...   # introspection
```

**Test sketch:**

```
test_two_clients_get_independent_sessions      each has own seq + state
test_duplicate_logon_replaces_or_rejects        same comp IDs -> policy
test_disconnect_deregisters_and_stops_runner    no task leak
test_max_sessions_rejects_extra_connection      cap enforced
test_stop_tears_down_all_sessions               server.stop() drains
test_sessions_exposes_active_runners            introspection
```

**Placement:** not in any milestone today. `MILESTONES.md` puts the
*accept role* in M6 (`SessionRole`), but the concurrency manager is
needed to run a server at all. Recommended order: after M2 heartbeat,
before M3 reconnect — per-session reconnect is much easier once a
manager owns the sessions. It is also the natural attach point for the
per-session dispatcher discussed for M6.

## Protocol Correctness (M2 follow-ups)

### [x] Bounded drain on teardown

**Shipped:** the writer exits only when `_stop_event` is set *and* the
queue is empty, so anything queued before teardown still reaches the
peer. `stop()` sets the flag, awaits reader and heartbeat (they exit on
their own poll), awaits the writer bounded, then closes the transport.
`_drain_and_close()` does the same for the session-driven ERROR and
Logout paths. Covered by `TestFIXSessionRunnerTeardown` in
`tests/unit/test_runner.py`.

### [x] Outbound heartbeat generation

**Shipped:** `FIXSession.send_heartbeat_if_idle()` emits a Heartbeat once
`heartbeat_interval` has passed with nothing sent, driven by the runner's
heartbeat task alongside `check_peer_liveness()`. Covered by
`TestFIXSessionHeartbeatSend` and `test_heartbeat_loop_sends_idle_heartbeat`.

## Session API Guards

### [x] Refuse application messages when not logged on

**Shipped:** `FIXSession.send()` raises `SessionNotLoggedOnError` for any
message outside the session-level set (Logon, Logout, Heartbeat,
TestRequest, ResendRequest, SequenceReset, Reject) unless the session is
`LOGGED_ON`. The check runs before the sequence number is assigned, so a
refused message leaves no hole. Covered by `TestFIXSessionSendGuard` in
`tests/unit/core/test_session.py`.

## Backpressure

### [ ] Bound the outbound send queue

`FIXSession._send_queue` is unbounded: if the transport stalls, queued
outbound messages grow the process without limit.

The callback queue is bounded (`SessionConfig.callback_queue_size`, default
10,000) and overflow is fatal. Outbound needs its own policy decision,
because dropping an unsent order is as wrong as dropping an execution.
Design it together with M3's bounded inbound queue, so both paths share one
policy and one set of observability hooks.

## Test Infrastructure

### [ ] Centralize test fixtures/builders

Fixture construction is duplicated across test files and will rot as the
test suite grows. Consolidate soon to promote reuse.

Current state:

- `tests/conftest.py` — `fix_parser`, `sample_logon`, `sample_new_order`
- `tests/unit/core/test_parser.py` — module-level `build_raw_message()` helper;
  `FIXParser()` re-created in every `setup_method` (6 classes)
- `tests/unit/core/test_session.py` — `session` fixture (also builds a
  `FIXMessageFactory` inline)
- `tests/unit/core/test_factory.py` — `FIXMessageFactory()` per `setup_method`
- `tests/unit/core/test_websocket.py` — `ws_server` fixture

Also duplicated data: the sample field sets (CLIENT01/MARKET01 headers,
AAPL order fields, logon tags 98/108) appear inline in several files
alongside the conftest versions.

Decide the layout before moving anything:

- Option A: one `tests/builders.py` (or shared `tests/conftest.py`) with
  message builders + shared fixtures
- Option B: one fixtures module per area, e.g. `tests/unit/core/fixtures.py`,
  re-exported through conftest

Recommendation: start with Option A while the suite is small; split per
module/type only when a file gets unwieldy.

## Notes

- Empty test packages already exist as placeholders: `tests/unit/client`,
  `tests/unit/market`, `tests/unit/persistence`, `tests/integration`,
  `tests/load` — move related fixtures there as those areas get tests.
- Related: `docs/KNOWN_ISSUES.md` for confirmed bugs; this file is for
  planned/deferred work only.
