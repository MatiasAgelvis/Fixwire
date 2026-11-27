# Audit Logging

**Status:** M3 deliverable. Enforced by `tests/unit/test_logging_taxonomy.py`.

## Purpose

FIXwire emits structured events through `structlog`. This document defines
what those events are called, what level they use, and what they may
contain — so a bank's SIEM, alerting, and compliance reporting can rely on
them instead of scraping free-form text.

The library emits; **the application decides where events go.** Call
`fixwire.logging.configure_logging()` once at startup, or configure
`structlog` yourself.

## Naming

```
<component>[.<subcomponent>].<event>
```

- `component` — one of `session`, `runner`, `server`, `transport`, `parser`.
  A new component is a change to this document.
- `subcomponent` — optional, one level, for implementations. Only
  `transport.ws.*` uses it today.
- `event` — `snake_case`, past tense where it describes something that
  happened: `logon_success`, `sequence_too_low`.

Event names are **static strings**. An f-string that builds a name is
rejected by the enforcement test, because a query for `session.*` would
silently miss it.

Renaming an event is a breaking change for anyone alerting on it: record it
in `CHANGELOG.md` under *Changed*, and keep the old name working for one
minor version if it has ever shipped.

## Levels

Levels are assigned by **operational consequence**, not by how bad the code
felt at that moment.

| Level | Meaning | Examples |
|---|---|---|
| `DEBUG` | Per-message trace. Safe to disable in production. Volume scales with traffic. | `session.message_queued`, `runner.message_written`, `transport.ws.sent` |
| `INFO` | Lifecycle transitions. One line per thing that changes the session's existence. | `session.state_change`, `session.logon_success`, `runner.reconnected` |
| `WARNING` | Expected-but-notable: a recoverable anomaly, a controlled refusal, or a retry. The session survives. | `session.sequence_gap`, `session.gap_fill_stale`, `server.duplicate_logon` |
| `ERROR` | A session-ending failure, or a server-wide fault. Someone should look. | `session.sequence_too_low`, `session.heartbeat_timeout`, `runner.task_error` |

There is no `CRITICAL`, and `logger.exception` is not used: tracebacks are
not audit events, and a library must not decide to dump stack frames into
an operator's log.

### Two nuances worth knowing

- **A policy refusal is not a failure.** `session.logon_rejected` is
  `WARNING`: the session ends, but it ended *as designed*. Rejecting a
  duplicate counterparty is routine.
- **A single session failing is not a server failure.**
  `server.session_failed` is `WARNING`; `ERROR` under `server.*` is
  reserved for the whole server being unable to serve.

## Required fields

Session-scoped events (`session.*`, `runner.*`) carry `sender` and `target`
where the session identity is known. Message-scoped events add `seq`
(MsgSeqNum) and `msg_type`.

Field names are the FIX concepts, not internal ones: `sender`, `target`,
`seq`, `msg_type`. Do not rename them per call site.

## What must never be logged

- Passwords, API keys, TLS private keys, certificates, or CA bundles.
- Full message payloads at `INFO` or above.
- Counterparty-supplied free text (tag 58 and friends) at `INFO` or above:
  it is attacker-controlled and may contain anything.
- Anything that would not be safe in a screenshot on a support ticket.

## Payloads are truncated

Parser diagnostics log at most the first 100 bytes of a message, and the
checksum diagnostics 50. Keep it that way: a malformed-message flood must
not become a log flood of full payloads.

## Retention and shipping

Retention is the operator's decision, not the library's. Guidance for
deployments:

- Ship to an append-only collector; do not rely on local files.
- Retain at least the audit window the institution's regulator requires.
- Run with `configure_logging(json=True)` when shipping: one JSON object per
  line, ISO-8601 UTC timestamps.
- `DEBUG` is off by default for a reason; enabling it in production is a
  deliberate, time-boxed act.

## Enforcement

`tests/unit/test_logging_taxonomy.py` parses `src/fixwire` and fails if:

- a level outside `debug|info|warning|error` appears,
- an event name is not namespaced or not `snake_case`,
- an event name is built with an f-string,
- `logger.critical` or `logger.exception` appears.

Adding a log call means satisfying these rules; adding a component means
editing this document and `ALLOWED_ROOTS` in that test.

## Event catalogue

### `session.*`

