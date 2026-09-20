# FIXwire - FIX Protocol Engine Specification

> A robust, async Python FIX protocol engine for testing and production use

## Quick Summary

| Aspect | Decision |
|--------|----------|
| **FIX Version** | 4.4 (industry standard, production-ready) |
| **Transport** | WebSocket (easy debugging, Docker-friendly) |
| **Language** | Python 3.11+ with async/await |
| **Package Manager** | **uv** (fast, modern) |
| **Tool Manager** | **mise** (Python, Node, etc.) |
| **Framework** | FastAPI (REST API) + WebSockets |
| **Database** | PostgreSQL (async via asyncpg) |
| **Cache** | Redis (session state, pub/sub) |
| **Validation** | Pydantic v2 |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Logging** | structlog (JSON structured) |
| **Metrics** | Prometheus |
| **Testing** | pytest + 90%+ coverage target |
| **Deployment** | Docker Compose |
| **Architecture** | Clean Architecture / Hexagonal |

---

## Overview

FIXwire is a modern, async Python implementation of the FIX (Financial Information eXchange) protocol engine designed for:

- **Test/Mock System**: Simulate FIX providers and clients for development and testing
- **Production Ready**: Robust enough for production use as a FIX gateway
- **Distributed**: Multi-component architecture with Docker orchestration
- **Observable**: Full message logging and audit trail

## Architecture

### Production-Grade Design Principles

**Clean Architecture (Hexagonal):**
- Domain logic is independent of frameworks
- External dependencies are behind ports/adapters
- Easy to test, easy to swap implementations
- Business rules don't depend on UI, database, or external services

**Domain-Driven Design (DDD):**
- Clear bounded contexts (FIX Protocol, Order Management, Market Data)
- Rich domain models with business logic
- Domain events for loose coupling
- Value objects for immutable concepts

**Resilience Patterns:**
- Circuit breakers for external dependencies
- Retry with exponential backoff
- Bulkhead isolation
- Timeout management
- Graceful degradation

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                    Clean Architecture Layers                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Presentation Layer                        ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        ││
│  │  │ REST API    │  │ WebSocket   │  │ CLI         │        ││
│  │  │ (FastAPI)   │  │ Server      │  │             │        ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘        ││
│  └─────────────────────────────────────────────────────────────┘│
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Application Layer                        ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        ││
│  │  │ Order       │  │ Market Data │  │ Trade       │        ││
│  │  │ Service     │  │ Service     │  │ Service     │        ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘        ││
│  └─────────────────────────────────────────────────────────────┘│
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      Domain Layer                           ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        ││
│  │  │ Order       │  │ Market Data │  │ Trade       │        ││
│  │  │ Aggregate   │  │ Aggregate   │  │ Aggregate   │        ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘        ││
│  │  ┌─────────────────────────────────────────────────────┐   ││
│  │  │              Domain Events                          │   ││
│  │  │  OrderSubmitted, OrderFilled, TradeCaptured         │   ││
│  │  └─────────────────────────────────────────────────────┘   ││
│  └─────────────────────────────────────────────────────────────┘│
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   Infrastructure Layer                      ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        ││
│  │  │ PostgreSQL  │  │ Redis       │  │ FIX Engine  │        ││
│  │  │ Repository  │  │ Cache       │  │ Adapter     │        ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘        ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       Docker/Kubernetes                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐         ┌─────────────────┐               │
│  │   FIX Client    │◄───────►│   FIX Market    │               │
│  │   Service       │  WSS    │   Service       │               │
│  └────────┬────────┘         └────────┬────────┘               │
│           │                           │                          │
│  ┌────────▼────────┐         ┌────────▼────────┐               │
│  │  Client Engine  │         │  Market Engine  │               │
│  │  (FIXT 1.1 +    │         │  (FIXT 1.1 +    │               │
│  │   FIX 5.0)      │         │   FIX 5.0)      │               │
│  └────────┬────────┘         └────────┬────────┘               │
│           │                           │                          │
│           ▼                           ▼                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Message Bus (Redis Pub/Sub)              ││
│  └─────────────────────────────────────────────────────────────┘│
│           │                           │                          │
│           ▼                           ▼                          │
│  ┌─────────────────┐         ┌─────────────────┐               │
│  │   PostgreSQL    │         │     Redis       │               │
│  │   (Persistence) │         │   (Cache/State) │               │
│  └─────────────────┘         └─────────────────┘               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

#### 1. FIX Core Engine (`fixwire/core/`)

**Purpose**: Protocol parsing, message construction, session management

**Key Classes**:
- `FIXMessage`: Message container with tag-value pairs
- `FIXParser`: Deserialize FIX byte stream into FIXMessage objects
- `FIXSerializer`: Serialize FIXMessage objects to byte stream
- `FIXSession`: Session state machine (logon, heartbeat, logout)
- `FIXSequenceManager`: Sequence number tracking and recovery

**Message Flow**:
```
Outbound: Application → FIXMessage → Serializer → Transport
Inbound: Transport → Parser → FIXMessage → Application
```

#### 2. Transport Layer (`fixwire/transport/`)

**Purpose**: WebSocket connection management, heartbeats, reconnection

**Key Classes**:
- `WebSocketServer`: Accepts client connections
- `WebSocketClient`: Connects to market servers
- `ConnectionManager`: Track active connections, health checks
- `HeartbeatMonitor`: Detect stale connections

