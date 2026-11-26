"""FIX Session - Manages FIX session state and protocol.

Handles logon, logout, heartbeat, and sequence number management.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog

from fixwire.core.factory import FIXMessageFactory
from fixwire.core.message import FIXMessage
from fixwire.core.outbox import InMemoryOutbox, Outbox
from fixwire.core.parser import FIXParser, ParserConfig
from fixwire.core.sequence import InMemorySequenceStore, SequenceState, SequenceStore
from fixwire.core.tags import MsgType, Tags
from fixwire.core.time import utc_now

logger = structlog.get_logger()


class SessionStatus(StrEnum):
    """FIX Session Statuses."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    WAITING_LOGON = "waiting_logon"
    LOGGED_ON = "logged_on"
    WAITING_LOGOUT = "waiting_logout"
    ERROR = "error"


class SessionNotLoggedOnError(RuntimeError):
    """An application message was queued while the session is not logged on.

    Application traffic is only accepted on a live session. A message
    parked on a dead session would either have to be flushed onto the next
    connection — invalid, because it would precede the Logon — or dropped,
    which loses it silently.
    """


class SessionQueueFullError(RuntimeError):
    """The outbound queue is full, so the message was not accepted.

    Raised instead of blocking: ``send()`` is also called from the reader
    and heartbeat tasks, so waiting would let an application backlog starve
    protocol traffic. The transport is not draining, which means the
    session cannot keep its half of the wire.
    """


