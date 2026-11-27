"""Credential redaction for log output.

Parser diagnostics log a prefix of the offending bytes so a malformed
message can be diagnosed. A malformed *Logon* can carry a password, so the
prefix is redacted before it reaches a logger.
"""

from fixwire.core.redaction import redact

SOH = b"\x01"


class TestRedact:
    """Only credential-bearing tag values are replaced."""

    def test_password_is_replaced(self):
        """Tag 554 never reaches a log in clear."""
        # Arrange
        raw = b"8=FIX.4.4" + SOH + b"554=supersecret" + SOH

        # Act
        result = redact(raw)

        # Assert
        assert b"supersecret" not in result
        assert result == b"8=FIX.4.4" + SOH + b"554=***" + SOH

    def test_other_credentials_are_replaced(self):
        """New password, username, and raw data are credentials too."""
        # Arrange
        raw = (
            b"553=alice" + SOH
            + b"925=newsecret" + SOH
            + b"96=blob" + SOH
        )

        # Act
        result = redact(raw)

        # Assert
        assert result == b"553=***" + SOH + b"925=***" + SOH + b"96=***" + SOH

    def test_ordinary_fields_are_untouched(self):
        """Diagnostics stay useful: everything else is preserved."""
        # Arrange
        raw = b"8=FIX.4.4" + SOH + b"35=A" + SOH + b"49=CLIENT" + SOH

        # Act & Assert
        assert redact(raw) == raw

    def test_a_truncated_field_is_still_redacted(self):
        """Log prefixes cut mid-value; the tag is what matters."""
        # Arrange: no trailing SOH, as a 100-byte prefix would be
        raw = b"35=A" + SOH + b"554=supersecre"

        # Act
        result = redact(raw)

        # Assert
        assert b"supersecre" not in result
        assert result.endswith(b"554=***")

    def test_empty_input(self):
        """Nothing to redact is not an error."""
        # Act & Assert
        assert redact(b"") == b""


class TestParserDiagnosticsAreRedacted:
    """The wiring, not just the helper: diagnostics must actually use it."""

    def test_a_malformed_logon_does_not_leak_its_password(self):
        """A bad checksum must not dump the credentials beside it."""
        # Arrange: bytes that are rejected early, carrying a password
        from structlog.testing import capture_logs

        from fixwire.core.parser import FIXParser, ParserConfig

        parser = FIXParser(ParserConfig(strict=False))
        raw = (
            b"8=NOTFIX" + SOH
            + b"35=A" + SOH
            + b"554=supersecret" + SOH
        )

        # Act
        with capture_logs() as logs:
            parser.parse(raw)

        # Assert: the diagnostic kept the bytes but not the credential
        assert any(e["event"] == "parser.invalid_begin_string" for e in logs)
        assert "supersecret" not in str(logs)
        assert "***" in str(logs)