**Protocol**:
- Binary WebSocket frames for FIX messages
- JSON control messages for session management
- Automatic reconnection with exponential backoff

#### 3. Client Component (`fixwire/client/`)

**Purpose**: Order submission, execution tracking, market data

**Key Classes**:
- `FIXClient`: High-level client API
- `OrderManager`: Submit, modify, cancel orders
- `ExecutionHandler`: Process execution reports
- `MarketDataHandler`: Subscribe to market data feeds

**Supported Message Types** (FIX 4.2):
- `D` - New Order Single
- `F` - Order Cancel Request
- `G` - Order Cancel/Replace Request
- `8` - Execution Report (inbound)
- `W` - Market Data Snapshot (inbound)

#### 4. Market Component (`fixwire/market/`)

**Purpose**: Order matching, execution generation, market data

**Key Classes**:
- `FIXMarket`: Market server orchestrator
- `MatchingEngine`: Price-time priority order matching
- `ExecutionEngine`: Generate execution reports
- `MarketDataEngine`: Aggregate and distribute market data

**Matching Logic**:
- Price-time priority (FIFO at same price)
- Support for Limit orders initially
- IOC/FOK/GTC time-in-force support

#### 5. Persistence Layer (`fixwire/persistence/`)

**Purpose**: Durable storage for orders, executions, audit

**Key Classes**:
- `OrderRepository`: CRUD for orders
- `ExecutionRepository`: Store execution reports
- `MessageLogRepository`: FIX message audit trail
- `SessionRepository`: Session state persistence

**Database Schema**:

```sql
-- Orders table
CREATE TABLE orders (
    id UUID PRIMARY KEY,
    cl_ord_id VARCHAR(50) UNIQUE NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side CHAR(1) NOT NULL,  -- '1'=Buy, '2'=Sell
    order_qty DECIMAL(18,8) NOT NULL,
    price DECIMAL(18,8),
    ord_type CHAR(1) NOT NULL,  -- '2'=Limit, '1'=Market
    time_in_force CHAR(1) DEFAULT '0',  -- '0'=Day
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Executions table
CREATE TABLE executions (
    id UUID PRIMARY KEY,
    order_id UUID REFERENCES orders(id),
    exec_id VARCHAR(50) UNIQUE NOT NULL,
    exec_type CHAR(1) NOT NULL,  -- '0'=New, '1'=Partial, '2'=Fill, '4'=Cancelled
    ord_status CHAR(1) NOT NULL,
    last_qty DECIMAL(18,8),
    last_px DECIMAL(18,8),
    cum_qty DECIMAL(18,8),
    avg_px DECIMAL(18,8),
    created_at TIMESTAMP NOT NULL
);

-- Message log (audit trail)
CREATE TABLE message_log (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    direction CHAR(1) NOT NULL,  -- 'I'=Inbound, 'O'=Outbound
    msg_type VARCHAR(10) NOT NULL,
    sequence_num INTEGER NOT NULL,
    raw_message TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);
```

## FIX Protocol Version

### Selected: FIX 4.4

**Why FIX 4.4:**
1. **Industry Standard**: 80%+ of trading systems use 4.4
2. **Battle-Tested**: Production-ready since 2003
3. **Simpler Architecture**: Integrated session layer (no FIXT 1.1 complexity)
4. **Well-Documented**: Tons of examples, community support
5. **Immediate Value**: Works with most existing systems

**Future Path:**
- Phase 2: Add FIX 5.0 support (when needed)
- Can run both 4.4 and 5.0 side-by-side

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FIX 4.4 Architecture                  │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────────────────────────────────────────┐│
│  │              FIX 4.4 Protocol Layer                 ││
│  │  ┌─────────────────────────────────────────────────┐││
│  │  │           Session Management                   │││
│  │  │  Logon, Heartbeat, Sequence, Resend            │││
│  │  └─────────────────────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────┐││
│  │  │           Application Layer                    │││
│  │  │  Orders, Executions, Market Data               │││
│  │  └─────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────┘│
│                          ▼                               │
│  ┌─────────────────────────────────────────────────────┐│
│  │              Transport Layer (WebSocket)            ││
│  └─────────────────────────────────────────────────────┘│
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Key Features

**FIX 4.4 Session Layer:**
- Session management (logon/logout)
- Heartbeat negotiation and monitoring
- Sequence number management
- Message resend logic
- Gap fill handling

**FIX 4.4 Application Layer:**
- Order management (new, cancel, replace, status)
- Execution reports
- Market data (snapshot + incremental)
- Trade capture
- Position management
- Allocation messages

### Supported Message Types

**Session Messages:**
- Logon (A) - Establish session
- Logout (5) - Terminate session
- Heartbeat (0) - Keep-alive
- TestRequest (1) - Verify connection
- ResendRequest (2) - Request message replay
- SequenceReset (4) - Reset sequence numbers
- Reject (3) - Message rejection

**Application Messages:**
- **Orders**: NewOrderSingle (D), OrderCancelRequest (F), OrderCancelReplaceRequest (G)
- **Execution**: ExecutionReport (8), OrderCancelReject (9)
- **Trade Capture**: TradeCaptureReportRequest (AD), TradeCaptureReport (AE)
- **Market Data**: MarketDataRequest (V), MarketDataSnapshotFullRefresh (W), MarketDataIncrementalRefresh (X)
- **Position**: RequestForPositions (AN), PositionReport (AP)
- **Allocation**: AllocationInstruction (J), AllocationReport (P)

