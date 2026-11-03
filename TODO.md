# TODO

Backlog for work that came up but is out of scope for the current task.
Do these soon — before they grow too large.

## Server Side

### [ ] `FIXServer` — overseer for concurrent client sessions

**Problem:** nothing manages server-side sessions. `WebSocketServer` only
tracks raw sockets, keyed by `"ip:port"`. Each connection handler must
build its own adapter + `FIXSession` + `FIXEngine` and remember to
`disconnect()` — the only working example is inline in
`tests/integration/test_engine_e2e.py`. That means: no FIX session
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
    def __init__(self, config_factory, host, port, max_sessions=100): ...
    async def start(self): ...
    async def stop(self): ...            # stop every engine, then the WS server
    async def _on_connection(self, ws):
        adapter = WebSocketTransportAdapter(ws)
        session = FIXSession(config_factory())
        engine  = FIXEngine(session, adapter)
        # register by (sender, target) -> duplicate policy -> try/finally disconnect
    def sessions(self) -> list[FIXEngine]: ...   # introspection
```

**Test sketch:**

```
test_two_clients_get_independent_sessions      each has own seq + state
test_duplicate_logon_replaces_or_rejects        same comp IDs -> policy
test_disconnect_deregisters_and_stops_engine    no task leak
test_max_sessions_rejects_extra_connection      cap enforced
test_stop_tears_down_all_sessions               server.stop() drains
test_sessions_exposes_active_engines            introspection
```

**Placement:** not in any milestone today. `MILESTONES.md` puts the
*accept role* in M6 (`SessionRole`), but the concurrency manager is
needed to run a server at all. Recommended order: after M2 heartbeat,
before M3 reconnect — per-session reconnect is much easier once a
manager owns the sessions. It is also the natural attach point for the
per-session dispatcher discussed for M6.

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
