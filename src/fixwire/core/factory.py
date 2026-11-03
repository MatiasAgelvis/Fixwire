"""FIX Message Factory - Create common FIX message types.

Provides factory methods for creating pre-configured FIXMessage objects.
"""

from __future__ import annotations

import structlog

from fixwire.core.message import FIXMessage
from fixwire.core.tags import MsgType, Tags

logger = structlog.get_logger()


class FIXMessageFactory:
    """Factory for creating common FIX messages.

    Usage:
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 1)
        raw = msg.serialize()
    """

    @staticmethod
    def create_heartbeat(sender: str, target: str, seq: int,
                        test_req_id: str | None = None) -> FIXMessage:
        """Create a Heartbeat message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            test_req_id: TestReqID (optional, for TestRequest response).

        Returns:
            Configured FIXMessage.
        """
        msg = FIXMessage()
        msg.msg_type = MsgType.HEARTBEAT
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        if test_req_id:
            msg.set(Tags.TEST_REQ_ID, test_req_id)
        return msg

    @staticmethod
    def create_test_request(sender: str, target: str, seq: int,
                           test_req_id: str) -> FIXMessage:
        """Create a TestRequest message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            test_req_id: TestReqID to echo back.

        Returns:
            Configured FIXMessage.
        """
        msg = FIXMessage()
        msg.msg_type = MsgType.TEST_REQUEST
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(Tags.TEST_REQ_ID, test_req_id)
        return msg

    @staticmethod
    def create_logon(sender: str, target: str, seq: int,
                    heartbeat_interval: int = 30,
                    reset_seq_num: bool = False) -> FIXMessage:
        """Create a Logon message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            heartbeat_interval: Heartbeat interval in seconds.
            reset_seq_num: Whether to reset sequence numbers.

        Returns:
            Configured FIXMessage.
        """
        msg = FIXMessage()
        msg.msg_type = MsgType.LOGON
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(Tags.ENCRYPT_METHOD, "0")  # EncryptMethod = None
        msg.set(Tags.HEART_BT_INT, str(heartbeat_interval))
        if reset_seq_num:
            msg.set(Tags.RESET_SEQ_NUM_FLAG, "Y")
        return msg

    @staticmethod
    def create_logout(sender: str, target: str, seq: int,
                     text: str | None = None) -> FIXMessage:
        """Create a Logout message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            text: Optional text message.

        Returns:
            Configured FIXMessage.
        """
        msg = FIXMessage()
        msg.msg_type = MsgType.LOGOUT
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        if text:
            msg.set(Tags.TEXT, text)
        return msg

    @staticmethod
    def create_reject(sender: str, target: str, seq: int,
                     ref_seq_num: int, ref_tag_id: int | None = None,
                     ref_msg_type: str | None = None,
                     session_reject_reason: int | None = None,
                     text: str | None = None) -> FIXMessage:
        """Create a Reject message.

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
            Configured FIXMessage.
        """
        msg = FIXMessage()
        msg.msg_type = MsgType.REJECT
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(Tags.REF_SEQ_NUM, str(ref_seq_num))
        if ref_tag_id is not None:
            msg.set(Tags.REF_TAG_ID, str(ref_tag_id))
        if ref_msg_type is not None:
            msg.set(Tags.REF_MSG_TYPE, ref_msg_type)
        if session_reject_reason is not None:
            msg.set(Tags.SESSION_REJECT_REASON, str(session_reject_reason))
        if text:
            msg.set(Tags.TEXT, text)
        return msg

    @staticmethod
    def create_resend_request(sender: str, target: str, seq: int,
                             begin_seq_no: int, end_seq_no: int = 0) -> FIXMessage:
        """Create a ResendRequest message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            begin_seq_no: BeginSeqNo to request.
            end_seq_no: EndSeqNo (0 = no end, 999999 = up to current).

        Returns:
            Configured FIXMessage.
        """
        msg = FIXMessage()
        msg.msg_type = MsgType.RESEND_REQUEST
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(Tags.BEGIN_SEQ_NO, str(begin_seq_no))
        msg.set(Tags.END_SEQ_NO, str(end_seq_no))
        return msg

    @staticmethod
    def create_sequence_reset(sender: str, target: str, seq: int,
                             new_seq_no: int, gap_fill: bool = False) -> FIXMessage:
        """Create a SequenceReset message.

        Args:
            sender: SenderCompID.
            target: TargetCompID.
            seq: Sequence number.
            new_seq_no: NewSeqNo to reset to.
            gap_fill: Whether this is a GapFill (true) or Reset (false).

        Returns:
            Configured FIXMessage.
        """
        msg = FIXMessage()
        msg.msg_type = MsgType.SEQUENCE_RESET
        msg.sender = sender
        msg.target = target
        msg.sequence = seq
        msg.set(Tags.NEW_SEQ_NO, str(new_seq_no))
        if gap_fill:
            msg.set(Tags.GAP_FILL_FLAG, "Y")
        return msg