### Implementation Strategy

1. **Phase 1**: Core engine (parser, serializer, session)
2. **Phase 2**: Transport layer (WebSocket)
3. **Phase 3**: Client & Market components
4. **Phase 4**: Persistence & API
5. **Phase 5**: Production features
6. **Future**: Add FIX 5.0 support

---

## Technology Stack

### Development Environment

**mise (formerly rtx)** for tool version management:
```bash
# Install mise
curl https://mise.run | sh

# Activate mise
eval "$(mise activate bash)"

# Install Python and other tools
mise install

# This reads .mise.toml in the project root
```

**.mise.toml** (project root):
```toml
[tools]
python = "3.11"
node = "20"  # If needed for frontend/dashboard

[env]
.".env" = true  # Load .env file
```

**uv** for Python package management:
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment
uv venv

# Install dependencies
uv pip install -e ".[dev]"

# Or sync from lockfile
uv sync

# Add new dependency
uv add fastapi

# Add dev dependency
uv add --dev pytest
```

### Project Structure

```
fixwire/
├── pyproject.toml
├── uv.lock
├── .mise.toml
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── src/
│   └── fixwire/
│       ├── __init__.py
│       │
│       ├── core/                        # FIX Core Engine
│       │   ├── __init__.py
│       │   ├── message.py              # FIXMessage class
│       │   ├── parser.py               # FIX parser
│       │   ├── serializer.py           # FIX serializer
│       │   ├── tags.py                 # FIX 4.4 tag definitions
│       │   ├── session.py              # Session management
│       │   ├── sequence.py             # Sequence numbers
│       │   └── heartbeat.py            # Heartbeat logic
│       │
│       ├── transport/                   # Transport Layer
│       │   ├── __init__.py
│       │   ├── websocket.py            # WebSocket server/client
│       │   └── connection.py           # Connection management
│       │
│       ├── client/                      # Client Component
│       │   ├── __init__.py
│       │   ├── order_manager.py        # Order submission
│       │   └── execution_handler.py    # Execution reports
│       │
│       ├── market/                      # Market Component
│       │   ├── __init__.py
│       │   ├── matching.py             # Matching engine
│       │   └── execution.py            # Execution engine
│       │
│       ├── persistence/                 # Persistence Layer
│       │   ├── __init__.py
│       │   ├── models.py               # SQLAlchemy models
│       │   ├── repositories.py         # Repository implementations
│       │   ├── database.py             # DB connection
│       │   └── migrations/             # Alembic migrations
│       │
│       ├── api/                         # REST API
│       │   ├── __init__.py
│       │   ├── app.py                  # FastAPI app
│       │   ├── routes/
│       │   │   ├── __init__.py
│       │   │   ├── orders.py
│       │   │   └── health.py
│       │   └── dependencies.py
│       │
│       └── config.py                    # Settings
│
├── tests/
│   ├── conftest.py
│   ├── unit/                           # Unit tests
│   │   ├── core/                       # Test FIX core
│   │   ├── client/                     # Test client
│   │   ├── market/                     # Test market
│   │   └── persistence/                # Test persistence
│   ├── integration/                    # Integration tests
│   │   ├── test_order_lifecycle.py
│   │   └── test_fix_session.py
│   └── load/                           # Load tests
│       └── test_concurrent.py
│
├── docker/
│   ├── Dockerfile.client
│   └── Dockerfile.market
│
└── docs/
    ├── architecture.md
    └── fix-protocol.md
```

### Core Dependencies

```toml
[project]
name = "fixwire"
version = "0.1.0"
description = "FIX Protocol Engine"
requires-python = ">=3.11"

dependencies = [
    # Async Framework
    "uvicorn[standard]>=0.24.0",
    "fastapi>=0.104.0",
    "websockets>=12.0",
    
    # Data Validation
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    
    # Database
    "sqlalchemy[asyncio]>=2.0.23",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    
    # Caching & Messaging
    "redis[hiredis]>=5.0.0",
    
    # Utilities
    "structlog>=23.2.0",
    "python-dotenv>=1.0.0",
    "tenacity>=8.2.0",
    "httpx>=0.25.0",
]

