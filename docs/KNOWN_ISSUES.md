# Known Issues & Improvements

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
- [ ] Send ResendRequest (MsgType=2) for missed messages
- [ ] Handle GapFill (SequenceReset-GapFill)
- [ ] Sequence number synchronization

### Sequence Numbers
- [ ] Gap detection and recovery
- [ ] ResendRequest handling
- [ ] SequenceReset handling

## Session

### Connection Management
- [ ] Reconnection with exponential backoff
- [ ] Heartbeat timeout detection
- [ ] Logon timeout handling
- [ ] Logout timeout handling

### Recovery
- [ ] ResendRequest for missed messages
- [ ] GapFill handling
- [ ] Sequence number synchronization

## Transport

### WebSocket
- [ ] Handle partial frame delivery
- [ ] Handle binary vs text frames
- [ ] Connection keep-alive

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
