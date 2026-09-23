"""Tests for FIXParser."""

import pytest

from fixwire.core.constants import SOH
from fixwire.core.message import FIXMessage
from fixwire.core.parser import FIXParseError, FIXParser


class TestFIXParser:
    """Test FIXParser class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.parser = FIXParser()

    def _build_message(self, **fields) -> bytes:
        """Helper to build a raw FIX message."""
        parts = []
        for tag, value in fields.items():
            parts.append(f"{tag}={value}")

        body = SOH.join(parts) + SOH
        body_bytes = body.encode("ascii")

        # Calculate body length
        body_length = len(body_bytes)

        # Build message
        result = bytearray()
        result.extend(b"8=FIX.4.4" + SOH.encode())
        result.extend(f"9={body_length}".encode() + SOH.encode())
        result.extend(body_bytes)

        # Calculate checksum
        checksum = sum(result) % 256
        result.extend(f"10={checksum:03d}".encode() + SOH.encode())

        return bytes(result)

    def test_parse_single_message(self):
        """Parse a single complete message."""
        raw = self._build_message(
            **{"35": "D", "49": "CLIENT01", "56": "MARKET01",
               "34": "1", "52": "20231220-14:30:00.000"}
        )

        messages = self.parser.parse(raw)

        assert len(messages) == 1
        msg = messages[0]
        assert msg.msg_type == "D"
        assert msg.sender == "CLIENT01"
        assert msg.target == "MARKET01"
        assert msg.sequence == 1

    def test_parse_multiple_messages(self):
        """Parse multiple messages in one buffer."""
        msg1 = self._build_message(**{"35": "D", "49": "C1", "56": "M1", "34": "1"})
        msg2 = self._build_message(**{"35": "D", "49": "C1", "56": "M1", "34": "2"})

        messages = self.parser.parse(msg1 + msg2)

        assert len(messages) == 2
        assert messages[0].sequence == 1
        assert messages[1].sequence == 2

    def test_parse_incomplete_message(self):
        """Parse incomplete message (returns None)."""
        raw = b"8=FIX.4.4\x019=50\x0135=D"

        messages = self.parser.parse(raw)

        assert len(messages) == 0

    def test_parse_with_garbage_before(self):
        """Parse message with garbage data before it."""
        garbage = b"some random data\x00\x00"
        msg = self._build_message(**{"35": "D", "49": "C1", "56": "M1"})

        messages = self.parser.parse(garbage + msg)

        assert len(messages) == 1
        assert messages[0].msg_type == "D"

    def test_checksum_validation(self):
        """Validate checksum on parsed message."""
        raw = self._build_message(
            **{"35": "A", "49": "CLIENT", "56": "SERVER",
               "34": "1", "98": "0", "108": "30"}
        )

        messages = self.parser.parse(raw)

        assert len(messages) == 1

    def test_checksum_mismatch_strict(self):
        """Reject message with bad checksum in strict mode."""
        raw = self._build_message(**{"35": "D", "49": "C1", "56": "M1"})

        # Corrupt checksum
        raw = raw[:-5] + b"999\x01"

        with pytest.raises(FIXParseError, match="Checksum mismatch"):
            self.parser.parse(raw)

    def test_invalid_begin_string(self):
        """Reject message with invalid BeginString."""
        msg = SOH.join([
            "8=INVALID",
            "9=10",
            "35=D",
            "10=128"
        ]).encode() + SOH.encode()

        with pytest.raises(FIXParseError, match="Invalid BeginString"):
            self.parser.parse(msg
)

    def test_empty_message(self):
        """Reject empty message."""
        with pytest.raises(FIXParseError, match="Empty message"):
            self.parser.parse(b"10=000\x01")

    def test_get_message_type(self):
        """Get message type from parsed message."""
        raw = self._build_message(**{"35": "D", "49": "C1", "56": "M1"})

        messages = self.parser.parse(raw)

        assert messages[0].msg_type == "D"

    def test_get_all_tags(self):
        """Get all tags from parsed message."""
        raw = self._build_message(
            **{"35": "D", "49": "CLIENT", "56": "SERVER",
               "11": "ORD001", "55": "AAPL", "54": "1"}
        )

        messages = self.parser.parse(raw)
        msg = messages[0]

        assert msg.has(35)
        assert msg.has(49)
        assert msg.has(56)
        assert msg.has(11)
        assert msg.has(55)
        assert msg.has(54)

    def test_buffer_accumulation(self):
        """Test that parser buffers partial data."""
        msg = self._build_message(**{"35": "D", "49": "C1", "56": "M1"})

        # Send first half
        messages1 = self.parser.parse(msg[:len(msg) // 2])
        assert len(messages1) == 0

        # Send second half
        messages2 = self.parser.parse(msg[len(msg) // 2:])
        assert len(messages2) == 1

    def test_reset_parser(self):
        """Test parser reset clears buffer."""
        raw = self._build_message(**{"35": "D", "49": "C1", "56": "M1"})

        self.parser.parse(raw[:50])
        assert self.parser.buffer_size > 0

        self.parser.reset()
        assert self.parser.buffer_size == 0

    def test_parse_logon_message(self):
        """Parse a Logon message."""
        raw = self._build_message(
            **{"35": "A", "49": "CLIENT01", "56": "MARKET01",
               "34": "1", "98": "0", "108": "30"}
        )

        messages = self.parser.parse(raw)
        msg = messages[0]

        assert msg.msg_type == "A"
        assert msg.get(98) == "0"
        assert msg.get_int(108) == 30

    def test_parse_heartbeat(self):
        """Parse a Heartbeat message."""
        raw = self._build_message(
            **{"35": "0", "49": "SERVER", "56": "CLIENT",
               "34": "5", "52": "20231220-14:30:00.000"}
        )

        messages = self.parser.parse(raw)
        msg = messages[0]

        assert msg.msg_type == "0"

    def test_parse_with_text_field(self):
        """Parse message with text field."""
        raw = self._build_message(
            **{"35": "3", "49": "SERVER", "56": "CLIENT",
               "34": "10", "45": "5", "58": "Invalid message format"}
        )

        messages = self.parser.parse(raw)
        msg = messages[0]

        assert msg.msg_type == "3"
        assert msg.text == "Invalid message format"

    def test_validate_message_valid(self):
        """Validate a valid message."""
        raw = self._build_message(
            **{"35": "D", "49": "CLIENT", "56": "SERVER",
               "34": "1", "52": "20231220-14:30:00.000"}
        )

        messages = self.parser.parse(raw)
        errors = self.parser.validate_message(messages[0])

        assert len(errors) == 0

    def test_validate_message_missing_tags(self):
        """Validate message with missing required tags."""
        from fixwire.core.message import FIXMessage

        msg = FIXMessage()
        msg[35] = "D"

        errors = self.parser.validate_message(msg)

        assert len(errors) > 0
        assert any("BeginString" in e for e in errors)
        assert any("SenderCompID" in e for e in errors)

    def test_strict_mode_disabled(self):
        """Test parser with strict mode disabled."""
        parser = FIXParser()
        parser._strict_mode = False

        # Message with bad checksum shouldn't raise
        raw = self._build_message(**{"35": "D", "49": "C1", "56": "M1"})
        raw = raw[:-5] + b"999\x01"

        # Should not raise, just skip the message
        messages = parser.parse(raw)
        assert len(messages) == 0