[project.optional-dependencies]
dev = [
    # Testing
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "pytest-xdist>=3.5.0",  # Parallel tests
    
    # Code Quality
    "ruff>=0.1.0",
    "mypy>=1.7.0",
    
    # Database Testing
    "aiosqlite>=0.19.0",  # SQLite for tests
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/fixwire"]

[tool.ruff]
target-version = "py311"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B"]

[tool.mypy]
python_version = "3.11"
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### Infrastructure

- **uv**: Fast Python package manager (replaces pip, poetry, pipenv)
- **mise**: Tool version manager (Python, Node, etc.)
- **Python 3.11+**: Full async/await support
- **FastAPI**: REST API for management and monitoring
- **WebSockets**: FIX message transport
- **PostgreSQL**: Durable persistence
- **Redis**: Session state, caching, pub/sub for distributed components
- **Docker**: Containerized deployment
- **Docker Compose**: Local development and testing

## Message Protocol

### FIX Message Format

```
8=FIX.4.2|9=176|35=D|49=CLIENT01|56=MARKET01|34=2|52=20231220-14:30:00.000|11=ORD001|21=1|55=AAPL|54=1|38=100|40=2|44=150.50|59=0|10=128|
```

### Tag Definitions

| Tag | Name | Description |
|-----|------|-------------|
| 8 | BeginString | FIX version (FIX.4.2) |
| 9 | BodyLength | Message body length |
| 35 | MsgType | Message type |
| 49 | SenderCompID | Sender identifier |
| 56 | TargetCompID | Target identifier |
| 34 | MsgSeqNum | Sequence number |
| 52 | SendingTime | Timestamp |
| 10 | CheckSum | Message checksum |

### Supported Message Types

#### Client → Market

| MsgType | Name | Description |
|---------|------|-------------|
| `A` | Logon | Establish session |
| `D` | NewOrderSingle | Submit new order |
| `F` | OrderCancelRequest | Cancel existing order |
| `G` | OrderCancelReplaceRequest | Modify existing order |
| `0` | Heartbeat | Keep-alive |
| `1` | TestRequest | Verify connection |
| `5` | Logout | Terminate session |

#### Market → Client

| MsgType | Name | Description |
|---------|------|-------------|
| `A` | Logon | Acknowledge session |
| `8` | ExecutionReport | Order status update |
| `W` | MarketDataSnapshot | Market data |
| `0` | Heartbeat | Keep-alive |
| `1` | TestRequest | Verify connection |
| `5` | Logout | Terminate session |

## Session Management

### Connection Flow

```
Client                              Market
  │                                    │
  │──── WebSocket Connect ────────────►│
  │                                    │
  │──── Logon (A) ────────────────────►│
  │                                    │
  │◄─── Logon Ack (A) ────────────────│
  │                                    │
  │══════ Session Established ════════│
  │                                    │
  │──── Heartbeat (0) ────────────────►│
  │                                    │
  │◄─── Heartbeat (0) ────────────────│
  │                                    │
  │──── Order (D) ────────────────────►│
  │                                    │
  │◄─── Execution Report (8) ─────────│
  │                                    │
  │──── Logout (5) ───────────────────►│
  │                                    │
  │◄─── Logout Ack (5) ───────────────│
  │                                    │
  │──── WebSocket Close ──────────────►│
  │                                    │
```

### Heartbeat Management

- **Default Interval**: 30 seconds
- **Timeout Detection**: 2x heartbeat interval (60 seconds)
- **Action on Timeout**: Disconnect and attempt reconnect

### Sequence Number Management

- **Initial Sequence**: 1
- **Increment**: +1 per message
- **Gap Detection**: Request ResendRequest (2) on gap
- **Recovery**: Replay missed messages

## Deployment

### Docker Compose Structure

```yaml
version: '3.8'

services:
  # Infrastructure
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: fixwire
      POSTGRES_USER: fixwire
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # Application Services
  market:
    build:
      context: .
      dockerfile: docker/Dockerfile.market
    environment:
      DATABASE_URL: postgresql+asyncpg://fixwire:${DB_PASSWORD}@postgres:5432/fixwire
      REDIS_URL: redis://redis:6379/0
      MARKET_PORT: 8001
    ports:
      - "8001:8001"
    depends_on:
      - postgres
      - redis

  client:
    build:
      context: .
      dockerfile: docker/Dockerfile.client
    environment:
      DATABASE_URL: postgresql+asyncpg://fixwire:${DB_PASSWORD}@postgres:5432/fixwire
      REDIS_URL: redis://redis:6379/0
      MARKET_WS_URL: ws://market:8001/fix
    depends_on:
      - postgres
      - redis
      - market

volumes:
  postgres_data:
```

### Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://fixwire:secret@localhost:5432/fixwire

# Redis
REDIS_URL=redis://localhost:6379/0

# Market Service
MARKET_HOST=0.0.0.0
MARKET_PORT=8001
MARKET_WS_PATH=/fix

# Client Service
CLIENT_ID=CLIENT01
MARKET_WS_URL=ws://localhost:8001/fix
HEARTBEAT_INTERVAL=30

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## API Endpoints

### Management API (FastAPI)

#### Market Service

```
GET  /health              - Health check
GET  /status              - Market status
GET  /sessions            - Active sessions
GET  /orders              - List orders
POST /orders              - Submit order (REST → FIX)
GET  /executions          - List executions
GET  /market-data/{symbol} - Get market data
```

#### Client Service

```
GET  /health              - Health check
GET  /status              - Client status
GET  /orders              - List client orders
POST /orders              - Submit order
DELETE /orders/{id}       - Cancel order
PUT  /orders/{id}         - Modify order
```

## Observability

### Logging

**Structured Logging with structlog:**
```python
import structlog

logger = structlog.get_logger()

# Context-rich logging
logger.info(
    "order.received",
    client_id="CLIENT01",
    cl_ord_id="ORD-001",
    symbol="AAPL",
    side="BUY",
    qty=100,
    price=150.50
)
```

**Log Levels:**
- `DEBUG`: Raw FIX messages, tag-level parsing
- `INFO`: Session events, order lifecycle, executions
- `WARNING**: Rejected orders, sequence gaps, reconnect attempts
- `ERROR`: Connection failures, parsing errors, system errors

**Log Output:**
- JSON format for production (structured, searchable)
- Console format for development (human-readable)
- All logs include: timestamp, component, session_id, correlation_id

### Metrics (Prometheus)

**Core Metrics:**
```
# Session metrics
fix_sessions_active gauge "Active FIX sessions"
fix_session_logon_total counter "Total logons"
fix_session_logout_total counter "Total logouts"

# Message metrics
fix_messages_sent_total counter "Messages sent" labels=[msg_type]
fix_messages_received_total counter "Messages received" labels=[msg_type]
fix_messages_rejected_total counter "Messages rejected" labels=[reason]

# Order metrics
fix_orders_new_total counter "New orders"
fix_orders_filled_total counter "Filled orders"
fix_orders_cancelled_total counter "Cancelled orders"
fix_orders_rejected_total counter "Rejected orders"
fix_order_latency_seconds histogram "Order processing latency"

# System metrics
fix_heartbeat_timeout_total counter "Heartbeat timeouts"
fix_reconnect_total counter "Reconnection attempts"
```

### Health Checks

**Endpoints:**
```
GET /health/live    - Liveness probe (is process running?)
GET /health/ready   - Readiness probe (can serve traffic?)
```

**Readiness Criteria:**
- Database connection active
- Redis connection active
- WebSocket server listening
- No critical errors in last 60 seconds

### Distributed Tracing (Future)

- OpenTelemetry integration
- Trace order lifecycle across components
- Correlation IDs for request tracking

---

## Development Roadmap

### Phase 1: Core Engine (Weeks 1-3)

**Goal**: Working FIX parser and session management

- [ ] Project setup (uv, mise, pyproject.toml)
- [ ] FIX 4.4 message parser/serializer
- [ ] FIXMessage class with tag support
- [ ] Checksum and body length validation
- [ ] Session management (logon/logout)
- [ ] Heartbeat mechanism
- [ ] Sequence number management
- [ ] Unit tests (90%+ coverage)

**Deliverable**: Can parse and generate FIX messages, manage sessions

### Phase 2: Transport Layer (Week 4)

**Goal**: WebSocket communication

- [ ] WebSocket server implementation
- [ ] WebSocket client implementation
- [ ] Connection management
- [ ] Message framing (FIX over WebSocket)
- [ ] Basic error handling
- [ ] Unit + integration tests

**Deliverable**: Two components can connect and exchange FIX messages

### Phase 3: Client & Market (Weeks 5-7)

**Goal**: Working order flow

- [ ] Client order management (submit, cancel, replace)
- [ ] Market matching engine (price-time priority)
- [ ] Execution report generation
- [ ] End-to-end order lifecycle
- [ ] Integration tests for full flow

**Deliverable**: Client can submit orders, market can match and fill them

### Phase 4: Persistence & API (Weeks 8-9)

**Goal**: Data persistence and management API

- [ ] SQLAlchemy async models (Order, Execution, MessageLog)
- [ ] Repository pattern implementation
- [ ] Message logging (audit trail)
- [ ] Session state persistence
- [ ] FastAPI REST API (health, orders, executions)
- [ ] Repository unit tests

**Deliverable**: Orders persisted, REST API for management

### Phase 5: Production Features (Weeks 10-11)

**Goal**: Production-ready features

- [ ] Structured logging (structlog)
- [ ] Health check endpoints
- [ ] Configuration management (pydantic-settings)
- [ ] Docker + Docker Compose
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Basic metrics (Prometheus)

**Deliverable**: Dockerized, deployable, observable system

### Phase 6: Hardening (Week 12)

**Goal**: Battle-tested reliability

- [ ] Graceful shutdown
- [ ] Reconnection with exponential backoff
- [ ] Sequence recovery (ResendRequest)
- [ ] Rate limiting
- [ ] Load testing (100+ concurrent)
- [ ] Documentation

**Deliverable**: Production-ready, tested, documented system

### Phase 7: Future Enhancements (Optional)

**Goal**: Extended capabilities

- [ ] FIX 5.0 support (add alongside 4.4)
- [ ] Market data feed (snapshot + incremental)
- [ ] Trade capture messages
- [ ] Position management
- [ ] Multi-venue routing
- [ ] Advanced matching algorithms

## Core Patterns

### 1. Retry with Backoff

```python
import asyncio
import random

async def reconnect_with_backoff(
    connect_func,
    max_retries: int = 10,
    base_delay: float = 1.0,
    max_delay: float = 60.0
):
    """Reconnect with exponential backoff and jitter."""
    for attempt in range(max_retries):
        try:
            return await connect_func()
        except ConnectionError:
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            total_delay = delay + jitter
            
            logger.warning(
                "reconnect.attempt",
                attempt=attempt + 1,
                delay=total_delay
            )
            await asyncio.sleep(total_delay)
    
    raise ConnectionError("Max reconnection attempts exceeded")
```

### 2. Graceful Shutdown

```python
import signal
import asyncio

async def graceful_shutdown(signals: set[int], loop):
    """Handle graceful shutdown signals."""
    logger.info("shutdown.initiated")
    
    # 1. Stop accepting new connections
    await server.stop_accepting()
    
    # 2. Wait for in-flight requests (with timeout)
    await asyncio.wait_for(
        wait_for_inflight_requests(),
        timeout=30.0
    )
    
    # 3. Close all connections gracefully
    await connection_manager.close_all()
    
    # 4. Close database connections
    await engine.dispose()
    
    logger.info("shutdown.complete")
    loop.stop()
```

### 3. Rate Limiting

```python
from datetime import datetime

class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, rate: float, burst: int):
        self.rate = rate  # Messages per second
        self.burst = burst  # Max burst size
        self.tokens = burst
        self.last_update = datetime.utcnow()
    
    async def acquire(self) -> bool:
        """Acquire a token, returns False if rate limited."""
        now = datetime.utcnow()
        time_passed = (now - self.last_update).total_seconds()
        self.tokens = min(
            self.burst,
            self.tokens + time_passed * self.rate
        )
        self.last_update = now
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
```

### 4. Health Checks

```python
from fastapi import FastAPI
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    uptime: float

