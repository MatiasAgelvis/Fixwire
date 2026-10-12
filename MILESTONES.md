# Milestones — FIXwire V1.0

> **Project framing:** Banking-grade, single-developer FIX 4.4 engine.
> "Sea-worthy" — installable and runnable by a financial institution at V1.0.
> No shortcuts that compromise correctness, even if they would let us ship faster.
>
> This file is the **long-term roadmap**. For short-term backlog, see `TODO.md`.
> For confirmed bugs and known debt, see `docs/KNOWN_ISSUES.md`.

---

## Principles

These are non-negotiable. Every milestone, every PR, every test reference flows from them.

1. **Strict by default.** Fail closed on bad input. Strict mode is the production mode.
2. **Sequence numbers are sacred.** Every outgoing message carries the right seq; every incoming seq is verified; persistence survives restart.
3. **Heartbeats follow the FIX 4.4 spec.** Timing, TestRequest enforcement, and disconnect-on-timeout are exact, not approximate.
4. **Errors are recoverable.** Retries with backoff are first-class, not an afterthought.
5. **Logs are auditable, secrets are not.** Every state transition logged; no PII or credentials in messages.
6. **Tests are the proof of sea-worthiness.** Exhaustive coverage at the unit and integration level; conformance tested against the FIX 4.4 specification.
7. **Backward compatibility is a feature.** Anything deferred to V1.x ships behind a clean extension point — never as silent debt.

---

## Testing Bar Scale

Every milestone declares which level it aims at. Level must be **proven via the test suite**, not asserted in prose.

| Level | What it means | How it's measured |
|---|---|---|
| **A** | Exhaustive unit tests (nominal + every failure path) **+** happy-path integration | Per-function failure matrix; one E2E test proving the path works end to end |
| **B** | A + chaos integration suite. Inject: gaps, duplicate seq, out-of-order, heartbeat timeout, malformed checksum, mid-stream disconnect, slow consumer, replay attack | Each chaos scenario is its own named test that passes deterministically |
| **C** (target) | B + conformance to FIX 4.4 spec. Cross-check message semantics against the official spec | Spec cross-check matrix: every spec requirement maps to a test name; no requirement without a test |

**V1.0 target: Level C ideally, Level B minimum.** M1–M5 must reach Level B as a floor; M6 raises to Level C.

---

## Status Legend

| Symbol | Meaning |
|---|---|
| ✅ | Done — meets its test bar, merged to `develop` |
| 🚧 | In progress — active branch, not yet merged |
| ⏸️ | Blocked — waiting on a dependency or decision |
| [ ] | Todo — not started |

---

## Milestone Roadmap to V1.0

| # | Milestone | Test bar | Status | Notes |
|---|---|---|---|---|
| M0 | Foundations (core protocol + transport) | A | ✅ Done | message, parser, factory, session — protocol logic |
| M1 | Engine architecture (extract `FIXEngine`, wire transport) | A | [ ] Todo | Refactor + new middle layer + bounded inbound queue + lifecycle |
| M2 | Protocol hardening (seq verify, heartbeat, reject, gap-fill) | B | [ ] Todo | Incoming seq verify is the critical missing piece |
| M3 | Resilience (reconnect, persistence, audit logging) | B | [ ] Todo | Pluggable `SequenceStore` interface; file-backed default |
| M4 | Security (WSS, TLS, no-secret-in-logs) | B | [ ] Todo | `wss://` first-class; cert validation configurable |
| M5 | Full resend (real replay, not just GapFill) | B | [ ] Todo | Persistent outbox; resend semantics per spec |
| M6 | FIX 4.4 conformance & roles (accept + initiate) | **C** | [ ] Todo | Spec cross-check matrix; raises V1.0 to Level C |
| M7 | V1.0 release (packaging, docs, CI, signing) | C | [ ] Todo | Banking-installable wheel + Docker + signed releases |

---

## M0 — Foundations ✅ Done

