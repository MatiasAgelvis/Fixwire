"""FIX Parser - Deserialize FIX byte stream into FIXMessage objects.

Handles parsing of FIX protocol messages from wire format.
"""

from __future__ import annotations

import structlog

from fixwire.core.constants import SOH
from fixwire.core.message import FIXMessage

logger = structlog.get_logger()

# FIX tag delimiters
FIELD_DELIMITER = SOH
FIX_DELIMITER = b"="

# Maximum message size (1MB)
MAX_MESSAGE_SIZE = 1_048_576

# Maximum number of tags per message
MAX_TAGS_PER_MESSAGE = 500


class FIXParseError(Exception):
    """Raised when a FIX message cannot be parsed."""

    def __init__(self, message: str, raw: bytes = b"", tag: int | None = None):
        self.raw = raw
        self.tag = tag
        super().__init__(message)


class FIXParser:
    """FIX Protocol Parser.

    Parses raw FIX byte stream into FIXMessage objects.

    Usage:
        parser = FIXParser()
        messages = parser.parse(raw_bytes)
        for msg in messages:
            print(msg.msg_type, msg.sender, msg.target)
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._strict_mode = True  # Enable strict validation

    def parse(self, data: bytes) -> list[FIXMessage]:
        """Parse raw data into FIX messages.

        Args:
            data: Raw bytes from wire.

        Returns:
            List of parsed FIXMessage objects.

        Raises:
            FIXParseError: If parsing fails in strict mode.
        """
        messages = []

        # Add incoming data to buffer
        self._buffer.extend(data)

        # Try to parse complete messages
        # Safety limit: no FIX message should exceed ~8KB
        max_iterations = max(1, len(data) // 10) + 10
        for _ in range(max_iterations):
            msg = self._try_parse_message()
            if msg is None:
                break
            messages.append(msg)
        else:
            logger.warning(
                "parser.max_iterations",
                buffer_size=len(self._buffer),
            )

        return messages

    def _try_parse_message(self) -> FIXMessage | None:
        """Try to parse a single message from buffer.

        Returns:
            FIXMessage if complete message found, None otherwise.
        """
        # Find start of message (8=FIX)
        start = self._buffer.find(b"8=FIX")
        if start == -1:
            # No message start found, keep only last few bytes
            if len(self._buffer) > 10:
                self._buffer = self._buffer[-10:]
            return None

        # Discard any data before message start
        if start > 0:
            self._buffer = self._buffer[start:]

        # Find end of message (10=checksum + SOH)
        # Checksum is 3 digits followed by SOH
        end = self._find_message_end()
        if end == -1:
            return None

        # Extract complete message
        # and remove it from buffer
        raw_msg = bytes(self._buffer[:end])
        self._buffer = self._buffer[end:]

        # Parse the message
        try:
            return self._parse_message(raw_msg)
        except FIXParseError as e:
            if self._strict_mode:
                raise
            logger.warning("parse.error", error=str(e), raw=raw_msg[:100])
            return None

    def _find_message_end(self) -> int:
        """Find the end of a FIX message in the buffer.

        Looks for pattern: 10=XXX<SOH> where XXX is 3 digits (0-255).
        Searches left to right for multi-message support.

        Returns:
            Index after the final SOH, or -1 if not found.
        """
        for pos in range(len(self._buffer) - 6):
            if self._buffer[pos:pos + 3] == b"10=":
                result = self._validate_checksum_at(pos)
                if result is not None:
                    return result
        return -1

    def _validate_checksum_at(self, pos: int) -> int | None:
        """Validate checksum field at given position.

        Format: 10=XXX<SOH>
                ^pos
                |10=     |XXX|SOH|
                |3 bytes |3  |1  |

        Args:
            pos: Position of '10=' in buffer.

        Returns:
            Index after SOH if valid, None otherwise.
        """
        # Need: 10= (3) + digits (3) + SOH (1) = 7 bytes minimum
        if pos + 7 > len(self._buffer):
            return None

        # Verify it's actually 10=
        if self._buffer[pos:pos + 3] != b"10=":
            return None

        # Validate digits are numeric
        digits = self._buffer[pos + 3:pos + 6]
        if not digits.isdigit():
            return None

        # Validate range (checksum is 0-255)
        if int(digits) > 255:
            return None

        # Verify SOH delimiter follows
        if self._buffer[pos + 6] != ord(SOH):
            return None

        return pos + 7

    def _parse_message(self, raw: bytes) -> FIXMessage:
        """Parse a single complete FIX message.

        Args:
            raw: Complete raw message bytes.

        Returns:
            Parsed FIXMessage object.

        Raises:
            FIXParseError: If parsing fails.
        """
        msg = FIXMessage()
        msg._raw = raw

        # Split by SOH
        raw_str = raw.decode("ascii", errors="replace")
        fields = raw_str.split(FIELD_DELIMITER)

        # Parse each field
        body_length = 0
        in_body = False
        tag_count = 0

        for field in fields:
            if not field:
                continue

            # Parse tag=value
            if "=" not in field:
                if self._strict_mode:
                    raise FIXParseError(
                        f"Invalid field format: {field}",
                        raw=raw
                    )
                continue

            try:
                tag_str, value = field.split("=", 1)
                tag = int(tag_str)
            except ValueError as err:
                if self._strict_mode:
                    raise FIXParseError(
                        f"Invalid field: {field!r}",
                        raw=raw
                    ) from err
                continue

            # Validate tag count
            tag_count += 1
            if tag_count > MAX_TAGS_PER_MESSAGE:
                raise FIXParseError(
                    f"Too many tags: {tag_count}",
                    raw=raw
                )

            # Handle special tags
            if tag == 8:  # BeginString
                if not value.startswith("FIX."):
                    raise FIXParseError(
                        f"Invalid BeginString: {value}",
                        raw=raw,
                        tag=8
                    )
                msg[8] = value
                continue

            if tag == 9:  # BodyLength
                body_length = int(value)
                msg[9] = value
                in_body = True
                continue

            if tag == 10:  # CheckSum
                msg[10] = value
                # Validate checksum
                self._validate_checksum(raw, value)
                continue

            # All other tags are in the body
            if in_body:
                msg[tag] = value

        if tag_count == 0:
            raise FIXParseError("Empty message", raw=raw)

        return msg

    def _validate_checksum(self, raw: bytes, expected_checksum: str) -> None:
        """Validate message checksum.

        Args:
            raw: Complete raw message bytes.
            expected_checksum: Expected checksum value.

        Raises:
            FIXParseError: If checksum doesn't match.
        """
        # Find position of 10=
        idx = raw.rfind(b"10=")
        if idx == -1:
            if self._strict_mode:
                raise FIXParseError("No checksum tag found", raw=raw)
            return

        # Calculate checksum of all bytes before tag 10
        calculated = sum(raw[:idx]) % 256
        expected = int(expected_checksum)

        if calculated != expected:
            raise FIXParseError(
                f"Checksum mismatch: calculated={calculated}, expected={expected}",
                raw=raw,
                tag=10
            )

    def validate_message(self, msg: FIXMessage) -> list[str]:
        """Validate a FIX message.

        Args:
            msg: Message to validate.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []

        # Check required tags
        if not msg.has(8):
            errors.append("Missing BeginString (tag 8)")
        if not msg.has(9):
            errors.append("Missing BodyLength (tag 9)")
        if not msg.has(35):
            errors.append("Missing MsgType (tag 35)")
        if not msg.has(49):
            errors.append("Missing SenderCompID (tag 49)")
        if not msg.has(56):
            errors.append("Missing TargetCompID (tag 56)")
        if not msg.has(34):
            errors.append("Missing MsgSeqNum (tag 34)")
        if not msg.has(52):
            errors.append("Missing SendingTime (tag 52)")
        if not msg.has(10):
            errors.append("Missing CheckSum (tag 10)")

        # Validate sequence number
        if msg.has(34):
            seq = msg.get_int(34)
            if seq < 1:
                errors.append(f"Invalid MsgSeqNum: {seq}")

        # Validate BeginString
        if msg.has(8):
            begin_string = msg.get(8)
            if begin_string not in ("FIX.4.2", "FIX.4.4", "FIXT.1.1"):
                errors.append(f"Unsupported BeginString: {begin_string}")

        return errors

    def reset(self) -> None:
        """Reset parser state (clear buffer)."""
        self._buffer.clear()

    @property
    def buffer_size(self) -> int:
        """Current buffer size."""
        return len(self._buffer)
