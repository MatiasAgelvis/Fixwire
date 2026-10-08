# TODO

Backlog for work that came up but is out of scope for the current task.
Do these soon — before they grow too large.

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