**Goal:** Provide the building blocks the rest of the project depends on.

**Deliverables:**
- ✅ `FIXMessage` — protocol-typed message with serialization + convenience properties
- ✅ `FIXParser` — strict-mode default; binary safe; validates checksum
- ✅ `FIXMessageFactory` — session-message creators (Logon, Logout, Heartbeat, TestRequest, Resend, Reject, SequenceReset)
- ✅ `Transport` Protocol and `WebSocketTransport` (client) / `WebSocketTransportAdapter` (server-side) / `WebSocketServer`
- ✅ `SessionStatus` state machine and `SessionConfig`
- ✅ Tests at level A for each module
- ✅ Methodology documented (TDD, AAA, fixtures strategy in `TODO.md`)

**Test bar reached:** A.

**Known carryover:** see `docs/KNOWN_ISSUES.md`. The Transport layer still had typing/idempotency cleanup which was resolved in commit history; no open debt there.

---

## M1 — Engine Architecture (refactor + integration)

**Goal:** Wire the FIX protocol state machine to the transport via a dedicated middle layer. After M1, a session can send and receive real FIX messages over a real WebSocket.

**Scope:**
- Refactor `FIXSession` into a **pure protocol state machine**: no asyncio tasks, no transport references, no I/O concerns. It exposes `send(msg)` and `receive(raw_bytes)` only.
- Add **`FIXEngine`** as the middle-layer coordinator that owns the transport and the I/O machinery.
- Inbound model: **bounded `asyncio.Queue`** between the transport and the session, so backpressure is visible and the app can pull at its pace.
- Outbound: writer task drains `FIXSession._send_queue` and pushes bytes through the transport.
- Lifecycle: `FIXEngine.connect()`, `FIXEngine.disconnect()`, with `engine.reconnect()` prepared but unused until M3.
- Strict error handling: any unhandled exception in a reader/writer task → `session.status = ERROR`, transport closed, exception logged.
- WSS usable immediately (no client-cert auth yet — M4).

**Out of scope (deferred to later milestones, with explicit reason):**
- Sequence persistence (M3)
- Auto-reconnect (M3)
- Incoming sequence verification (M2)
- Spec timing for heartbeat/TestRequest (M2)
- TLS client cert auth (M4)

**Deliverables:**
- `FIXEngine` class with documented public API
- `FIXSession` slimmed down (no `_heartbeat_task`, no transport reference, no I/O)
- Refactor test suite that proves the protocol layer works without I/O
- **One integration test:** two sessions over a real WebSocket exchange Logon → Heartbeat → Logout
- Design doc: `docs/design/session-transport.md` documenting architecture and decisions
- Branch: `feature/session-transport-integration`

**Test bar reached:** A (exhaustive unit for protocol layer; one happy-path integration).

---

## M2 — Protocol Hardening

**Goal:** Make the protocol layer conform to FIX 4.4 at the message-semantics level.

**Scope:**
- **Incoming sequence number verification.** Every received message's `MsgSeqNum` (34) is compared against the expected next. Mismatch → `Reject` (3) in non-strict, `Logout` (5) in strict.
- **Heartbeat timing per FIX 4.4:** `heartbeat_interval × 1.2` grace window before declaring peer dead.
- **TestRequest enforcement.** If a TestRequest is unanswered within spec window → log warning, escalate to `ERROR` then disconnect.
- **Reject (3) handling** in `_handle_reject` per spec semantics.
- **GapFill** vs full resend decision: gap fill if sequence > expected within range; full resend request if out of range (prepares M5).
- **Strict mode**: `FIXParser(strict_mode=True)` is the **default constructor**, not an opt-in.
- **Datetime fix.** `datetime.utcnow()` (deprecated in 3.12) → `datetime.now(timezone.utc)` or `datetime.now(UTC)` — done across the whole codebase, not just the new code.

