"""Tests for FIXParser."""

import pytest

from fixwire.core.constants import SOH
from fixwire.core.message import FIXMessage
from fixwire.core.parser import FIXParseError, FIXParser


def build_raw_message(fields: dict[int, str]) -> tuple[FIXMessage, bytes]:
    """Build a valid FIX message and return both the message and raw bytes.

    Includes required tags by default. Override them by passing in fields.

    Returns:
        Tuple of (FIXMessage, raw bytes)
    """
    # Default required tags (8 is added by serialize)
    defaults = {
        35: "D",
        49: "CLIENT",
        56: "SERVER",
        34: "1",
        52: "20231220-14:30:00.000",
    }
    # Merge with provided fields (provided fields override defaults)
    merged = defaults | fields
    msg = FIXMessage.from_dict(merged)
    raw = msg.serialize()
    return msg, raw


class TestFIXParserBasic:
    """Test basic parsing functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.parser = FIXParser()

    def test_parse_single_message(self):
        """Parse a single complete message."""
        # Arrange
        base_message = {
            35: "D", 49: "CLIENT01", 56: "MARKET01",
            34: "1", 52: "20231220-14:30:00.000"
        }
        original, raw = build_raw_message(base_message)

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]

        for tag, value in base_message.items():
            assert parsed[tag] == value

    def test_parse_multiple_messages(self):
        """Parse multiple messages in one buffer."""
        # Arrange
        msg1, raw1 = build_raw_message({35: "D", 49: "C1", 56: "M1", 34: "1"})
        msg2, raw2 = build_raw_message({35: "D", 49: "C1", 56: "M1", 34: "2"})

        # Act
        messages = self.parser.parse(raw1 + raw2)

        # Assert
        assert len(messages) == 2
        assert messages[0][34] == msg1[34]
        assert messages[1][34] == msg2[34]

    def test_parse_incomplete_message(self):
        """Parse incomplete message (returns empty)."""
        # Arrange
        raw = b"8=FIX.4.4\x019=50\x0135=D"

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 0

    def test_parse_with_garbage_before(self):
        """Parse message with garbage data before it."""
        # Arrange
        garbage = b"some random data\x00\x00"
        original, raw = build_raw_message({35: "D", 49: "C1", 56: "M1"})

        # Act
        messages = self.parser.parse(garbage + raw)

        # Assert
        assert len(messages) == 1
        assert messages[0][35] == original[35]

    def test_parse_with_garbage_between_messages(self):
        """Parse with garbage between two messages."""
        # Arrange
        msg1, raw1 = build_raw_message({35: "D", 49: "C1", 56: "M1", 34: "1"})
        garbage = b"\x00\x01\x02"
        msg2, raw2 = build_raw_message({35: "D", 49: "C1", 56: "M1", 34: "2"})

        # Act
        messages = self.parser.parse(raw1 + garbage + raw2)

        # Assert
        assert len(messages) == 2
        assert messages[0][34] == msg1[34]
        assert messages[1][34] == msg2[34]

    def test_parse_empty_buffer(self):
        """Parse empty buffer."""
        # Arrange & Act
        messages = self.parser.parse(b"")

        # Assert
        assert len(messages) == 0

    def test_parse_buffer_with_only_garbage(self):
        """Parse buffer with only garbage."""
        # Arrange & Act
        messages = self.parser.parse(b"not a fix message")

        # Assert
        assert len(messages) == 0


class TestFIXParserBuffering:
    """Test buffer management."""

    def setup_method(self):
        """Setup test fixtures."""
        self.parser = FIXParser()

    def test_buffer_accumulation(self):
        """Test that parser buffers partial data."""
        # Arrange
        original, raw = build_raw_message({35: "D", 49: "C1", 56: "M1"})

        # Act: parse in two chunks
        messages1 = self.parser.parse(raw[:len(raw) // 2])
        messages2 = self.parser.parse(raw[len(raw) // 2:])

        # Assert
        assert len(messages1) == 0
        assert len(messages2) == 1
        for tag, value in original.items():
            assert messages2[0][tag] == value

    def test_reset_parser(self):
        """Test parser reset clears buffer."""
        # Arrange
        original, raw = build_raw_message({35: "D", 49: "C1", 56: "M1"})
        self.parser.parse(raw[:50])

        # Act
        self.parser.reset()

        # Assert
        assert self.parser.buffer_size == 0

    def test_buffer_size(self):
        """Test buffer size tracking."""
        # Arrange
        original, raw = build_raw_message({35: "D", 49: "C1", 56: "M1"})

        # Act
        assert self.parser.buffer_size == 0
        self.parser.parse(raw[:20])

        # Assert
        assert self.parser.buffer_size > 0


class TestFIXParserMessageTypes:
    """Test parsing different message types."""

    def setup_method(self):
        """Setup test fixtures."""
        self.parser = FIXParser()

    def test_parse_logon_message(self):
        """Parse a Logon message."""
        # Arrange
        original, raw = build_raw_message({
            35: "A", 49: "CLIENT01", 56: "MARKET01",
            34: "1", 98: "0", 108: "30"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        for tag, value in original.items():
            assert parsed[tag] == value

    def test_parse_logout_message(self):
        """Parse a Logout message."""
        # Arrange
        original, raw = build_raw_message({
            35: "5", 49: "SERVER", 56: "CLIENT",
            34: "5", 58: "Goodbye"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        for tag, value in original.items():
            assert parsed[tag] == value

    def test_parse_heartbeat(self):
        """Parse a Heartbeat message."""
        # Arrange
        original, raw = build_raw_message({
            35: "0", 49: "SERVER", 56: "CLIENT",
            34: "5", 52: "20231220-14:30:00.000"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        for tag, value in original.items():
            assert parsed[tag] == value

    def test_parse_test_request(self):
        """Parse a TestRequest message."""
        # Arrange
        original, raw = build_raw_message({
            35: "1", 49: "CLIENT", 56: "SERVER",
            34: "10", 112: "TEST-001"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        for tag, value in original.items():
            assert parsed[tag] == value

    def test_parse_new_order_single(self):
        """Parse a NewOrderSingle message."""
        # Arrange
        original, raw = build_raw_message({
            35: "D", 49: "CLIENT", 56: "SERVER",
            34: "15", 11: "ORD-001", 55: "AAPL",
            54: "1", 38: "100", 40: "2", 44: "150.50"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        for tag, value in original.items():
            assert parsed[tag] == value

    def test_parse_execution_report(self):
        """Parse an ExecutionReport message."""
        # Arrange
        original, raw = build_raw_message({
            35: "8", 49: "SERVER", 56: "CLIENT",
            34: "20", 11: "ORD-001", 17: "EXEC-001",
            150: "2", 39: "2", 55: "AAPL", 54: "1",
            32: "100", 31: "150.50", 14: "100", 6: "150.50"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        for tag, value in original.items():
            assert parsed[tag] == value


class TestFIXParserChecksumValidation:
    """Test checksum validation."""

    def setup_method(self):
        """Setup test fixtures."""
        self.parser = FIXParser()

    def test_checksum_valid(self):
        """Validate checksum on valid message."""
        # Arrange
        original, raw = build_raw_message({
            35: "A", 49: "CLIENT", 56: "SERVER",
            34: "1", 98: "0", 108: "30"
        })

        # Act
        result = self.parser.validate_checksum(raw)

        # Assert
        assert result is True

    def test_checksum_strict_invalid_raises(self):
        """Strict mode raises on invalid checksum."""
        # Arrange: setup a base message and corrupt the checksum
        original, raw = build_raw_message({35: "D", 49: "C1", 56: "M1"})
        raw = raw[:-4] + b"999" + SOH.encode()  # Corrupt checksum

        # Act & Assert
        with pytest.raises(FIXParseError, match="Checksum mismatch"):
            self.parser.validate_checksum(raw)

    def test_checksum_non_strict_invalid_returns_false(self):
        """Non-strict mode returns False on invalid checksum."""
        # Arrange
        parser = FIXParser(strict=False)
        original, raw = build_raw_message({35: "D", 49: "C1", 56: "M1"})
        raw = raw[:-4] + b"999\x01"  # Corrupt checksum

        # Act
        result = parser.validate_checksum(raw)

        # Assert
        assert result is False


class TestFIXParserStrictMode:
    """Test strict vs non-strict mode."""

    def setup_method(self):
        """Setup test fixtures."""
        self.parser = FIXParser()

    def test_strict_mode_default(self):
        """Test that strict mode is enabled by default."""
        # Arrange & Act & Assert
        assert self.parser.strict is True

    def test_strict_mode_rejects_invalid_begin_string(self):
        """Test strict mode rejects invalid BeginString."""
        # Arrange
        raw = SOH.join([
            "8=INVALID",
            "9=10",
            "35=D",
            "10=128"
        ]).encode() + SOH.encode()

        # Act & Assert
        with pytest.raises(FIXParseError, match="Invalid BeginString"):
            self.parser.parse(raw)

    def test_non_strict_mode_skips_invalid_begin_string(self):
        """Test non-strict mode skips invalid BeginString."""
        # Arrange
        parser = FIXParser(strict=False)
        raw = SOH.join([
            "8=INVALID",
            "9=10",
            "35=D",
            "10=128"
        ]).encode() + SOH.encode()

        # Act
        messages = parser.parse(raw)

        # Assert
        assert len(messages) == 0

    def test_strict_mode_rejects_message_without_msg_type(self):
        """Test strict mode rejects message missing MsgType (35)."""
        # Arrange: Message with valid checksum but no MsgType
        prefix = SOH.join(["8=FIX.4.4", "9=5"]).encode() + SOH.encode()
        checksum = sum(prefix) % 256
        raw = prefix + f"10={checksum:03d}".encode() + SOH.encode()

        # Act & Assert
        with pytest.raises(FIXParseError, match="Missing required tag: MsgType"):
            self.parser.parse(raw)

    def test_strict_mode_rejects_truly_empty_buffer(self):
        """Test strict mode with empty buffer."""
        # Arrange
        raw = b""

        # Act
        messages = self.parser.parse(raw)

        # Assert - Empty buffer returns empty list, no error
        assert len(messages) == 0

    def test_validate_message_valid(self):
        """Validate a valid message."""
        # Arrange
        original, raw = build_raw_message({
            35: "D", 49: "CLIENT", 56: "SERVER",
            34: "1", 52: "20231220-14:30:00.000"
        })
        messages = self.parser.parse(raw)

        # Act
        errors = self.parser.validate_message(messages[0])

        # Assert
        assert len(errors) == 0

    def test_validate_message_missing_tags(self):
        """Validate message with missing required tags."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"

        # Act
        errors = self.parser.validate_message(msg)

        # Assert
        assert len(errors) > 0
        assert any("BeginString" in e for e in errors)
        assert any("SenderCompID" in e for e in errors)

    def test_validate_message_invalid_sequence(self):
        """Validate message with invalid sequence number."""
        # Arrange
        msg = FIXMessage()
        msg[8] = "FIX.4.4"
        msg[35] = "D"
        msg[49] = "CLIENT"
        msg[56] = "SERVER"
        msg[34] = "0"  # Invalid sequence number, must be > 0
        msg[52] = "20231220-14:30:00.000"
        msg[10] = "123"

        # Act
        errors = self.parser.validate_message(msg)

        # Assert
        assert any("MsgSeqNum" in e for e in errors)

    def test_validate_message_unsupported_begin_string(self):
        """Validate message with unsupported BeginString."""
        # Arrange
        msg = FIXMessage()
        msg[8] = "FIX.3.0"  # Unsupported BeginString, must be FIX.4.4
        msg[35] = "D"
        msg[49] = "CLIENT"
        msg[56] = "SERVER"
        msg[34] = "1"
        msg[52] = "20231220-14:30:00.000"
        msg[10] = "123"

        # Act
        errors = self.parser.validate_message(msg)

        # Assert
        assert any("BeginString" in e for e in errors)


