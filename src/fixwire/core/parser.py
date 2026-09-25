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

    Args:
        strict: If True, enables strict validation of checksum and message size.
    Usage:
        parser = FIXParser()
        messages = parser.parse(raw_bytes)
        for msg in messages:
            print(msg.msg_type, msg.sender, msg.target)
    """

    def __init__(self, strict: bool = True) -> None:
        self._buffer = bytearray()
        self._strict = strict  # Enable strict validation

    @property
    def strict(self) -> bool:
        """Get strict mode status."""
        return self._strict

    @strict.setter
    def strict(self, value: bool) -> None:
        """Set strict mode status."""
        self._strict = value

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

    def _handle_no_fix_start(self) -> FIXMessage | None:
        """Handle buffer that doesn't start with 8=FIX.

        Returns:
            None always (no valid message found)
        """
        # Check for invalid BeginString (8=non-FIX)
        if len(self._buffer) > 3 and self._buffer[:2] == b"8=":
            if self._strict:
                begin_string = self._buffer.split(SOH.encode())[0].decode(errors="replace")
                raise FIXParseError(
                    f"Invalid BeginString: {begin_string}",
                    raw=bytes(self._buffer),
                    tag=8
                )
            logger.warning("parser.invalid_begin_string", raw=bytes(self._buffer[:50]))
            # Skip to next SOH and continue
            next_soh = self._buffer.find(SOH.encode())
            if next_soh != -1:
                self._buffer = self._buffer[next_soh + 1:]
            else:
                self._buffer.clear()
            return None

        # Keep only last few bytes for partial message detection
        if len(self._buffer) > 10:
            self._buffer = self._buffer[-10:]
        return None

    def _try_parse_message(self) -> FIXMessage | None:
        """Try to parse a single message from buffer.

        Returns:
            FIXMessage if complete message found, None otherwise.
        """
        # Find start of message (8=FIX)
        start = self._buffer.find(b"8=FIX")
        if start == -1:
            return self._handle_no_fix_start()

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
            if self._strict:
                raise
            logger.warning("parse.error", error=str(e), raw=raw_msg[:100])
            return None

    def _handle_special_tag(self, tag: int, value: str, msg: FIXMessage, raw: bytes) -> tuple[int, bool] | None:
        """Handle special tags (BeginString, BodyLength, CheckSum).

        Args:
            tag: Tag number.
            value: Tag value.
            msg: Message being built.
            raw: Raw message bytes.

        Returns:
            Tuple of (body_length, in_body) if special tag handled, None otherwise.

        Raises:
            FIXParseError: If invalid BeginString.
        """
        if tag == 8:  # BeginString
            if not value.startswith("FIX."):
                raise FIXParseError(
                    f"Invalid BeginString: {value}",
                    raw=raw,
                    tag=8
                )
            msg[8] = value
            return 0, False

        if tag == 9:  # BodyLength
            body_length = int(value)
            msg[9] = value
            return body_length, True

        if tag == 10:  # CheckSum
            msg[10] = value
            self.validate_checksum(raw)  # Raises in strict, returns bool in non-strict
            return 0, False

        return None

    def _validate_required_tags(self, msg: FIXMessage, raw: bytes) -> None:
        """Validate that required tags are present.

        Args:
            msg: Parsed message.
            raw: Raw message bytes (for error reporting).

        Raises:
            FIXParseError: If required tag is missing.
        """
        # Always required tags
        required_tags = [
            (8, "BeginString"),
            (9, "BodyLength"),
            (35, "MsgType"),
            (49, "SenderCompID"),
            (56, "TargetCompID"),
            (34, "MsgSeqNum"),
            (52, "SendingTime"),
            (10, "CheckSum"),
        ]

        for tag, name in required_tags:
            if not msg.has(tag):
                raise FIXParseError(
                    f"Missing required tag: {name} ({tag})",
                    raw=raw,
                    tag=tag
                )

    def _find_message_end(self) -> int:
        """Find the end of a FIX message in the buffer.

        Looks for pattern: 10=XXX<SOH> where XXX is 3 digits (0-255).
        Searches left to right for multi-message support.

        Returns:
            Index after the final SOH, or -1 if not found.
        """
        for pos in range(len(self._buffer) - 6):
            if self._buffer[pos:pos + 3] == b"10=":
                result = self._find_checksum_field(pos)
                if result is not None:
                    return result
        return -1

    def _find_checksum_field(self, pos: int) -> int | None:
        """Find checksum field boundary at given position.

        Validates format only (10=XXX<SOH>), not checksum value.

        Format: 10=XXX<SOH>
                ^pos
                |10=     |XXX|SOH|
                |3 bytes |3  |1  |

        Args:
            pos: Position of '10=' in buffer.

        Returns:
            Index after SOH if valid format, None otherwise.
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
                if self._strict:
                    raise FIXParseError(
                        f"Invalid field format: {field}",
                        raw=raw
                    )
                continue

            try:
                tag_str, value = field.split("=", 1)
                tag = int(tag_str)
            except ValueError as err:
                if self._strict:
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
            result = self._handle_special_tag(tag, value, msg, raw)
            if result is not None:
                body_length, in_body = result
                continue

            # All other tags are in the body
            if in_body:
                msg[tag] = value

        if tag_count == 0:
            raise FIXParseError("Empty message", raw=raw)

        # Validate required tags
        if self._strict:
            self._validate_required_tags(msg, raw)

        return msg

    def validate_checksum(self, raw: bytes) -> bool:
        """Validate message checksum.

        Can be called standalone or during parsing.
        Behavior depends on strict_mode:
        - Strict: raises FIXParseError on invalid checksum
        - Non-strict: logs warning, returns False

        Args:
            raw: Complete raw message bytes.

        Returns:
            True if checksum is valid, False otherwise.

        Raises:
            FIXParseError: If strict mode and checksum invalid.
        """
        # Find position of 10=
        idx = raw.rfind(b"10=")
        if idx == -1:
            if self._strict:
                raise FIXParseError("No checksum tag found", raw=raw)
            logger.warning("parser.no_checksum", raw=raw[:50])
            return False

        # Calculate checksum of all bytes before tag 10
        calculated = sum(raw[:idx]) % 256

        # Extract expected checksum from message
        try:
            extracted = int(raw[idx + 3:idx + 6])
        except (ValueError, IndexError):
            if self._strict:
                raise FIXParseError("Invalid checksum format", raw=raw, tag=10) from None
            logger.warning("parser.invalid_checksum_format", raw=raw[:50])
            return False

        if calculated != extracted:
            if self._strict:
                raise FIXParseError(
                    f"Checksum mismatch: calculated={calculated}, expected={extracted}",
                    raw=raw,
                    tag=10
                )
            logger.warning(
                "parser.checksum_mismatch",
                calculated=calculated,
                extracted=extracted,
            )
            return False

        return True

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