**Deliverables:**
- Incoming sequence verifier with reject/logout behavior
- Heartbeat monitor with spec timing
- TestRequest enforcement with disconnect escalation
- Reject/gap-fill conformance tests
- Strict default across the parser
- Datetime migration

**Test bar reached:** B. Each protocol-level failure mode has its own named test.

---

## M3 — Resilience & Recovery

**Goal:** Survive process restart and transient network loss without operator intervention.

**Scope:**
- **`SequenceStore` protocol.** Pluggable; default implementation = file-backed JSON per session (atomic write on each seq change).
- **Reconnection with exponential backoff.** `engine.reconnect(Strategy)` with `max_retries` and base `retry_delay`; honors `config.max_retries` and `config.retry_delay` from `SessionConfig`.
- **Crash-safe outbox** (foundation for M5). Outbound messages persisted before they hit the wire; restored on reconnect.
- **Audit logging.** Every state transition, every msg in/out, every error — structured via `structlog`, levels correct (DEBUG for message traces, INFO for lifecycle, WARNING for recoverable, ERROR for sessions-ending, no CRITICAL).
- **Time shutdown.** Clean shutdown on SIGTERM — graceful logout first, then transport close.

**Deliverables:**
- `SequenceStore` interface + `FileSequenceStore` + `InMemorySequenceStore` (the latter for tests)
- Reconnect logic with exponential backoff (jittered)
- Outbox storage interface
- Audit log spec (event names, payloads, retention policy)
- Graceful shutdown

**Test bar reached:** B. Chaos scenarios for: process crash mid-message, network drop mid-stream, restart with persisted seq.

---

## M4 — Security

**Goal:** Encryption and certificate handling suitable for a financial institution.

**Scope:**
- **WSS first-class.** `WebSocketTransport` accepts `wss://` URLs; cert validation configurable (default: required).
- **TLS client certificate authentication** (mutual TLS) for FIX-over-TLS scenarios. Server-side: require client cert. Client-side: present cert.
- **Configurable CA bundle** for verification (system default, custom path, or disable for test environments).
- **No secrets in logs.** Audit of all `logger.info/warning/error` calls to verify no `sender_comp_id`/`target_comp_id` combos reveal anything beyond what's spec-public, no cert/keys/passwords in any log line.
- **Error message review.** No internal stack traces or library names in messages returned to the network.

**Deliverables:**
- WSS round-trip integration test
- mTLS round-trip integration test (mutual TLS)
- Log audit checklist (signed off by hand)
- Error message review checklist

**Test bar reached:** B. WSS + mTLS have their own integration tests; log audit is a manual sign-off.

---

## M5 — Full Resend

**Goal:** Replace the placeholder GapFill in `_handle_resend_request` with real resend of original messages per FIX 4.4 spec.

**Scope:**
- **Outbox persistence** (foundation laid in M3, completed here). Every sent message body stored until acknowledged or pruned.
- **Resend request handling.** On receiving ResendRequest (2), replay original messages from the outbox in order. If a message isn't available (e.g. never sent), send SequenceReset-GapFill (4, 123=Y) with appropriate NewSeqNo.
- **End-of-resend semantics.** Session sends `EndOfResend` (marker via SequenceReset with `NewSeqNo = last + 1`) per spec.
- **Time-bounded outbox pruning.** Configurable retention (default: configurable per session; sane production default).

**Deliverables:**
- Outbox-backed resend implementation
- Spec-compliant GapFill decision logic
- Tests for: resend a single message, resend a range, resend with missing messages (GapFill)

**Test bar reached:** B.

---

## M6 — FIX 4.4 Conformance & Roles

**Goal:** Conform to the FIX 4.4 specification. Add the missing session role(s) and prove conformance against the spec document.