class TestFIXParserEdgeCases:
    """Test edge cases and error conditions."""

    def setup_method(self):
        """Setup test fixtures."""
        self.parser = FIXParser()

    def test_parse_message_with_text_field(self):
        """Parse message with text field."""
        # Arrange
        original, raw = build_raw_message({
            35: "3", 49: "SERVER", 56: "CLIENT",
            34: "10", 45: "5", 58: "Invalid message format"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        assert parsed[35] == original[35]
        assert parsed[58] == original[58]

    def test_parse_message_with_long_text(self):
        """Parse message with long text field."""
        # Arrange
        long_text = "A" * 1000
        original, raw = build_raw_message({
            35: "3", 49: "SERVER", 56: "CLIENT",
            34: "10", 45: "5", 58: long_text
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        assert messages[0][58] == original[58]

    def test_parse_message_with_special_characters(self):
        """Parse message with special characters in text."""
        # Arrange
        original, raw = build_raw_message({
            35: "3", 49: "SERVER", 56: "CLIENT",
            34: "10", 45: "5", 58: "Test with spaces and symbols!@#$%"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        assert messages[0][58] == original[58]

    def test_parse_message_all_tags(self):
        """Parse message with many tags."""
        # Arrange
        original, raw = build_raw_message({
            35: "D", 49: "CLIENT", 56: "SERVER",
            34: "1", 52: "20231220-14:30:00.000",
            11: "ORD-001", 21: "1", 55: "AAPL",
            54: "1", 38: "100", 40: "2", 44: "150.50",
            59: "0", 1: "ACCOUNT-001", 58: "Test order"
        })

        # Act
        messages = self.parser.parse(raw)

        # Assert
        assert len(messages) == 1
        parsed = messages[0]
        assert parsed[11] == original[11]
        assert parsed[55] == original[55]
        assert parsed[58] == original[58]
