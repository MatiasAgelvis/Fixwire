"""Audit log taxonomy, enforced rather than documented and hoped for.

See ``docs/AUDIT_LOGGING.md``. These tests parse the source so a new log
call cannot quietly invent a namespace, a level, or a dynamic event name.
"""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "fixwire"

ALLOWED_LEVELS = {"debug", "info", "warning", "error"}
ALLOWED_ROOTS = {
    "session", "runner", "server", "transport", "parser", "shutdown"
}

# logger.info("name", ...) or logger.warning(\n    "name", ...
CALL = re.compile(
    r'logger\.(debug|info|warning|error|critical|exception)\(\s*(f?)"([^"]+)"'
)
# <root>[.<segment>].<event>, all lowercase snake_case
NAME = re.compile(
    r"^(" + "|".join(sorted(ALLOWED_ROOTS)) + r")(\.[a-z][a-z0-9_]*)+$"
)


def _calls():
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text()
        for match in CALL.finditer(text):
            line = text[: match.start()].count("\n") + 1
            yield (
                path.relative_to(SRC),
                line,
                match.group(1),
                match.group(2),
                match.group(3),
            )


def test_the_source_actually_has_log_calls():
    """Guard against the parser silently matching nothing."""
    assert len(list(_calls())) > 20


@pytest.mark.parametrize("call", list(_calls()), ids=lambda c: f"{c[0]}:{c[1]}")
def test_call_uses_an_allowed_level(call):
    """Only the four documented levels; no critical, no exception."""
    path, line, level, _, _ = call
    assert level in ALLOWED_LEVELS, f"{path}:{line} uses level {level!r}"


@pytest.mark.parametrize("call", list(_calls()), ids=lambda c: f"{c[0]}:{c[1]}")
def test_event_name_is_namespaced_and_static(call):
    """Static, namespaced, snake_case — so queries and alerts can rely on it."""
    path, line, _, fstring, name = call
    assert not fstring, f"{path}:{line} builds its event name with an f-string"
    assert NAME.match(name), f"{path}:{line} event {name!r} is not namespaced"
    assert name.split(".")[0] in ALLOWED_ROOTS, f"{path}:{line} {name!r}"


def test_no_logger_exception_or_critical():
    """structlog has no critical; exception would smuggle tracebacks into logs."""
    text = "".join(path.read_text() for path in SRC.rglob("*.py"))
    assert "logger.critical(" not in text
    assert "logger.exception(" not in text


DOC = Path(__file__).resolve().parents[2] / "docs" / "AUDIT_LOGGING.md"
CATALOGUE_ROW = re.compile(
    r"^\| `([a-z0-9_.]+)` \| (debug|info|warning|error) \|", re.MULTILINE
)


def _catalogue() -> dict[str, str]:
    """Event name to level, as documented."""
    return dict(CATALOGUE_ROW.findall(DOC.read_text()))


def test_every_event_is_documented():
    """A new log call must appear in the catalogue."""
    documented = _catalogue()
    emitted = {name for _, _, _, _, name in _calls()}
    missing = sorted(emitted - documented.keys())
    assert not missing, f"undocumented events: {missing}"


def test_catalogue_has_no_stale_events():
    """An event removed from the code must leave the catalogue."""
    documented = _catalogue()
    emitted = {name for _, _, _, _, name in _calls()}
    stale = sorted(documented.keys() - emitted)
    assert not stale, f"documented but never emitted: {stale}"


def test_catalogue_levels_match_the_code():
    """The level in the doc is the level in the code."""
    documented = _catalogue()
    wrong = [
        f"{name}: code={level}, doc={documented[name]}"
        for _, _, level, _, name in _calls()
        if name in documented and documented[name] != level
    ]
    assert not wrong, wrong
