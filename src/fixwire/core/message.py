"""FIX Message - Container for FIX protocol messages.

Provides FIXMessage class for building, parsing, and manipulating FIX messages.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from fixwire.core.constants import SOH
from fixwire.core.tags import get_tag_name


class FIXMessage:
    """FIX Message container.

    Stores FIX tag-value pairs and provides methods to access them.
    Maintains tag ordering as per FIX protocol.

    Usage:
        msg = FIXMessage()
        msg[35] = "D"  # MsgType = NewOrderSingle
        msg[49] = "CLIENT01"  # SenderCompID
        msg[55] = "AAPL"  # Symbol

        # Access
        msg.msg_type  # "D"
        msg[55]      # "AAPL"

        # Serialize
        raw = msg.serialize()
    """

    def __init__(self) -> None:
        self._tags: OrderedDict[int, str] = OrderedDict()
        self._raw: bytes | None = None

    def __getitem__(self, tag: int) -> str:
        """Get tag value by tag number."""
        return self._tags[tag]

    def __setitem__(self, tag: int, value: str) -> None:
        """Set tag value by tag number."""
        self._tags[tag] = value

    def __delitem__(self, tag: int) -> None:
        """Remove a tag."""
        del self._tags[tag]

    def __contains__(self, tag: int) -> bool:
        """Check if tag exists."""
        return tag in self._tags

    def __len__(self) -> int:
        """Number of tags (excluding BodyLength and CheckSum)."""
        return len(self._tags)

    def __iter__(self) -> Iterator[int]:
        """Iterate over tag numbers in order."""
        return iter(self._tags.keys())

    def __repr__(self) -> str:
        """String representation showing key tags."""
        msg_type = self._tags.get(35, "?")
        sender = self._tags.get(49, "?")
        target = self._tags.get(56, "?")
        seq = self._tags.get(34, "?")
        return f"FIXMessage(type={msg_type}, sender={sender}, target={target}, seq={seq})"

    def __str__(self) -> str:
        """Human-readable representation."""
        lines = []
        for tag, value in self._tags.items():
            name = get_tag_name(tag)
            lines.append(f"  {tag}={name}: {value}")
        return "\n".join(lines)

    @property
    def msg_type(self) -> str:
        """Get message type (Tag 35)."""
        return self._tags.get(35, "")

    @msg_type.setter
    def msg_type(self, value: str) -> None:
        """Set message type (Tag 35)."""
        self._tags[35] = value

    @property
    def sender(self) -> str:
        """Get sender (Tag 49)."""
        return self._tags.get(49, "")

    @sender.setter
    def sender(self, value: str) -> None:
        """Set sender (Tag 49)."""
        self._tags[49] = value

    @property
    def target(self) -> str:
        """Get target (Tag 56)."""
        return self._tags.get(56, "")

    @target.setter
    def target(self, value: str) -> None:
        """Set target (Tag 56)."""
        self._tags[56] = value

    @property
    def sequence(self) -> int:
        """Get sequence number (Tag 34)."""
        return int(self._tags.get(34, 0))

    @sequence.setter
    def sequence(self, value: int) -> None:
        """Set sequence number (Tag 34)."""
        self._tags[34] = str(value)

    @property
    def sending_time(self) -> datetime | None:
        """Get sending time (Tag 52)."""
        raw = self._tags.get(52, "")
        if raw:
            try:
                return datetime.strptime(raw, "%Y%m%d-%H:%M:%S.%f")
            except ValueError:
                try:
                    return datetime.strptime(raw, "%Y%m%d-%H:%M:%S")
                except ValueError:
                    return None
        return None

    @sending_time.setter
    def sending_time(self, value: datetime) -> None:
        """Set sending time (Tag 52)."""
        self._tags[52] = value.strftime("%Y%m%d-%H:%M:%S.%f")[:-3]

    def get(self, tag: int, default: str = "") -> str:
        """Get tag value with default."""
        return self._tags.get(tag, default)

    def get_int(self, tag: int, default: int = 0) -> int:
        """Get tag value as integer."""
        try:
            return int(self._tags[tag])
        except (KeyError, ValueError):
            return default

    def get_float(self, tag: int, default: float = 0.0) -> float:
        """Get tag value as float."""
        try:
            return float(self._tags[tag])
        except (KeyError, ValueError):
            return default

    def set(self, tag: int, value: Any) -> None:
        """Set tag value (converts to string)."""
        self._tags[tag] = str(value)

    def has(self, tag: int) -> bool:
        """Check if tag exists."""
        return tag in self._tags

    def items(self) -> list[tuple[int, str]]:
        """Get all tag-value pairs."""
        return list(self._tags.items())

    def tags(self) -> list[int]:
        """Get all tag numbers."""
        return list(self._tags.keys())

    def values(self) -> list[str]:
        """Get all tag values."""
        return list(self._tags.values())

    def serialize(self) -> bytes:
        """Serialize message to FIX wire format.

        Returns:
            Complete FIX message bytes with BodyLength and CheckSum.

        Note:
            BodyLength (tag 9) and CheckSum (tag 10) are calculated automatically.
            SendingTime (tag 52) is set to current time if not set.
        """
        # Set sending time if not set
        if 52 not in self._tags:
            self.sending_time = datetime.now()

        # Build body (everything after BodyLength)
        body_parts = []
        for tag, value in self._tags.items():
            if tag in (9, 10):  # Skip BodyLength and CheckSum
                continue
            body_parts.append(f"{tag}={value}{SOH}")

        body = SOH.join(body_parts) + SOH
        body_bytes = body.encode("ascii")

        # Calculate BodyLength (length of body from tag 35 to before tag 10)
        body_length = len(body_bytes)

        # Insert BodyLength after BeginString
        # Find position after first SOH (after 8=FIX.4.4)
        result = bytearray()
        result.extend(f"8=FIX.4.4{SOH}".encode("ascii"))
        result.extend(f"9={body_length}{SOH}".encode("ascii"))
        result.extend(body_bytes)

        # Calculate checksum
        checksum = sum(result) % 256
        result.extend(f"10={checksum:03d}{SOH}".encode("ascii"))

        self._raw = bytes(result)
        return self._raw

    def body_length(self) -> int:
        """Calculate body length for current message state."""
        # Body is everything between BodyLength and CheckSum tags
        body_parts = []
        for tag, value in self._tags.items():
            if tag in (9, 10):
                continue
            body_parts.append(f"{tag}={value}{SOH}")

        body = SOH.join(body_parts) + SOH
        return len(body.encode("ascii"))

    def checksum(self) -> int:
        """Calculate checksum for current message state."""
        raw = self.serialize()
        # Checksum is sum of all bytes before tag 10
        # Find position of 10=
        idx = raw.rfind(b"10=")
        if idx == -1:
            return 0
        return sum(raw[:idx]) % 256

    def copy(self) -> FIXMessage:
        """Create a copy of this message."""
        new_msg = FIXMessage()
        new_msg._tags = self._tags.copy()
        return new_msg

    def clear(self) -> None:
        """Clear all tags."""
        self._tags.clear()
        self._raw = None

    def to_dict(self) -> dict[int, str]:
        """Convert to dictionary."""
        return dict(self._tags)

    def to_debug_string(self) -> str:
        """Debug-friendly string representation."""
        parts = []
        for tag, value in self._tags.items():
            name = get_tag_name(tag)
            parts.append(f"{tag} ({name}) = {value}")
        return "\n".join(parts)

    @classmethod
    def from_dict(cls, data: dict[int, str]) -> FIXMessage:
        """Create message from dictionary."""
        msg = cls()
        for tag, value in data.items():
            msg[tag] = str(value)
        return msg

    # Convenience properties for common tags
    # --- Order Identifiers ---

    @property
    def client_order_id(self) -> str:
        """Client-assigned unique order identifier (Tag 11)."""
        return self.get(11)

    @property
    def order_id(self) -> str:
        """Exchange-assigned order identifier (Tag 37)."""
        return self.get(37)

    @property
    def execution_id(self) -> str:
        """Unique execution event identifier (Tag 17)."""
        return self.get(17)

    @property
    def original_client_order_id(self) -> str:
        """Original ClOrdID before a cancel/replace (Tag 41)."""
        return self.get(41)

    # --- Order Details ---

    @property
    def symbol(self) -> str:
        """Instrument ticker symbol, e.g. AAPL (Tag 55)."""
        return self.get(55)

    @property
    def side(self) -> str:
        """Order side: 1=Buy, 2=Sell (Tag 54)."""
        return self.get(54)

    @property
    def order_quantity(self) -> float:
        """Requested order quantity (Tag 38)."""
        return self.get_float(38)

    @property
    def price(self) -> float:
        """Price set by the client for the order (Tag 44)."""
        return self.get_float(44)

    @property
    def order_type(self) -> str:
        """Order type: 1=Market, 2=Limit, 3=Stop, etc. (Tag 40)."""
        return self.get(40)

    @property
    def time_in_force(self) -> str:
        """How long the order stays active: 0=Day, 1=GTC, 3=IOC, 4=FOK (Tag 59)."""
        return self.get(59)

    @property
    def account(self) -> str:
        """Trading account identifier (Tag 1)."""
        return self.get(1)

    # --- Execution / Fill Info ---

    @property
    def order_status(self) -> str:
        """Current order status: 0=New, 1=Partial, 2=Filled, 4=Cancelled, etc. (Tag 39)."""
        return self.get(39)

    @property
    def execution_type(self) -> str:
        """Type of execution event: 0=New, 1=Partial Fill, 2=Fill, etc. (Tag 150)."""
        return self.get(150)

    @property
    def last_fill_quantity(self) -> float:
        """Quantity filled on this specific fill (Tag 32)."""
        return self.get_float(32)

    @property
    def last_fill_price(self) -> float:
        """Price of this specific fill (Tag 31)."""
        return self.get_float(31)

    @property
    def filled_quantity(self) -> float:
        """Cumulative quantity filled across all fills (Tag 14)."""
        return self.get_float(14)

    @property
    def average_price(self) -> float:
        """Volume-weighted average price of all fills (Tag 6)."""
        return self.get_float(6)

    @property
    def remaining_quantity(self) -> float:
        """Quantity still working / not yet filled (Tag 151)."""
        return self.get_float(151)

    # --- Session / Protocol ---

    @property
    def message_type(self) -> str:
        """FIX message type code, e.g. D=NewOrderSingle (Tag 35)."""
        return self.get(35)

    @property
    def heartbeat_interval(self) -> int:
        """Heartbeat interval in seconds (Tag 108)."""
        return self.get_int(108)

    @property
    def test_request_id(self) -> str:
        """Identifier echoed back in Heartbeat responses (Tag 112)."""
        return self.get(112)

    @property
    def reset_sequence_numbers(self) -> bool:
        """Whether to reset sequence numbers on logon (Tag 141)."""
        return self.get(141) == "Y"

    # --- Sequence / Resend ---

    @property
    def begin_sequence_number(self) -> int:
        """First sequence number in range request (Tag 132)."""
        return self.get_int(132)

    @property
    def end_sequence_number(self) -> int:
        """Last sequence number in range request (Tag 133)."""
        return self.get_int(133)

    @property
    def new_sequence_number(self) -> int:
        """New sequence number after reset (Tag 36)."""
        return self.get_int(36)

    @property
    def gap_fill_flag(self) -> bool:
        """Whether SequenceReset is a gap fill vs true reset (Tag 123)."""
        return self.get(123) == "Y"

    # --- Reject Info ---

    @property
    def reference_sequence_number(self) -> int:
        """Sequence number of the message being rejected (Tag 45)."""
        return self.get_int(45)

    @property
    def reference_tag_id(self) -> int:
        """Tag number that caused the rejection (Tag 371)."""
        return self.get_int(371)

    @property
    def reference_message_type(self) -> str:
        """Message type of the rejected message (Tag 372)."""
        return self.get(372)

    @property
    def reject_reason(self) -> int:
        """Session-level reject reason code (Tag 373)."""
        return self.get_int(373)

    # --- Misc ---

    @property
    def text(self) -> str:
        """Free-form text message, e.g. reject reason description (Tag 58)."""
        return self.get(58)
