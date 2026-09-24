# FIXwire

FIX 4.4 Protocol Engine in Python

## Quick Start

```bash
# Install mise
curl https://mise.run | sh

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup project
mise install
uv venv
uv pip install -e ".[dev]"

# Run tests
mise run test

# Run with coverage
mise run test-coverage
```

## Development

### Test-Driven Development (TDD)

We follow TDD to fail early and design better APIs:

1. **Red** — Write a failing test
2. **Green** — Write minimal code to pass
3. **Refactor** — Improve while keeping tests green

**When writing code:**
- New features: Write tests first
- Bug fixes: Write failing test first, then fix
- See [SPEC.md - Testing Methodology](SPEC.md#testing-methodology)

### Available Commands

```bash
mise run test          # All tests
mise run test-unit     # Unit tests only
mise run test-core     # Core engine tests
mise run test-coverage # Tests with coverage
mise run lint          # Lint with ruff
mise run format        # Format code
mise run typecheck     # Type check with mypy
```

### Project Structure

```
fixwire/
├── src/fixwire/           # Source code
│   ├── core/              # FIX engine (parser, serializer, session)
│   ├── transport/         # WebSocket server/client
│   ├── client/            # Client component
│   ├── market/            # Market component
│   ├── persistence/       # Database models
│   └── api/               # REST API
├── tests/                 # Test suite
│   ├── unit/              # Unit tests
│   ├── integration/       # Integration tests
│   └── load/              # Load tests
└── docs/                  # Documentation
```

## Architecture

See [SPEC.md](SPEC.md) for full architecture details.

### Core Components

- **FIXMessage** — Tag-value container for FIX messages
- **FIXParser** — Deserialize raw bytes to FIXMessage
- **FIXSerializer** — Serialize FIXMessage to bytes
- **FIXSession** — Session lifecycle management

## Testing

### Unit Tests

Test components in isolation:

```bash
mise run test-unit
```

### Test Coverage

```bash
mise run test-coverage
```

Target: 90%+ coverage

### Writing Tests

Follow TDD approach:
1. Write failing test
2. Implement minimal code to pass
3. Refactor while keeping tests green

See [SPEC.md - Testing Methodology](SPEC.md#testing-methodology)

## Known Issues

See [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) for:
- Parser edge cases
- Session recovery improvements
- Future enhancements

## License

MIT