@app.get("/health/live", response_model=HealthResponse)
async def liveness():
    """Liveness probe: Is process alive?"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        uptime=get_uptime()
    )

@app.get("/health/ready", response_model=HealthResponse)
async def readiness():
    """Readiness probe: Can serve traffic?"""
    db_ok = await check_database()
    redis_ok = await check_redis()
    
    all_healthy = db_ok and redis_ok
    
    return HealthResponse(
        status="healthy" if all_healthy else "unhealthy",
        timestamp=datetime.utcnow(),
        uptime=get_uptime()
    )
```

### 5. Configuration Management

```python
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """Application settings with validation."""
    
    # Database
    database_url: str = Field(..., env="DATABASE_URL")
    
    # Redis
    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    
    # FIX Protocol
    fix_version: str = Field("FIX.4.4", env="FIX_VERSION")
    fix_sender_comp_id: str = Field(..., env="FIX_SENDER_COMP_ID")
    fix_target_comp_id: str = Field(..., env="FIX_TARGET_COMP_ID")
    fix_heartbeat_interval: int = Field(30, env="FIX_HEARTBEAT_INTERVAL")
    
    # Server
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(8000, env="PORT")
    
    # Logging
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_format: str = Field("json", env="LOG_FORMAT")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
```

## Error Handling

### Error Categories

| Category | Examples | Action |
|----------|----------|--------|
| **Connection** | WebSocket disconnect, timeout | Reconnect with backoff |
| **Protocol** | Invalid message, sequence gap | Log error, send Reject |
| **Business** | Invalid order, insufficient funds | Send ExecutionReport (Rejected) |
| **System** | Database down, Redis unavailable | Circuit breaker, alerting |

### Connection Errors

- **WebSocket Disconnect**: Auto-reconnect with exponential backoff
- **Timeout**: Send TestRequest, disconnect on failure
- **Invalid Message**: Log error, send Reject (3) message

### Session Errors

- **Sequence Gap**: Send ResendRequest (2)
- **Invalid SenderCompID**: Send Reject and disconnect
- **Heartbeat Timeout**: Send Heartbeat, disconnect on no response

### Business Errors

- **Invalid Order**: Send ExecutionReport with ExecType=8 (Rejected)
- **Insufficient Funds**: Send ExecutionReport with ExecType=8
- **Symbol Not Found**: Send ExecutionReport with ExecType=8

### System Errors

- **Database Unavailable**: Circuit breaker open, use Redis cache
- **Redis Unavailable**: Degraded mode, in-memory only
- **External Service Down**: Use circuit breaker, return cached data

### Error Response Format

```python
class ErrorResponse(BaseModel):
    """Standardized error response."""
    error_code: str
    error_type: str
    message: str
    details: dict[str, Any] | None = None
    timestamp: datetime
    correlation_id: str
    
    # Example:
    # {
    #     "error_code": "ORDER_REJECTED",
    #     "error_type": "business",
    #     "message": "Insufficient funds",
    #     "details": {"required": 1000, "available": 500},
    #     "timestamp": "2024-01-15T10:30:00Z",
    #     "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
    # }
```

## Testing Strategy

### Test Structure

```
tests/
├── conftest.py
├── unit/
│   ├── core/
│   │   ├── test_parser.py
│   │   ├── test_serializer.py
│   │   ├── test_message.py
│   │   └── test_session.py
│   ├── client/
│   │   └── test_order_manager.py
│   ├── market/
│   │   └── test_matching_engine.py
│   └── persistence/
│       ├── test_order_repository.py
│       └── test_execution_repository.py
├── integration/
│   ├── test_order_lifecycle.py
│   └── test_fix_session.py
└── load/
    └── test_concurrent.py
```

### Unit Tests

**Coverage Target: 90%+**

**Core Engine Tests:**
```python
# tests/unit/core/test_parser.py

import pytest
from fixwire.core.parser import FIXParser
from fixwire.core.message import FIXMessage


class TestFIXParser:
    """Test FIX message parsing."""

    def test_parse_single_message(self):
        """Parse a valid FIX message."""
        raw = b"8=FIX.4.4\x019=85\x0135=D\x0149=CLIENT01\x0156=MARKET01\x0134=1\x0152=20231220-14:30:00.000\x0111=ORD001\x0121=1\x0155=AAPL\x0154=1\x0138=100\x0140=2\x0144=150.50\x0110=128\x01"
        parser = FIXParser()
        messages = parser.parse(raw)
        
        assert len(messages) == 1
        assert messages[0].msg_type == "D"
        assert messages[0]["55"] == "AAPL"
    
    def test_parse_multiple_messages(self):
        """Parse multiple messages in a single buffer."""
        # Test batch parsing
        pass
    
    def test_parse_incomplete_message(self):
        """Handle incomplete message (missing checksum)."""
        pass
    
    def test_checksum_validation(self):
        """Validate message checksum."""
        pass
    
    def test_body_length_validation(self):
        """Validate body length calculation."""
        pass


class TestFIXMessage:
    """Test FIX message object."""

    def test_get_tag_value(self):
        """Get tag value by number."""
        msg = FIXMessage()
        msg["35"] = "D"
        assert msg["35"] == "D"
        assert msg.msg_type == "D"
    
    def test_set_tag_value(self):
        """Set tag value."""
        pass
    
    def test_remove_tag(self):
        """Remove a tag."""
        pass
    
    def test_iteration(self):
        """Iterate over tags."""
        pass
    
    def test_equality(self):
        """Message equality comparison."""
        pass
```

**Matching Engine Tests:**
```python
# tests/unit/market/test_matching_engine.py

import pytest
from fixwire.market.matching import MatchingEngine
from fixwire.core.message import FIXMessage


class TestMatchingEngine:
    """Test order matching logic."""

    def test_match_buy_and_sell(self):
        """Match compatible buy and sell orders."""
        engine = MatchingEngine()
        
        buy_order = self._create_order("D", "AAPL", "1", 100, 150.00)
        sell_order = self._create_order("D", "AAPL", "2", 100, 150.00)
        
        engine.add_order(buy_order)
        fill = engine.add_order(sell_order)
        
        assert fill is not None
        assert fill.last_qty == 100
        assert fill.last_px == 150.00
    
    def test_no_match_price_mismatch(self):
        """No match when prices don't overlap."""
        pass
    
    def test_partial_fill(self):
        """Partial fill when quantities differ."""
        pass
    
    def test_price_time_priority(self):
        """FIFO at same price level."""
        pass
    
    def test_cancel_order(self):
        """Cancel an existing order."""
        pass
    
    def test_replace_order(self):
        """Replace an existing order."""
        pass

    def _create_order(self, msg_type, symbol, side, qty, price):
        """Helper to create test orders."""
        msg = FIXMessage()
        msg["35"] = msg_type
        msg["55"] = symbol
        msg["54"] = side
        msg["38"] = str(qty)
        msg["44"] = str(price)
        return msg
