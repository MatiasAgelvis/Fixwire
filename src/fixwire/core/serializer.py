"""FIX Serializer - Serialize FIXMessage objects to wire format.

Converts FIXMessage objects to bytes for transmission.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from fixwire.core.message import SOH, FIXMessage

logger = structlog.get_logger()


class FIXSerializer:
    """FIX Protocol Serializer.

    Serializes FIXMessage objects to wire format bytes.

    Usage:
        serializer = FIXSerializer()
        raw = serializer.serialize(message)
        # raw is ready to send over the wire
    """

    def __init__(self, version: str = "FIX.4.4") -> None:
        """Initialize serializer.

        Args:
            version: FIX version string (default: FIX.4.4)
        """
        self.version = version

    def serialize(self, msg: FIXMessage) -> bytes:
        """Serialize a FIX message to wire format.

        Args:
            msg: FIXMessage to serialize.

        Returns:
            Complete FIX message bytes ready for transmission.

        Note:
            - BodyLength (tag 9) and CheckSum (tag 10) are calculated automatically
            - SendingTime (tag 52) is set to current UTC time if not already set
        """
        # Set sending time if not set
        if 52 not in msg:
            msg.sending_time = datetime.utcnow()

        # Build body (everything except BeginString, BodyLength, CheckSum)
        body_parts = []
        for tag, value in msg.items():
            if tag in (8, 9, 10):
                continue
            body_parts.append(f"{tag}={value}{SOH}")

        body = SOH.join(body_parts) + SOH
        body_bytes = body.encode("ascii")

        # Calculate body length
        body_length = len(body_bytes)

        # Build complete message
        result = bytearray()
        result.extend(f"8={self.version}{SOH}".encode("ascii"))
        result.extend(f"9={body_length}{SOH}".encode("ascii"))
        result.extend(body_bytes)

        # Calculate and add checksum
        checksum = sum(result) % 256
        result.extend(f"10={checksum:03d}{SOH}".encode("ascii"))

        return bytes(result)

    def serialize_batch(self, messages: list[FIXMessage]) -> bytes:
        """Serialize multiple messages to a single byte stream.

        Args:
            messages: List of FIXMessage objects.

        Returns:
            Concatenated serialized messages.
        """
        parts = []
        for msg in messages:
            parts.append(self.serialize(msg))
        return b"".join(parts)

    def create_heartbeat(self, sender: str, target: str, seq: int,
                        test_req_id: str | None = None) -> bytes:
        """Create and serialize a Heartbeat message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            test_req_id: TestReqID (optional, for TestRequest response).

        Returns:
            Serialized Heartbeat message.
        """
        msg = FIXMessage()
        msg.msg_type = "0"
        msg.sender = sender
        msg.target = target
        msg.sequence = seq

        if test_req_id:
            msg.set(112, test_req_id)

        return self.serialize(msg)

    def create_test_request(self, sender: str, target: str, seq: int,
                           test_req_id: str) -> bytes:
        """Create and serialize a TestRequest message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            test_req_id: TestReqID to echo back.

        Returns:
            Serialized TestRequest message.
        """
        msg = FIXMessage()
        msg.msg_type = "1"
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(112, test_req_id)

        return self.serialize(msg)

    def create_logon(self, sender: str, target: str, seq: int,
                    heartbeat_interval: int = 30,
                    reset_seq_num: bool = False) -> bytes:
        """Create and serialize a Logon message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            heartbeat_interval: Heartbeat interval in seconds.
            reset_seq_num: Whether to reset sequence numbers.

        Returns:
            Serialized Logon message.
        """
        msg = FIXMessage()
        msg.msg_type = "A"
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(98, "0")  # EncryptMethod = None
        msg.set(108, str(heartbeat_interval))

        if reset_seq_num:
            msg.set(141, "Y")

        return self.serialize(msg)

    def create_logout(self, sender: str, target: str, seq: int,
                     text: str | None = None) -> bytes:
        """Create and serialize a Logout message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            text: Optional text message.

        Returns:
            Serialized Logout message.
        """
        msg = FIXMessage()
        msg.msg_type = "5"
        msg.sender = sender
        msg.target = target
        msg.sequence = seq

        if text:
            msg.set(58, text)

        return self.serialize(msg)

    def create_reject(self, sender: str, target: str, seq: int,
                     ref_seq_num: int, ref_tag_id: int | None = None,
                     ref_msg_type: str | None = None,
                     session_reject_reason: int | None = None,
                     text: str | None = None) -> bytes:
        """Create and serialize a Reject message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            ref_seq_num: RefSeqNum of rejected message.
            ref_tag_id: RefTagID of problematic tag (optional).
            ref_msg_type: RefMsgType of rejected message (optional).
            session_reject_reason: SessionRejectReason code (optional).
            text: Optional text description.

        Returns:
            Serialized Reject message.
        """
        msg = FIXMessage()
        msg.msg_type = "3"
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(45, str(ref_seq_num))

        if ref_tag_id is not None:
            msg.set(371, str(ref_tag_id))
        if ref_msg_type is not None:
            msg.set(372, ref_msg_type)
        if session_reject_reason is not None:
            msg.set(373, str(session_reject_reason))
        if text:
            msg.set(58, text)

        return self.serialize(msg)

    def create_resend_request(self, sender: str, target: str, seq: int,
                             begin_seq_no: int, end_seq_no: int = 0) -> bytes:
        """Create and serialize a ResendRequest message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            begin_seq_no: BeginSeqNo to request.
            end_seq_no: EndSeqNo (0 = no end, 999999 = up to current).

        Returns:
            Serialized ResendRequest message.
        """
        msg = FIXMessage()
        msg.msg_type = "2"
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(132, str(begin_seq_no))
        msg.set(133, str(end_seq_no))

        return self.serialize(msg)

    def create_sequence_reset(self, sender: str, target: str, seq: int,
                             new_seq_no: int, gap_fill: bool = False) -> bytes:
        """Create and serialize a SequenceReset message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            new_seq_no: NewSeqNo to reset to.
            gap_fill: Whether this is a GapFill (true) or Reset (false).

        Returns:
            Serialized SequenceReset message.
        """
        msg = FIXMessage()
        msg.msg_type = "4"
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(36, str(new_seq_no))

        if gap_fill:
            msg.set(123, "Y")

        return self.serialize(msg)