# Session-level messages belong to session management and may be queued in
# any state: the handshake has to work before the session is logged on.
_SESSION_LEVEL_MSG_TYPES: frozenset[MsgType] = frozenset({
    MsgType.LOGON,
    MsgType.LOGOUT,
    MsgType.HEARTBEAT,
    MsgType.TEST_REQUEST,
    MsgType.RESEND_REQUEST,
    MsgType.SEQUENCE_RESET,
    MsgType.REJECT,
})


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
    parser: ParserConfig = field(default_factory=ParserConfig)
    # Bounds the queue feeding application callbacks. None means unbounded;
    # 0 and negative are rejected in __post_init__.
    callback_queue_size: int | None = 10_000
    # Bounds the outbound queue. Overflow raises SessionQueueFullError rather
    # than blocking. None means unbounded; 0 and negative are rejected.
    send_queue_size: int | None = 10_000
    # Where sequence numbers live between runs. The default keeps them in
    # memory, so a fresh process legitimately starts at zero.
    sequence_store: SequenceStore = field(
        default_factory=InMemorySequenceStore
    )
    # Where sent messages are kept so a ResendRequest can be answered with
    # real replays. The default keeps them in memory for the session's life.
    outbox: Outbox = field(default_factory=InMemoryOutbox)

    def __post_init__(self) -> None:
        """Reject queue bounds that would silently mean unbounded.

        ``asyncio.Queue(maxsize=0)`` is infinite, so a zero bound would
        disable the limit instead of enforcing it. Unbounded must be written
        as ``None`` so it is a deliberate choice.
        """
        for name in ("callback_queue_size", "send_queue_size"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(
                    f"{name} must be a positive int or None (unbounded); "
                    f"got {value!r}"
                )


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
        self.parser = FIXParser(config.parser)
        self.factory = FIXMessageFactory()
        self._store = config.sequence_store
        self._outbox = config.outbox
        self._state = _SessionState()
        self._send_queue: asyncio.Queue[FIXMessage] = asyncio.Queue(
            maxsize=config.send_queue_size or 0
        )
        self._receive_callbacks: list[Callable[[FIXMessage], Any]] = []
        self._callback_dispatcher: Callable[[FIXMessage], None] | None = None
        self._logon_validators: list[Callable[[FIXMessage], bool]] = []

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

    def set_callback_dispatcher(
        self, dispatcher: Callable[[FIXMessage], None] | None
    ) -> None:
        """Route message notifications through ``dispatcher``.

        The dispatcher must not block: it runs on the receive path, so
        blocking there would stall protocol handling. ``FIXSessionRunner``
        installs one that enqueues onto a dedicated task, so a slow
        application callback degrades itself rather than the session.

        With no dispatcher (standalone use), callbacks are awaited inline.

        A dispatcher may raise to signal that the session cannot continue;
        the exception travels out of ``receive()`` so the caller can tear
        the session down.
        """
        self._callback_dispatcher = dispatcher

    async def notify_callbacks(self, msg: FIXMessage) -> None:
        """Invoke every registered ``on_message`` callback.

        Called inline when no dispatcher is installed; a dispatcher calls
        it from whatever task it owns.
        """
        for callback in self._receive_callbacks:
            try:
                result = callback(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("session.callback_error",
                           error=str(e),
                           msg_type=msg.msg_type)

    def on_logon_request(self, validator: Callable[[FIXMessage], bool]) -> None:
        """Register a validator consulted before accepting an inbound Logon.

        Returning False rejects the session: a Logout is queued and the
        session moves to ERROR. Use this for admission policy such as
        duplicate-session detection.
        """
        self._logon_validators.append(validator)

    def _next_seq_num(self) -> int:
        """Get next outgoing sequence number."""
        self._state.outgoing_seq_num += 1
        return self._state.outgoing_seq_num

    @property
    def _session_key(self) -> tuple[str, str]:
        """Store key: our SenderCompID and the peer we are talking to."""
        return (self.config.sender_comp_id, self.config.target_comp_id)

    async def _restore_sequence(self) -> None:
        """Adopt persisted numbers, if this session has any."""
        state = await self._store.load(self._session_key)
        if state is None:
            return
        self._state.outgoing_seq_num = state.outgoing
        self._state.incoming_seq_num = state.incoming
        logger.info("session.sequence_restored",
                    outgoing=state.outgoing,
                    incoming=state.incoming,
                    sender=self.config.sender_comp_id,
                    target=self.config.target_comp_id)

    async def _persist_sequence(self) -> None:
        """Write the current numbers through to the store."""
        await self._store.save(
            SequenceState(
                sender_comp_id=self.config.sender_comp_id,
                target_comp_id=self.config.target_comp_id,
                outgoing=self._state.outgoing_seq_num,
                incoming=self._state.incoming_seq_num,
            )
        )

    async def send(self, msg: FIXMessage) -> None:
        """Send a FIX message.

        Args:
            msg: Message to send (seq num and timestamps will be set automatically).

        Raises:
            SessionNotLoggedOnError: An application message was queued while
                the session is not logged on. Session-level messages are
                exempt so the handshake can run.
            SessionQueueFullError: The outbound queue is full. The sequence
                number has not been consumed.
        """
        if (
            self.status != SessionStatus.LOGGED_ON
            and msg.msg_type not in _SESSION_LEVEL_MSG_TYPES
        ):
            raise SessionNotLoggedOnError(
                f"Cannot send {msg.msg_type!r} while session is "
                f"{self.status.value}: only session-level messages are "
                "allowed before logon"
            )

        if self._send_queue.full():
            raise SessionQueueFullError(
                f"Outbound queue is full ({self._send_queue.maxsize}); "
                "the transport is not draining"
            )

        # Set session fields
        msg.sender = self.config.sender_comp_id
        msg.target = self.config.target_comp_id
        msg.sequence = self._next_seq_num()
        msg.sending_time = utc_now()

        # Serialize and queue for sending. Safe without awaiting: nothing
        # can interleave between the capacity check and this call.
        #
        # Write-ahead: the number must be durable before the message can
        # leave, and so must a copy of the message itself — otherwise a drop
        # leaves the peer asking for something we cannot replay. If either
        # write fails, the message is not queued.
        payload = msg.serialize()
        await self._persist_sequence()
        await self._outbox.append(self._session_key, msg.sequence, payload)
        self._send_queue.put_nowait(msg)

        self._state.last_sent_time = utc_now()
        logger.debug("session.message_sent",
                    msg_type=msg.msg_type,
                    seq=msg.sequence)

    def pending_send_count(self) -> int:
        """Number of outbound messages queued but not yet written."""
        return self._send_queue.qsize()

    def peek_pending_send(self) -> list[FIXMessage]:
        """Snapshot of the outbound queue, without consuming it.

        ``asyncio.Queue`` has no non-destructive accessor, so this reads its
        internal deque. The session owns the queue and callers run on the
        same event loop, so the snapshot cannot change underneath them.
        """
        return list(getattr(self._send_queue, "_queue"))  # noqa: B009

    async def discard_pending_send(self) -> list[FIXMessage]:
        """Drop queued outbound messages and rewind the sequence baseline.

        The messages were never handed to the transport, so their sequence
        numbers are free to reuse: rewinding stops the peer from seeing a
        gap that would otherwise have to be gap-filled away. The rewound
        value is persisted, otherwise a restart would hand those numbers
        out again.

        Returns:
            The discarded messages, so the caller can report or resubmit
            them.
        """
        discarded: list[FIXMessage] = []
        while True:
            try:
                discarded.append(self._send_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if discarded:
            rewind_to = min(msg.sequence for msg in discarded) - 1
            self._state.outgoing_seq_num = rewind_to
            # Drop the stored copies first: their numbers are about to be
            # reused, and two records for one number would replay twice.
            await self._outbox.truncate(self._session_key, rewind_to)
            await self._persist_sequence()
        return discarded

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
        self._state.last_received_time = utc_now()
        msg_type = msg.msg_type

        logger.debug("session.message_received",
                    msg_type=msg_type,
                    seq=msg.sequence)

        # Verify the incoming sequence before anything else sees the message.
        if not await self._check_incoming_sequence(msg):
            return

        # Session level messages
        if msg_type == MsgType.LOGON:
            await self._handle_logon(msg)
        elif msg_type == MsgType.LOGOUT:
            await self._handle_logout(msg)
        elif msg_type == MsgType.HEARTBEAT:
            await self._handle_heartbeat(msg)
        elif msg_type == MsgType.TEST_REQUEST:
            await self._handle_test_request(msg)
        elif msg_type == MsgType.RESEND_REQUEST:
            await self._handle_resend_request(msg)
        elif msg_type == MsgType.REJECT:
            await self._handle_reject(msg)
        elif msg_type == MsgType.SEQUENCE_RESET:
            await self._handle_sequence_reset(msg)

        # Hand the message to the application. A dispatcher (installed by
        # the runner) keeps slow callbacks off the receive path.
        if self._callback_dispatcher is not None:
            self._callback_dispatcher(msg)
        else:
            await self.notify_callbacks(msg)

    async def _check_incoming_sequence(self, msg: FIXMessage) -> bool:
        """Verify MsgSeqNum (34) against the expected next incoming number.

        Returns True when the message should be dispatched, False when this
        method already handled the condition (gap request, duplicate, or
        session termination).

        Logon and SequenceReset are exempt: they establish or adjust the
        baseline rather than being checked against it. The check only runs
        once the session is logged on, so handshake messages cannot trigger
        a ResendRequest.
        """
        if self.status != SessionStatus.LOGGED_ON:
            return True
        if msg.msg_type in (MsgType.LOGON, MsgType.SEQUENCE_RESET):
            return True

        expected = self.get_next_expected_seq_num()
        received = msg.sequence

        if received == expected:
            self._state.incoming_seq_num = received
            await self._persist_sequence()
            return True

        if received > expected:
            # Gap: ask for the missing range and do not process this message.
            logger.warning("session.sequence_gap",
                           expected=expected,
                           received=received)
            await self._request_resend(expected, received - 1)
            return False

        if msg.get(Tags.POSS_DUP_FLAG) == "Y":  # a retransmission, already seen
            logger.debug("session.duplicate_ignored",
                         expected=expected,
                         received=received)
            return False

        logger.error("session.sequence_too_low",
                     expected=expected,
                     received=received)
        await self._terminate_sequence_too_low(expected, received)
        return False

    async def _request_resend(self, begin: int, end: int) -> None:
        """Queue a ResendRequest for the missing sequence range."""
        request = FIXMessageFactory.create_resend_request(
            sender=self.config.sender_comp_id,
            target=self.config.target_comp_id,
            seq=0,  # Will be set by send()
            begin_seq_no=begin,
            end_seq_no=end,
        )
        await self.send(request)

    async def _terminate_sequence_too_low(
        self, expected: int, received: int
    ) -> None:
        """Terminate the session per FIX 4.4: queue Logout, move to ERROR."""
        logout = FIXMessageFactory.create_logout(
            sender=self.config.sender_comp_id,
            target=self.config.target_comp_id,
            seq=0,  # Will be set by send()
            text=f"MsgSeqNum too low, expecting {expected} but received {received}",
        )
        await self.send(logout)
        self.status = SessionStatus.ERROR

    async def _admit_logon(self, msg: FIXMessage) -> bool:
        """Consult the registered validators before accepting a Logon.

        On rejection, queue a Logout addressed to the peer and move to
        ERROR so the engine tears the connection down.
        """
        for validator in self._logon_validators:
            if not validator(msg):
                logger.warning("session.logon_rejected",
                               sender=msg.sender,
                               target=msg.target)
                logout = FIXMessageFactory.create_logout(
                    sender=self.config.sender_comp_id,
                    target=msg.sender,  # reply to the actual peer
                    seq=0,  # Will be set by send()
                    text="Session already logged on",
                )
                await self.send(logout)
                self.status = SessionStatus.ERROR
                return False
        return True

    async def _handle_logon(self, msg: FIXMessage) -> None:
        """Handle Logon message.

        Both roles consume the Logon, so both set the incoming baseline to
        its MsgSeqNum: the next expected message is ``msg.sequence + 1``.
        """
        if self.status == SessionStatus.WAITING_LOGON:
            # We initiated logon, received response
            self._state.incoming_seq_num = msg.sequence
            self.status = SessionStatus.LOGGED_ON
            self._state.logon_time = utc_now()
            await self._persist_sequence()
            logger.info("session.logon_success",
                       sender=self.config.sender_comp_id,
                       target=self.config.target_comp_id)
        elif self.status in (SessionStatus.DISCONNECTED, SessionStatus.CONNECTING):
            # We received logon, need to respond.
            # The peer's SenderCompID is our TargetCompID: learn it so
            # responses (including a rejection Logout) are addressed
            # correctly instead of to the configured placeholder.
            self.config.target_comp_id = msg.sender
            if not await self._admit_logon(msg):
                return
            self.status = SessionStatus.WAITING_LOGON
            # The peer identity is known now, so persisted numbers can be
            # adopted before the Logon response consumes an outgoing one.
            await self._restore_sequence()
            self._state.incoming_seq_num = msg.sequence

            # Send logon response using factory
            response = FIXMessageFactory.create_logon(
                sender=self.config.sender_comp_id,
                target=self.config.target_comp_id,
                seq=0,  # Will be set by send()
                heartbeat_interval=self.config.heartbeat_interval
            )
            await self.send(response)

            self.status = SessionStatus.LOGGED_ON
            self._state.logon_time = utc_now()
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
            response.msg_type = MsgType.LOGOUT
            await self.send(response)
            self.status = SessionStatus.DISCONNECTED
            logger.info("session.logout_received")

    async def _handle_heartbeat(self, msg: FIXMessage) -> None:
        """Handle Heartbeat message."""
        # Check if this is response to our TestRequest
        if (self._state.test_request_id and
            msg.get(Tags.TEST_REQ_ID) == self._state.test_request_id):
            self._state.test_request_id = None
            self._state.test_request_time = None
            logger.debug("session.heartbeat_test_response_received")

    async def _handle_test_request(self, msg: FIXMessage) -> None:
        """Handle TestRequest message."""
        test_req_id = msg.get(Tags.TEST_REQ_ID)
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
        seq_reset.msg_type = MsgType.SEQUENCE_RESET
        seq_reset.set(Tags.NEW_SEQ_NO, str(new_seq))
        seq_reset.set(Tags.GAP_FILL_FLAG, "Y")
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
        """Handle SequenceReset.

        The two forms differ per FIX 4.4:

        - GapFill (123=Y) may only advance. A stale GapFill is ignored:
          applying it would rewind the incoming sequence and make the next
          real message look like a gap.
        - Reset (123=N) is unconditional and may move backwards, which is
          what makes it usable for administrative recovery.

        ``NewSeqNo`` defaults to 0 when tag 36 is missing or malformed, so
        a non-positive value is treated as a malformed message and dropped
        rather than zeroing the baseline.
        """
        new_seq = msg.new_sequence_number

        if new_seq <= 0:
            logger.warning("session.sequence_reset_malformed",
                           gap_fill=msg.gap_fill_flag,
                           new_seq_no=new_seq)
            return

        if msg.gap_fill_flag:
            expected = self.get_next_expected_seq_num()
            if new_seq <= expected:
                logger.warning("session.gap_fill_stale",
                               expected=expected,
                               new_seq_no=new_seq)
                return
            self._state.incoming_seq_num = new_seq - 1
            await self._persist_sequence()
            logger.info("session.gap_fill",
                       new_seq=new_seq)
            return

        self._state.incoming_seq_num = new_seq - 1
        await self._persist_sequence()
        logger.info("session.sequence_reset",
                   new_seq=new_seq)

    async def connect(self) -> None:
        """Initiate session connection and logon.

        Sequence numbers are preserved across a reconnect unless
        ``config.reset_seq_num`` is set. FIX requires continuity: wiping
        the counters would make the peer see a false gap.
        """
        self.status = SessionStatus.CONNECTING

        if self.config.reset_seq_num:
            # Starting a new sequence overwrites the stored one as soon as
            # the Logon is queued, so the persisted numbers are ignored
            # rather than explicitly cleared.
            self._state.outgoing_seq_num = 0
            self._state.incoming_seq_num = 0
        else:
            await self._restore_sequence()

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

    async def disconnect(self) -> None:
        """Initiate session logout and park the session in WAITING_LOGOUT.

        Pure state transition — this queues the Logout and returns. It
        does not wait for the peer's Logout response and applies no
        timeout: owning time is the caller's job. `FIXSessionRunner.disconnect()`
        drives the wait using `config.logout_timeout` and forces the
        session to DISCONNECTED if the peer never replies.

        Note the asymmetry with `connect()`, which likewise returns as soon
        as the Logon is queued. Both waits live in the engine so the session
        stays a pure state machine with no asyncio coordination.
        """
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

    def _elapsed_seconds(self, since: datetime | None, now: datetime) -> float:
        """Seconds since ``since``; two intervals when never recorded.

        A missing timestamp means "nothing seen/sent yet", which should
        read as long overdue rather than as "just now".
        """
        if since is None:
            return self.config.heartbeat_interval * 2
        return (now - since).total_seconds()

    async def check_peer_liveness(self) -> None:
        """Detect a silent peer and escalate if it stays silent.

        Within the grace window this is a no-op. Beyond it, an unanswered
        TestRequest terminates the session (Logout + ERROR); otherwise a
        TestRequest is sent to probe the peer.

        Pure protocol decision — no timers. FIXSessionRunner calls this on its
        heartbeat task on a fixed interval.
        """
        if self.status != SessionStatus.LOGGED_ON:
            return

        now = utc_now()
        time_since_last = self._elapsed_seconds(self._state.last_received_time, now)

        # FIX 4.4 allows ~120% of the interval before probing a silent peer.
        grace = self.config.heartbeat_interval * 1.2
        if time_since_last < grace:
            return

        if self._state.test_request_id:
            # Previous test request not answered: terminate, but tell the
            # peer why before parking the session.
            logger.warning("session.heartbeat_timeout")
            logout = FIXMessageFactory.create_logout(
                sender=self.config.sender_comp_id,
                target=self.config.target_comp_id,
                seq=0,  # Will be set by send()
                text="Heartbeat timeout: TestRequest unanswered",
            )
            await self.send(logout)
            self.status = SessionStatus.ERROR
            return

        # Send test request
        test_req_id = f"{self.config.sender_comp_id}-{int(now.timestamp())}"
        self._state.test_request_id = test_req_id
        self._state.test_request_time = now

        test_req = FIXMessage()
        test_req.msg_type = MsgType.TEST_REQUEST
        test_req.set(Tags.TEST_REQ_ID, test_req_id)
        await self.send(test_req)

    async def send_heartbeat_if_idle(self) -> None:
        """Emit a Heartbeat when we have been quiet for a full interval.

        This is the outbound keepalive half: it stops a strict peer from
        timing us out. ``last_sent_time`` is maintained by ``send()``, so
        no extra state is needed.
        """
        if self.status != SessionStatus.LOGGED_ON:
            return

        idle = self._elapsed_seconds(self._state.last_sent_time, utc_now())

        if idle < self.config.heartbeat_interval:
            return

        heartbeat = FIXMessageFactory.create_heartbeat(
            sender=self.config.sender_comp_id,
            target=self.config.target_comp_id,
            seq=0,  # Will be set by send()
        )
        await self.send(heartbeat)

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