```

### Integration Tests

**End-to-End Flow:**
```python
# tests/integration/test_order_lifecycle.py

import pytest
from fixwire.client import FIXClient
from fixwire.market import FIXMarket


@pytest.mark.integration
class TestOrderLifecycle:
    """Test complete order lifecycle."""

    @pytest.mark.asyncio
    async def test_new_order_fill(self):
        """New order → Execution Report (Fill)."""
        market = FIXMarket()
        client = FIXClient()
        
        async with market.run(), client.connect(market.url):
            # Submit order
            order = await client.new_order(
                symbol="AAPL",
                side="BUY",
                qty=100,
                price=150.00
            )
            
            # Wait for execution
            exec_report = await client.wait_for_execution(order.cl_ord_id)
            
            assert exec_report.ord_status == "2"  # Filled
            assert exec_report.last_qty == 100
    
    @pytest.mark.asyncio
    async def test_cancel_order(self):
        """New order → Cancel → Execution Report (Cancelled)."""
        pass
    
    @pytest.mark.asyncio
    async def test_replace_order(self):
        """New order → Replace → Execution Report (Replaced)."""
        pass
    
    @pytest.mark.asyncio
    async def test_session_reconnect(self):
        """Test session reconnection after disconnect."""
        pass
```

### Test Configuration

```python
# conftest.py