**Scope:**
- **Accept-session role (server-side).** Today the session is initiator-only. Add a `role: SessionRole` field in `SessionConfig`. Server accepts incoming Logons, validates credentials, responds.
- **Initiate-session role (client-side).** Already supported but formalized as `SessionRole.INITIATOR`.
- **Spec cross-check matrix.** A doc (`docs/FIX44_CONFORMANCE.md`) listing every FIX 4.4 requirement with a test name that proves it. No requirement without a named test.
- **Full conformance test suite.** Each requirement → a passing test. The suite is the artifact a bank runs in CI before installing.
- **Logout handshake conformance.** Server-initiated logout and client-initiated logout both follow spec timing.
- **PossDup / PossResend flag handling** (prepares reload semantics).

**Deliverables:**
- `SessionRole` enum and conditional behavior in session
- Accept-session path (server message handler)
- `docs/FIX44_CONFORMANCE.md` matrix
- Conformance test suite

**Test bar reached:** **C**. This is where V1.0 reaches the target test bar.

---

## M7 — V1.0 Release

**Goal:** A banking institution can install and run the engine.

**Scope:**

#### Packaging
- **Wheel.** `pyproject.toml` cleanup; `pip install fixwire` works on Python 3.11+.
- **Versioning policy** documented (`docs/VERSIONING.md`) following semver with a clear deprecation contract.
- **CHANGELOG.md** following Keep a Changelog format.
- **Migration notes** for any pre-V1.0 consumers (none yet, but the artifact exists).

#### Containerization
- **Multi-arch image.** `linux/amd64` and `linux/arm64`, published side by side.
- **Minimal base.** Distroless or equivalent — no shell, no package manager, no `apt`.
- **Non-root user.** Image runs as a fixed non-root UID; no privilege escalation possible.
- **Reproducible builds.** Same source + same build inputs = bit-identical image digest.
- **Pinned tags.** `v1.0.0`, `1.0`, `1.0.0-amd64` etc. **No `latest` tag.** Releases are immutable.
- **Image size budget.** < 200 MB compressed for the runtime image (track in CI; fail if exceeded).
- **Healthcheck.** `HEALTHCHECK` baked into the Dockerfile or `compose`-level default that maps to the engine's status endpoint.

#### Supply-chain security
- **SBOM** generated for every release (CycloneDX or SPDX), attached to the GitHub release and the container registry.
- **Vulnerability scanning** in CI (Trivy or Grype). Build fails on `HIGH`/`CRITICAL` for any base image or dependency CVE.
- **Image signing.** Sigstore/cosign signatures on every published tag; verifiable by anyone.
- **Wheel signing.** Signed wheel metadata; verifiability documented in `INSTALL.md`.

#### Documentation set
- **`INSTALL.md`** — install (wheel, docker run, docker-compose).
- **`CONFIGURATION.md`** — every config field, defaults, overrides, examples for common deployments.
- **`OPERATIONS.md`** — startup, shutdown, log interpretation, alerting hooks.
- **`TROUBLESHOOTING.md`** — common failures with diagnostic steps.
- **Migration notes** for pre-V1.0 users (none today; the artifact exists).

#### CI/CD pipeline
- GitHub Actions matrix: lint (`ruff`), typecheck (`mypy`), full test suite, conformance suite, coverage gate, build artifact, sign, publish.
- Branch protection on `main` and `develop` requires green CI.
- Coverage gate enforced in CI for `src/fixwire/core/` and `src/fixwire/transport/`.

#### Final sign-off
- **Final security review.** Checklist covering M2 (seq verify), M4 (TLS, no-secret logs).
- **Manual run-through** of `INSTALL.md` and `OPERATIONS.md` on a fresh machine by someone other than the author.
- **V1.0 tag** on `main` after all sign-off criteria are ticked.

**Deliverables:**
- Signed wheel on PyPI; signed multi-arch images on a container registry
- SBOMs published alongside each release
- Complete `docs/` set
- CI green on every commit
- V1.0 tag on `main`

**Test bar reached:** C.

---

## V1.0 Sign-Off Criteria

V1.0 ships when **all** of the following hold:

