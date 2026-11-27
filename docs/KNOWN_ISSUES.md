# Known Issues & Improvements

> **Methodology:** We follow TDD (Test-Driven Development). Write tests first, then implement.
> See [SPEC.md - Testing Methodology](../SPEC.md#testing-methodology) for details.

## Parser

### Malformed Message Handling
- [ ] Messages with checksum field != 3 digits (e.g. `10=99\x01`, `10=9999\x01`)
- [ ] Messages with non-numeric checksum (e.g. `10=abc\x01`)
- [ ] Messages with missing SOH after checksum
- [ ] Messages with extra bytes between fields
- [ ] Messages with encoding errors (non-ASCII bytes)
- [ ] Messages with zero-length fields (empty tag=value)
- [ ] BodyLength mismatch (declared vs actual)
- [ ] Messages with `=` in tag value (rare but possible)
- [ ] Messages with leading/trailing whitespace in values
- [ ] Messages with duplicate tags

### Checksum
- [x] Validate checksum format (10=XXX<SOH>)
- [x] Validate checksum value matches calculated
- [ ] Handle truncated messages (incomplete checksum)
- [ ] Handle corrupted `10=` prefix
- [ ] Handle checksum > 255 (invalid range)

### Session Recovery
- [ ] Send Reject (MsgType=3) for invalid messages
- [x] Send ResendRequest (MsgType=2) for missed messages
- [x] Handle GapFill (SequenceReset-GapFill)
- [ ] Sequence number synchronization

### Sequence Numbers
- [ ] Gap detection and recovery
- [ ] ResendRequest handling
- [x] SequenceReset handling

## Session

### Connection Management
- [ ] Reconnection with exponential backoff
- [x] Heartbeat timeout detection
- [x] Logon timeout handling
- [x] Logout timeout handling

### Recovery
- [ ] ResendRequest for missed messages
- [ ] GapFill handling
- [ ] Sequence number synchronization
- [ ] Reconnect baseline silently skips unreceived messages

  On reconnect the peer's Logon MsgSeqNum becomes our expected incoming
  number (`_handle_logon`), so messages we never received — anywhere from
  the last one we processed up to that number — are never requested. FIX
  expects the receiver to compare and send a ResendRequest for the gap.
  Belongs with the M5 resend path, where requesting and replaying exist.

### Outbound
- [ ] Losing the in-flight message on send failure

  `_writer_loop` does `queue.get()` → `serialize()` → `transport.send()`.
  If `send()` raises, the message is already out of the queue and is
  dropped: its sequence number is consumed, nothing is recorded, and it is
  not requeued. The peer sees a gap and asks for it; with no store we
  answer with a GapFill, telling the peer the message never existed.

  Requeueing it is not a fix — if the send actually landed, requeueing
  sends it twice. Resolve together with the M3 outbox: persist before the
  wire, replay after logon, serve ResendRequest from the store.

## Transport

### WebSocket
- [ ] Handle partial frame delivery
- [x] Handle binary vs text frames
- [x] Connection keep-alive

### Error Handling
- [ ] Network interruption recovery
- [ ] DNS resolution failures
- [ ] TLS handshake errors

## Market

### Matching Engine
- [ ] Price-time priority ordering
- [ ] Partial fill handling
- [ ] Order cancellation
- [ ] Order replacement

### Execution Reports
- [ ] Generate unique ExecID
- [ ] Track cumulative quantities
- [ ] Calculate average price

## Persistence

### Database
- [ ] Connection pooling
- [ ] Transaction isolation
- [ ] Deadlock detection
- [ ] Connection recovery

### Caching
- [ ] Cache invalidation
- [ ] Cache warming
- [ ] Distributed caching

## Security

### Authentication
- [ ] FIX session authentication
- [ ] API key management
- [ ] Token rotation

### Authorization
- [ ] Role-based access control
- [ ] Permission management
- [ ] Audit logging

## Testing

### Coverage
- [ ] Unit test coverage > 90%
- [ ] Integration test coverage
- [ ] Load test scenarios
- [ ] Chaos test scenarios

### Quality
- [ ] Static analysis (mypy, ruff)
- [ ] Code review checklist
- [ ] Documentation coverage

## Performance

### Optimization
- [ ] Message parsing benchmarks
- [ ] Connection throughput tests
- [ ] Memory usage profiling
- [ ] CPU profiling

### Scalability
- [ ] Horizontal scaling
- [ ] Load balancing
- [ ] Rate limiting

## Documentation

### API
- [ ] REST API documentation
- [ ] WebSocket protocol documentation
- [ ] FIX protocol mapping
- [ ] Configuration reference

### Operations
- [ ] Deployment guide
- [ ] Monitoring guide
- [ ] Troubleshooting guide
- [ ] Performance tuning guide