import pytest
import asyncio
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from fixwire.core.parser import FIXParser
from fixwire.core.message import FIXMessage
from fixwire.persistence.database import Base


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_engine():
    """Test database engine (SQLite for tests)."""
    engine = create_async_engine("sqlite+aiosqlite:///test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Test database session."""
    async with AsyncSession(db_engine) as session:
        yield session


@pytest.fixture
def fix_parser() -> FIXParser:
    """FIX parser instance."""
    return FIXParser()


@pytest.fixture
def sample_logon() -> FIXMessage:
    """Sample logon message."""
    msg = FIXMessage()
    msg["8"] = "FIX.4.4"
    msg["35"] = "A"
    msg["49"] = "CLIENT01"
    msg["56"] = "MARKET01"
    msg["34"] = "1"
    msg["52"] = "20231220-14:30:00.000"
    msg["98"] = "0"
    msg["108"] = "30"
    return msg


@pytest.fixture
def sample_new_order() -> FIXMessage:
    """Sample new order message."""
    msg = FIXMessage()
    msg["35"] = "D"
    msg["49"] = "CLIENT01"
    msg["56"] = "MARKET01"
    msg["11"] = "ORD-001"
    msg["21"] = "1"
    msg["55"] = "AAPL"
    msg["54"] = "1"
    msg["38"] = "100"
    msg["40"] = "2"
    msg["44"] = "150.50"
    msg["59"] = "0"
    return msg
```

### Running Tests

```bash
# Unit tests
pytest tests/unit/ -v --cov=fixwire --cov-report=html

# Integration tests
pytest tests/integration/ -v --cov=fixwire

# All tests with coverage
pytest tests/ -v --cov=fixwire --cov-report=html --cov-report=term-missing

# Load tests
pytest tests/load/ -v --benchmark-only
```

### CI/CD Integration

```yaml
# .github/workflows/test.yml

name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e .[dev]
      - name: Run tests
        run: pytest tests/ --cov=fixwire --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### Load Tests

```python
# tests/load/test_concurrent_connections.py

import asyncio
import pytest
from fixwire.client import FIXClient


@pytest.mark.load
class TestConcurrentConnections:
    """Load testing for concurrent connections."""

    @pytest.mark.asyncio
    async def test_100_concurrent_clients(self):
        """Handle 100 concurrent client connections."""
        clients = [FIXClient() for _ in range(100)]
        
        async def connect_and_trade(client):
            async with client.connect(MARKET_URL):
                await client.new_order("AAPL", "BUY", 100, 150.00)
        
        # Run all concurrently
        await asyncio.gather(*[connect_and_trade(c) for c in clients])
    
    @pytest.mark.asyncio
    async def test_message_throughput(self):
        """Measure messages per second."""
        pass
```

## Security

### Input Validation

```python
from pydantic import BaseModel, validator

class NewOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float
    
    @validator('side')
    def validate_side(cls, v):
        if v not in ('1', '2'):
            raise ValueError('Side must be 1 (Buy) or 2 (Sell)')
        return v
    
    @validator('quantity')
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError('Quantity must be positive')
        return v
    
    @validator('price')
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError('Price must be positive')
        return v
```

### Rate Limiting

```python
from datetime import datetime

class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = datetime.utcnow()
    
    async def acquire(self) -> bool:
        now = datetime.utcnow()
        time_passed = (now - self.last_update).total_seconds()
        self.tokens = min(
            self.burst,
            self.tokens + time_passed * self.rate
        )
        self.last_update = now
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
```

### Audit Logging

```python
import structlog

logger = structlog.get_logger()

def log_order_event(
    user_id: str,
    order_id: str,
    event_type: str,
    details: dict
):
    """Log order events for audit trail."""
    logger.info(
        "audit.order",
        user_id=user_id,
        order_id=order_id,
        event_type=event_type,
        details=details,
        timestamp=datetime.utcnow()
    )
```

### Security Best Practices

1. **Never log sensitive data**: Passwords, API keys, tokens
2. **Use parameterized queries**: Prevent SQL injection (SQLAlchemy handles this)
3. **Validate all inputs**: Pydantic validation on all endpoints
4. **Rate limiting**: Prevent brute force attacks
5. **HTTPS/WSS in production**: Always use TLS
6. **Secret management**: Use environment variables, never hardcode
7. **Dependency scanning**: Regular security audits

## Production-Grade Checklist

### ✅ Architecture

- [x] Clean Architecture (Hexagonal)
- [x] Separation of Concerns
- [x] Dependency Injection
- [x] SOLID Principles

### ✅ Resilience

- [x] Retry with Exponential Backoff
- [x] Timeout Management
- [x] Graceful Shutdown
- [x] Reconnection Logic
- [x] Sequence Recovery

### ✅ Performance

- [x] Connection Pooling
- [x] Async I/O (Python asyncio)
- [x] Rate Limiting

### ✅ Observability

- [x] Structured Logging (JSON)
- [x] Health Check Endpoints
- [x] Request Correlation IDs

### ✅ Security

- [x] Input Validation (Pydantic)
- [x] Rate Limiting
- [x] Audit Logging

### ✅ Testing

- [x] Unit Tests (90%+ coverage)
- [x] Integration Tests
- [x] Load Tests
- [x] CI/CD Pipeline

### ✅ Deployment

- [x] Docker Containers
- [x] Docker Compose
- [x] Configuration Management
- [x] Health Checks

### ✅ Operations

- [x] Graceful Shutdown
- [x] Error Handling
- [x] Monitoring & Alerting

## Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| **Concurrent Connections** | 100+ | Per service instance |
| **Message Throughput** | 1,000+ msg/sec | Order processing |
| **Latency (P99)** | < 100ms | Order submission |
| **Startup Time** | < 5 seconds | Cold start |
| **Memory Usage** | < 512MB | Per instance |

## Monitoring

### Health Check Endpoints

```
GET /health/live    - Is process alive?
GET /health/ready   - Can serve traffic?
```

### Basic Metrics

- Active sessions count
- Order throughput (orders/sec)
- Message latency (P95, P99)
- Error rate
- Reconnection attempts

## Quick Start

### Prerequisites

```bash
# Install mise
curl https://mise.run | sh

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Activate mise
eval "$(mise activate bash)"
```

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/fixwire.git
cd fixwire

# Install tools
mise install

# Install dependencies
uv venv
uv pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Run database migrations
uv run alembic upgrade head

# Run tests
uv run pytest tests/ -v --cov=fixwire

# Start development server
uv run uvicorn fixwire.api.app:app --reload
```

### Docker

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Run tests
docker-compose run --rm test

# Stop all services
docker-compose down
```

## License

MIT License - See LICENSE file for details