| Event | Level | Meaning |
|---|---|---|
| `session.state_change` | info | Status transition (`old`, `new`) |
| `session.message_queued` | debug | Message accepted for sending (not yet on the wire) |
| `session.message_received` | debug | Parsed inbound message |
| `session.logon_success` | info | Initiator's Logon was accepted |
| `session.logon_received` | info | Acceptor accepted a peer's Logon |
| `session.logon_rejected` | warning | Admission policy refused a Logon |
| `session.logout_complete` | info | Our Logout got a reply |
| `session.logout_received` | info | Peer's Logout handled |
| `session.heartbeat_test_response_received` | debug | TestRequest answered |
| `session.heartbeat_timeout` | error | TestRequest unanswered: session terminated |
| `session.sequence_gap` | warning | MsgSeqNum above expected: ResendRequest queued |
| `session.sequence_too_low` | error | MsgSeqNum below expected: session terminated |
| `session.duplicate_ignored` | debug | Low MsgSeqNum with PossDupFlag=Y |
| `session.resend_request` | info | Peer asked for a range |
| `session.sequence_reset` | info | SequenceReset (123=N) applied |
| `session.gap_fill` | info | SequenceReset-GapFill applied |
| `session.gap_fill_stale` | warning | GapFill would have moved backwards; ignored |
| `session.sequence_reset_malformed` | warning | SequenceReset without a usable NewSeqNo |
| `session.sequence_restored` | info | Persisted numbers adopted |
| `session.sequences_reset` | info | Local reset requested at connect |
| `session.rejected` | warning | Peer sent a Reject |
| `session.callback_error` | warning | An application callback raised |

### `runner.*`

| Event | Level | Meaning |
|---|---|---|
| `runner.message_written` | debug | Bytes handed to the transport |
| `runner.disconnected` | info | Explicit disconnect finished |
| `runner.logout_teardown` | info | Engine tore down after a peer Logout |
| `runner.logout_timeout` | warning | No Logout reply within `logout_timeout` |
| `runner.reconnected` | info | Reconnect succeeded |
| `runner.reconnect_attempt_failed` | warning | One attempt failed; retrying |
| `runner.discarded_on_reconnect` | warning | Queued messages dropped by request |
| `runner.session_error` | error | Teardown after the session entered ERROR |
| `runner.task_error` | error | Reader/writer task failed |
| `runner.callback_queue_full` | error | Application is not draining callbacks |
| `runner.close_after_error_failed` | warning | Transport close failed during error handling |

### `server.*`

| Event | Level | Meaning |
|---|---|---|
| `server.session_failed` | warning | One session raised out of its handler |
| `server.duplicate_logon` | warning | Live identity claimed again |
| `server.max_sessions_reached` | warning | Connection refused by the cap |
| `server.stop_timeout` | warning | Teardown exceeded the shutdown deadline |

### `shutdown.*`

| Event | Level | Meaning |
|---|---|---|
| `shutdown.started` | info | A termination signal triggered shutdown |
| `shutdown.complete` | info | Every stop callback ran |
| `shutdown.already_running` | warning | Signal re-delivered while shutting down |
| `shutdown.step_timeout` | warning | One stop callback exceeded its bound |
| `shutdown.step_failed` | error | One stop callback raised |

### `transport.ws.*`

| Event | Level | Meaning |
|---|---|---|
| `transport.ws.connected` | info | Client connection established |
| `transport.ws.closed` | info | Client connection closed |
| `transport.ws.sent` | debug | Frame sent (size only) |
| `transport.ws.received` | debug | Frame received (size only) |
| `transport.ws.client_connected` | info | Server accepted a connection |
| `transport.ws.client_disconnected` | info | Server connection ended |
| `transport.ws.message_received` | debug | Frame received by the server |
| `transport.ws.server_started` | info | Listener started |
| `transport.ws.server_stopped` | info | Listener stopped |
| `transport.ws.close_error` | warning | Close raised |

### `parser.*`

| Event | Level | Meaning |
|---|---|---|
| `parser.error` | warning | Message rejected in lenient mode |
| `parser.invalid_begin_string` | warning | Stream does not carry FIX |
| `parser.no_checksum` | warning | Message without a checksum |
| `parser.invalid_checksum_format` | warning | Checksum field malformed |
| `parser.checksum_mismatch` | warning | Checksum does not match the body |
| `parser.message_too_large` | warning | Message exceeded `max_message_size` |
| `parser.max_iterations` | warning | Parse loop hit its per-call bound |
