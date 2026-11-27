"""Tests for the structlog setup helper."""

import logging

import pytest
import structlog

from fixwire.logging import configure_logging


@pytest.fixture(autouse=True)
def _restore_structlog():
    """Do not leak configuration into other tests."""
    yield
    structlog.reset_defaults()


class TestConfigureLogging:
    """Rendering choice and level filtering."""

    def test_console_renderer_by_default(self):
        """Humans reading a terminal get the console renderer."""
        # Act
        configure_logging()

        # Assert
        processors = structlog.get_config()["processors"]
        assert any(
            isinstance(p, structlog.dev.ConsoleRenderer) for p in processors
        )

    def test_json_renderer_on_request(self):
        """Shipping to a collector gets one JSON object per line."""
        # Act
        configure_logging(json=True)

        # Assert
        processors = structlog.get_config()["processors"]
        assert any(
            isinstance(p, structlog.processors.JSONRenderer)
            for p in processors
        )

    def test_level_filters_lower_levels(self, capsys):
        """INFO is suppressed when configured at WARNING."""
        # Arrange
        configure_logging(level=logging.WARNING)
        log = structlog.get_logger("audit-test")

        # Act
        log.info("audit_test.hidden")
        log.warning("audit_test.visible")

        # Assert
        captured = capsys.readouterr().out
        assert "audit_test.visible" in captured
        assert "audit_test.hidden" not in captured

    def test_is_idempotent(self):
        """Calling it twice replaces the configuration instead of stacking."""
        # Act
        configure_logging(json=True)
        configure_logging(json=False)

        # Assert
        processors = structlog.get_config()["processors"]
        assert not any(
            isinstance(p, structlog.processors.JSONRenderer)
            for p in processors
        )
