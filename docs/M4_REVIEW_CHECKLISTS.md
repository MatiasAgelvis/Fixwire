# M4 Review Checklists

**Status:** M4 deliverable. Both checklists were walked by hand against
`src/fixwire` at the end of M4. Re-run them when logging or peer-facing
messages change.

---

## 1. Log audit — no secrets in logs

Scope: every `logger.<level>` call in `src/fixwire`. The taxonomy itself is
enforced mechanically (`tests/unit/test_logging_taxonomy.py`); this
checklist covers *content*, which no test can fully judge.

| # | Check | Result |
|---|---|---|
| 1 | No passwords, keys, certificates, or CA bundles are logged | ✅ none present |
| 2 | Credential-bearing FIX tags are redacted before logging | ✅ `Username` 553, `Password` 554, `NewPassword` 925, `RawData` 96 → `***` (`fixwire.core.redaction`) |
| 3 | Message payloads are truncated, never logged whole | ✅ parser diagnostics cap at 100 bytes (50 for checksum) |
| 4 | Counterparty free text (tag 58) is not logged at INFO or above | ✅ **fixed in M4**: `session.rejected` logged `text=`; now logs `text_length` |
| 5 | Credentials embedded in connection URLs are not logged | ✅ **fixed in M4**: `transport.ws.connected/closed` now log `redact_url()` |
| 6 | Composition IDs are fine to log (spec-public) | ✅ `sender` / `target` are logged, which the spec allows |
| 7 | No `logger.exception` smuggling tracebacks and locals into logs | ✅ forbidden by the taxonomy test |
| 8 | Log level never leaks more than the level implies | ✅ DEBUG carries message traces; INFO+ does not |

### Findings fixed here

- **`session.rejected` logged tag 58 verbatim.** The counterparty controls
  that string, so it is both a confidentiality and a log-injection risk.
  Now only its length is recorded.
- **`transport.ws.connected/closed` logged the raw URL.** `wss://user:pass@host`
  would have put the password in the log. Now redacted; the host and port
  remain, so the event is still useful.

### Known limits (accepted)

- Parser diagnostics still log *redacted* prefixes of malformed input. This
  is a deliberate trade: diagnosing a malformed message without its bytes
  is guesswork.
- Redaction is tag-based. A peer that puts a password in a non-credential
  tag will not be redacted — no heuristic can tell.
- Log volume is not rate-limited. A malformed-message flood produces one
  WARNING per message; shipping with a rate-limiting collector is the
  deployment answer.

---

## 2. Error message review — nothing internal reaches the peer

Scope: every string this engine can put on the wire in `Text` (58) or send
as a reason. FIX peers treat these as opaque, but they are still an
information channel.

| # | Check | Result |
|---|---|---|
| 1 | No stack traces or exception strings sent to the peer | ✅ `str(e)` appears only in log calls |
| 2 | No library or internal module names | ✅ peer-facing texts are plain English |
| 3 | No file paths, hostnames, or configuration echoed to the peer | ✅ none |
| 4 | Logout texts say what happened, in spec terms | ✅ e.g. `MsgSeqNum too low, expecting 5 but received 3` |
| 5 | Rejection texts do not disclose admission policy internals | ⚠️ `Session already logged on` — states the fact, not the registry |
| 6 | Transport-level errors are not forwarded verbatim | ✅ `WebSocketTransport` wraps them in `ConnectionError` for the caller; nothing forwards them to the peer |

### Peer-facing strings, exhaustively

From `FIXSession`:

- `MsgSeqNum too low, expecting {expected} but received {received}` — spec-defined condition, includes only sequence numbers.
- `Session already logged on` — admission rejection.
- `Heartbeat timeout: TestRequest unanswered` — spec-defined condition.

From `FIXSessionRunner`: none. The runner closes the transport; it does not
speak FIX.

### Known limits (accepted)

- `Reject` (3) is never sent for an invalid message — the factory exists but
  is unused (`docs/KNOWN_ISSUES.md`). When that lands, its `Text` must be
  reviewed with this list.
- `Session already logged on` reveals that *some* session holds the identity.
  A venue may prefer a generic refusal; that is a policy question for M6.

---

## Re-running these

```sh
# Taxonomy and content guards
python -m pytest tests/unit/test_logging_taxonomy.py -v

# Anything logging raw bytes, URLs, or free text
grep -rn "raw=\|url=\|text=" src/fixwire --include=*.py
```

Both findings above were produced by that second grep. It is the cheapest
way to start the review next time.