- [ ] M1, M2, M3, M4, M5, M6, M7 all ✅
- [ ] Test suite runs green on a clean clone: `mise run test`
- [ ] Coverage on `src/fixwire/core/` and `src/fixwire/transport/` ≥ 95%
- [ ] No open entries in `docs/KNOWN_ISSUES.md` under "Bugs" category
- [ ] `docs/FIX44_CONFORMANCE.md` exists and every requirement row maps to a passing test name
- [ ] All four tools (`ruff`, `mypy`, `pytest`, `uv-audit`) clean in CI
- [ ] Signed wheel on PyPI; signed image on registry
- [ ] Manual run-through of `INSTALL.md`, `OPERATIONS.md` on a fresh machine by someone other than the author

---

## Beyond V1.0 — Roadmap (Not in V1.0 scope)

These are deferred from V1.0 because they are **deployment concerns** that a banking customer typically owns themselves. The engine must install into whatever infrastructure they have; it doesn't ship that infrastructure.

> Adding any item here to V1.0 requires a PR that updates this file and the V1.0 Sign-Off Criteria.

### Container orchestration
- **Helm chart** for Kubernetes deployment — generated from a chart that mirrors the Docker Compose layout.
- **Kubernetes manifests** (Deployment, Service, ConfigMap, Secret, NetworkPolicy) for the most common cloud platforms.
- **Pod-level hardening** — `securityContext`, `readOnlyRootFilesystem`, `runAsNonRoot`, `seccompProfile`, `capabilities.drop ALL`.

### Infrastructure as Code
- **Terraform / OpenTofu modules** for AWS, GCP, Azure — VPC, subnets, security groups, IAM, secrets manager wiring.
- **Ansible playbooks** for OS-level provisioning and configuration management.
- **Pulumi** TypeScript/Python module as an alternative to Terraform.
- **Multi-environment layouts** (dev/staging/prod) with parameterized modules and per-env backend configs.

### Observability stack
- **Prometheus exporter** built into the engine for: open sessions, message rate by type, sequence gaps detected, heartbeat latencies, queue depths.
- **Grafana dashboards** — one per major concern (sessions, throughput, errors, latency).
- **Alert rules** — pre-built alerting on: heartbeat violation, sequence gap > N, ERROR status duration > X seconds, ERROR rate / time, reconnect storm.
- **Structured logging sinks** — log routing adapters for common backends (Loki, Elasticsearch, Datadog).
- **OpenTelemetry traces** with FIX message correlation IDs; trace context propagated across the wire.
- **Runbook coverage** — every alert rule has a runbook section in `docs/RUNBOOKS.md`.

### Geo & resilience
- **Active-active failover** across data centers.
- **Session persistence across failover** — replays cleanly to the new peer using M5's outbox.
- **Dead-letter / quarantine queue** for messages that cannot be delivered or processed.

### Ecosystem
- **FIX 5.0+** support (spec compliance tracked separately).
- **FastAPI gateway layer** (already mentioned in `SPEC.md`); formalized as its own milestone once M5 ships.
- **Market / matching engine** (referenced in `KNOWN_ISSUES.md`) — separate product track; not a FIXwire dependency.

---

## Related Documents

- **`SPEC.md`** — protocol specification and architecture principles. Source of truth for **what** the engine does.
- **`TODO.md`** — short-term backlog for the current sprint. Source of truth for **immediate** work.
- **`docs/KNOWN_ISSUES.md`** — confirmed bugs and known debt. Source of truth for **what's broken or shaky**.
- **`docs/design/session-transport.md`** (planned) — architecture decision record for the M1 refactor. Source of truth for **why** the engine is shaped the way it is.
- **`docs/FIX44_CONFORMANCE.md`** (planned) — M6 deliverable. Source of truth for **what spec we conform to and how it's proven**.

---

## Update Discipline

This file is not aspirational — it's a **contract**. Changes are made by PR, not by edit. Every PR that closes a milestone or moves an item on this file must update it in the same PR. The diff on `MILESTONES.md` is part of the code review.
