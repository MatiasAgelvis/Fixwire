"""FIX Session - Manages FIX session state and protocol.

Handles logon, logout, heartbeat, and sequence number management.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.message import FIXMessage
from fixwire.core.parser import FIXParser

logger = structlog.get_logger()


class SessionStatus(StrEnum):
    """FIX Session Statuses."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    WAITING_LOGON = "waiting_logon"
    LOGGED_ON = "logged_on"
    WAITING_LOGOUT = "waiting_logout"
    ERROR = "error"


@dataclass
class SessionConfig:
    """FIX Session Configuration."""
    sender_comp_id: str
    target_comp_id: str
    heartbeat_interval: int = 30
    logon_timeout: int = 10
    logout_timeout: int = 10
    reset_seq_num: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class _SessionState:
    """FIX Session Internal State."""
    status: SessionStatus = SessionStatus.DISCONNECTED
    incoming_seq_num: int = 0
    outgoing_seq_num: int = 0
    last_received_time: datetime | None = None
    last_sent_time: datetime | None = None
    test_request_id: str | None = None
    test_request_time: datetime | None = None
    logon_time: datetime | None = None


class FIXSession:
    """FIX Session Manager.

    Manages the FIX session lifecycle including logon, logout, heartbeat,
    and sequence number tracking.

    Usage:
        session = FIXSession(config)
        await session.connect()
        await session.send(message)
        await session.disconnect()
    """

    def __init__(self, config: SessionConfig) -> None:
        self.config = config
        self.parser = FIXParser()
        self.factory = FIXMessageFactory()
        self._state = _SessionState()
        self._send_queue: asyncio.Queue[FIXMessage] = asyncio.Queue()
        self._receive_callbacks: list[Callable[[FIXMessage], Any]] = []
        self._heartbeat_task: asyncio.Task | None = None
        self._connect_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        """Check if session is logged on."""
        return self._state.status == SessionStatus.LOGGED_ON

    @property
    def status(self) -> SessionStatus:
        """Get current session status."""
        return self._state.status

    @status.setter
    def status(self, value: SessionStatus) -> None:
        """Set session status."""
        old_status = self._state.status
        self._state.status = value
        if old_status != value:
            logger.info("session.state_change",
                       old=old_status,
                       new=value,
                       sender=self.config.sender_comp_id,
                       target=self.config.target_comp_id)

    def on_message(self, callback: Callable[[FIXMessage], Any]) -> None:
        """Register callback for received messages."""
        self._receive_callbacks.append(callback)

    def _next_seq_num(self) -> int:
        """Get next outgoing sequence number."""
        self._state.outgoing_seq_num += 1
        return self._state.outgoing_seq_num

    async def send(self, msg: FIXMessage) -> None:
        """Send a FIX message.

        Args:
            msg: Message to send (seq num and timestamps will be set automatically).
        """
        # Set session fields
        msg.sender = self.config.sender_comp_id
        msg.target = self.config.target_comp_id
        msg.sequence = self._next_seq_num()
        msg.sending_time = datetime.utcnow()

        # Serialize and queue for sending
        await self._send_queue.put(msg)

        self._state.last_sent_time = datetime.utcnow()
        logger.debug("session.message_sent",
                    msg_type=msg.msg_type,
                    seq=msg.sequence)

    async def send_raw(self, raw: bytes) -> None:
        """Send raw bytes (for serialization-only messages)."""
        await self._send_queue.put(raw)  # type: ignore

    async def receive(self, data: bytes) -> list[FIXMessage]:
        """Process received raw data.

        Args:
            data: Raw bytes received from wire.

        Returns:
            List of parsed messages.
        """
        messages = self.parser.parse(data)

        for msg in messages:
            await self._handle_message(msg)

        return messages

    async def _handle_message(self, msg: FIXMessage) -> None:
        """Handle a received message.

        Args:
            msg: Parsed FIX message.
        """
        self._state.last_received_time = datetime.utcnow()
        msg_type = msg.msg_type

        logger.debug("session.message_received",
                    msg_type=msg_type,
                    seq=msg.sequence)

        # Session level messages
        if msg_type == "A":  # Logon
            await self._handle_logon(msg)
        elif msg_type == "5":  # Logout
            await self._handle_logout(msg)
        elif msg_type == "0":  # Heartbeat
            await self._handle_heartbeat(msg)
        elif msg_type == "1":  # TestRequest
            await self._handle_test_request(msg)
        elif msg_type == "2":  # ResendRequest
            await self._handle_resend_request(msg)
        elif msg_type == "3":  # Reject
            await self._handle_reject(msg)
        elif msg_type == "4":  # SequenceReset
            await self._handle_sequence_reset(msg)

        # Notify callbacks
        for callback in self._receive_callbacks:
            try:
                result = callback(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("session.callback_error",
                           error=str(e),
                           msg_type=msg_type)

    async def _handle_logon(self, msg: FIXMessage) -> None:
        """Handle Logon message."""
        if self.status == SessionStatus.WAITING_LOGON:
            # We initiated logon, received response
            self.status = SessionStatus.LOGGED_ON
            self._state.logon_time = datetime.utcnow()
            logger.info("session.logon_success",
                       sender=self.config.sender_comp_id,
                       target=self.config.target_comp_id)
        elif self.status in (SessionStatus.DISCONNECTED, SessionStatus.CONNECTING):
            # We received logon, need to respond
            self.status = SessionStatus.WAITING_LOGON
            self._state.incoming_seq_num = msg.sequence - 1

            # Send logon response using factory
            response = FIXMessageFactory.create_logon(
                sender=self.config.sender_comp_id,
                target=self.config.target_comp_id,
                seq=0,  # Will be set by send()
                heartbeat_interval=self.config.heartbeat_interval
            )
            await self.send(response)

            self.status = SessionStatus.LOGGED_ON
            self._state.logon_time = datetime.utcnow()
            logger.info("session.logon_received",
                       sender=msg.sender,
                       target=msg.target)

    async def _handle_logout(self, msg: FIXMessage) -> None:
        """Handle Logout message."""
        if self.status == SessionStatus.WAITING_LOGOUT:
            # We initiated logout, received response
            self.status = SessionStatus.DISCONNECTED
            logger.info("session.logout_complete")
        else:
            # We received logout request, send response
            response = FIXMessage()
            response.msg_type = "5"
            await self.send(response)
            self.status = SessionStatus.DISCONNECTED
            logger.info("session.logout_received")

    async def _handle_heartbeat(self, msg: FIXMessage) -> None:
        """Handle Heartbeat message."""
        # Check if this is response to our TestRequest
        if (self._state.test_request_id and
            msg.get(112) == self._state.test_request_id):
            self._state.test_request_id = None
            self._state.test_request_time = None
            logger.debug("session.heartbeat_test_response_received")

    async def _handle_test_request(self, msg: FIXMessage) -> None:
        """Handle TestRequest message."""
        test_req_id = msg.get(112)
        if test_req_id:
            # Respond with Heartbeat containing TestReqID
            heartbeat = FIXMessageFactory.create_heartbeat(
                sender=self.config.sender_comp_id,
                target=self.config.target_comp_id,
                seq=0,  # Will be set by send()
                test_req_id=test_req_id
            )
            await self.send(heartbeat)

    async def _handle_resend_request(self, msg: FIXMessage) -> None:
        """Handle ResendRequest message."""
        begin_seq = msg.begin_sequence_number
        end_seq = msg.end_sequence_number

        logger.info("session.resend_request",
                   begin=begin_seq,
                   end=end_seq)

        # For now, send SequenceReset-GapFill
        # TODO: Implement actual message resend
        new_seq = end_seq + 1 if end_seq > 0 else self._state.outgoing_seq_num + 1
        seq_reset = FIXMessage()
        seq_reset.msg_type = "4"
        seq_reset.set(36, str(new_seq))
        seq_reset.set(123, "Y")  # GapFillFlag
        await self.send(seq_reset)

    async def _handle_reject(self, msg: FIXMessage) -> None:
        """Handle Reject message."""
        ref_seq = msg.reference_sequence_number
        reason = msg.reject_reason
        text = msg.text

        logger.warning("session.rejected",
                      ref_seq=ref_seq,
                      reason=reason,
                      text=text)

    async def _handle_sequence_reset(self, msg: FIXMessage) -> None:
        """Handle SequenceReset message."""
        new_seq = msg.new_sequence_number
        gap_fill = msg.gap_fill_flag

        if gap_fill:
            # GapFill - skip messages
            self._state.incoming_seq_num = new_seq - 1
            logger.info("session.gap_fill",
                       new_seq=new_seq)
        else:
            # SequenceReset - reset to new value
            self._state.incoming_seq_num = new_seq - 1
            logger.info("session.sequence_reset",
                       new_seq=new_seq)

    async def connect(self) -> None:
        """Initiate session connection and logon."""
        self.status = SessionStatus.CONNECTING
        self._state.outgoing_seq_num = 0
        self._state.incoming_seq_num = 0

        if self.config.reset_seq_num:
            self._state.outgoing_seq_num = 0
            self._state.incoming_seq_num = 0

        # Send logon using factory
        logon = FIXMessageFactory.create_logon(
            sender=self.config.sender_comp_id,
            target=self.config.target_comp_id,
            seq=0,  # Will be set by send()
            heartbeat_interval=self.config.heartbeat_interval,
            reset_seq_num=self.config.reset_seq_num
        )
        await self.send(logon)
        self.status = SessionStatus.WAITING_LOGON

        # Start heartbeat monitor
        self._start_heartbeat_monitor()

    async def disconnect(self) -> None:
        """Initiate session logout and disconnect."""
        if self.status != SessionStatus.LOGGED_ON:
            self.status = SessionStatus.DISCONNECTED
            return

        self.status = SessionStatus.WAITING_LOGOUT

        # Send logout using factory
        logout = FIXMessageFactory.create_logout(
            sender=self.config.sender_comp_id,
            target=self.config.target_comp_id,
            seq=0  # Will be set by send()
        )
        await self.send(logout)

        # Stop heartbeat monitor
        self._stop_heartbeat_monitor()

        # Wait for logout response or timeout
        try:
            await asyncio.wait_for(
                self._wait_for_status(SessionStatus.DISCONNECTED),
                timeout=self.config.logout_timeout
            )
        except TimeoutError:
            logger.warning("session.logout_timeout")
            self.status = SessionStatus.DISCONNECTED

    async def _wait_for_status(self, target_status: SessionStatus) -> None:
        """Wait until session reaches target status."""
        while self.status != target_status:
            await asyncio.sleep(0.1)

    def _start_heartbeat_monitor(self) -> None:
        """Start heartbeat monitoring task."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())

    def _stop_heartbeat_monitor(self) -> None:
        """Stop heartbeat monitoring task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _heartbeat_monitor(self) -> None:
        """Monitor heartbeats and send test requests if needed."""
        while True:
            await asyncio.sleep(self.config.heartbeat_interval)

            if self.status != SessionStatus.LOGGED_ON:
                break

            # Check if we received anything recently
            now = datetime.utcnow()
            if self._state.last_received_time:
                time_since_last = (now - self._state.last_received_time).total_seconds()
            else:
                time_since_last = self.config.heartbeat_interval * 2

            # Send TestRequest if no messages received
            if time_since_last >= self.config.heartbeat_interval:
                if self._state.test_request_id:
                    # Previous test request not answered
                    logger.warning("session.heartbeat_timeout")
                    self.status = SessionStatus.ERROR
                    break

                # Send test request
                test_req_id = f"{self.config.sender_comp_id}-{int(now.timestamp())}"
                self._state.test_request_id = test_req_id
                self._state.test_request_time = now

                test_req = FIXMessage()
                test_req.msg_type = "1"
                test_req.set(112, test_req_id)
                await self.send(test_req)

    def get_next_expected_seq_num(self) -> int:
        """Get next expected incoming sequence number."""
        return self._state.incoming_seq_num + 1

    def get_next_send_seq_num(self) -> int:
        """Get next outgoing sequence number."""
        return self._state.outgoing_seq_num + 1

    def reset_sequence_numbers(self) -> None:
        """Reset both incoming and outgoing sequence numbers."""
        self._state.incoming_seq_num = 0
        self._state.outgoing_seq_num = 0
        logger.info("session.sequences_reset")
