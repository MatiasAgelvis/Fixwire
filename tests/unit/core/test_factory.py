"""Tests for FIXMessageFactory."""

from fixwire.core.factory import FIXMessageFactory


class TestFIXMessageFactorySessionMessages:
    """Test session message creation."""

    def setup_method(self):
        """Setup test fixtures."""
        self.factory = FIXMessageFactory()

    def test_create_heartbeat(self):
        """Test Heartbeat creation."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1

        # Act
        msg = self.factory.create_heartbeat(sender, target, seq)
        raw = msg.serialize()

        # Assert
        assert msg[35] == "0"
        assert msg[49] == sender
        assert msg[56] == target
        assert raw.startswith(b"8=FIX.4.4")

    def test_create_heartbeat_with_test_req_id(self):
        """Test Heartbeat with TestReqID."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1
        test_req_id = "TEST-001"

        # Act
        msg = self.factory.create_heartbeat(sender, target, seq, test_req_id)

        # Assert
        assert msg[35] == "0"
        assert msg[112] == test_req_id

    def test_create_test_request(self):
        """Test TestRequest creation."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1
        test_req_id = "TEST-001"

        # Act
        msg = self.factory.create_test_request(sender, target, seq, test_req_id)

        # Assert
        assert msg[35] == "1"
        assert msg[112] == test_req_id

    def test_create_logon(self):
        """Test Logon creation."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1
        heartbeat_interval = 30

        # Act
        msg = self.factory.create_logon(sender, target, seq, heartbeat_interval)

        # Assert
        assert msg[35] == "A"
        assert msg[98] == "0"
        assert msg[108] == str(heartbeat_interval)

    def test_create_logon_with_reset(self):
        """Test Logon with sequence number reset."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1
        heartbeat_interval = 30
        reset_seq_num = True

        # Act
        msg = self.factory.create_logon(
            sender, target, seq, heartbeat_interval, reset_seq_num
        )

        # Assert
        assert msg[35] == "A"
        assert msg[141] == "Y"

    def test_create_logout(self):
        """Test Logout creation."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1

        # Act
        msg = self.factory.create_logout(sender, target, seq)

        # Assert
        assert msg[35] == "5"

    def test_create_logout_with_text(self):
        """Test Logout with text."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1
        text = "Goodbye"

        # Act
        msg = self.factory.create_logout(sender, target, seq, text)

        # Assert
        assert msg[35] == "5"
        assert msg[58] == text

    def test_create_reject(self):
        """Test Reject creation."""
        # Arrange
        sender = "SERVER"
        target = "CLIENT"
        seq = 1
        ref_seq_num = 5

        # Act
        msg = self.factory.create_reject(sender, target, seq, ref_seq_num)

        # Assert
        assert msg[35] == "3"
        assert msg[45] == str(ref_seq_num)

    def test_create_reject_with_details(self):
        """Test Reject with full details."""
        # Arrange
        sender = "SERVER"
        target = "CLIENT"
        seq = 1
        ref_seq_num = 5
        ref_tag_id = 35
        ref_msg_type = "D"
        session_reject_reason = 1
        text = "Invalid MsgType"

        # Act
        msg = self.factory.create_reject(
            sender,
            target,
            seq,
            ref_seq_num,
            ref_tag_id,
            ref_msg_type,
            session_reject_reason,
            text,
        )

        # Assert
        assert msg[35] == "3"
        assert msg[45] == str(ref_seq_num)
        assert msg[371] == str(ref_tag_id)
        assert msg[372] == ref_msg_type
        assert msg[373] == str(session_reject_reason)
        assert msg[58] == text

    def test_create_resend_request(self):
        """Test ResendRequest creation."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1
        begin_seq_no = 10
        end_seq_no = 20

        # Act
        msg = self.factory.create_resend_request(
            sender, target, seq, begin_seq_no, end_seq_no
        )

        # Assert
        assert msg[35] == "2"
        assert msg[132] == str(begin_seq_no)
        assert msg[133] == str(end_seq_no)

    def test_create_resend_request_no_end(self):
        """Test ResendRequest without end sequence."""
        # Arrange
        sender = "CLIENT"
        target = "SERVER"
        seq = 1
        begin_seq_no = 10

        # Act
        msg = self.factory.create_resend_request(sender, target, seq, begin_seq_no)

        # Assert
        assert msg[35] == "2"
        assert msg[132] == str(begin_seq_no)
        assert msg[133] == "0"

    def test_create_sequence_reset(self):
        """Test SequenceReset creation."""
        # Arrange
        sender = "SERVER"
        target = "CLIENT"
        seq = 1
        new_seq_no = 50

        # Act
        msg = self.factory.create_sequence_reset(sender, target, seq, new_seq_no)

        # Assert
        assert msg[35] == "4"
        assert msg[36] == str(new_seq_no)

    def test_create_sequence_reset_gap_fill(self):
        """Test SequenceReset-GapFill."""
        # Arrange
        sender = "SERVER"
        target = "CLIENT"
        seq = 1
        new_seq_no = 50
        gap_fill = True

        # Act
        msg = self.factory.create_sequence_reset(
            sender, target, seq, new_seq_no, gap_fill
        )

        # Assert
        assert msg[35] == "4"
        assert msg[36] == str(new_seq_no)
        assert msg[123] == "Y"


class TestFIXMessageFactoryEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_heartbeat_empty_sender(self):
        """Test Heartbeat with empty sender."""
        # Arrange & Act
        msg = FIXMessageFactory.create_heartbeat("", "SERVER", 1)

        # Assert
        assert msg[49] == ""
        assert msg[35] == "0"

    def test_heartbeat_empty_target(self):
        """Test Heartbeat with empty target."""
        # Arrange & Act
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "", 1)

        # Assert
        assert msg[56] == ""

    def test_heartbeat_zero_seq(self):
        """Test Heartbeat with zero sequence number."""
        # Arrange & Act
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 0)

        # Assert
        assert msg[34] == "0"

    def test_heartbeat_large_seq(self):
        """Test Heartbeat with large sequence number."""
        # Arrange & Act
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 999999999)

        # Assert
        assert msg[34] == "999999999"

    def test_heartbeat_none_test_req_id(self):
        """Test Heartbeat with None test_req_id."""
        # Arrange & Act
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 1, None)

        # Assert
        assert msg[35] == "0"
        assert not msg.has(112)

    def test_heartbeat_empty_test_req_id(self):
        """Test Heartbeat with empty test_req_id (not set)."""
        # Arrange & Act
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 1, "")

        # Assert - Empty string is falsy, tag not set
        assert not msg.has(112)

    def test_logon_zero_heartbeat_interval(self):
        """Test Logon with zero heartbeat interval."""
        # Arrange & Act
        msg = FIXMessageFactory.create_logon("CLIENT", "SERVER", 1, 0)

        # Assert
        assert msg[108] == "0"

    def test_logon_large_heartbeat_interval(self):
        """Test Logon with large heartbeat interval."""
        # Arrange & Act
        msg = FIXMessageFactory.create_logon("CLIENT", "SERVER", 1, 3600)

        # Assert
        assert msg[108] == "3600"

    def test_logon_reset_false(self):
        """Test Logon with reset_seq_num=False."""
        # Arrange & Act
        msg = FIXMessageFactory.create_logon("CLIENT", "SERVER", 1, 30, False)

        # Assert
        assert msg[35] == "A"
        assert not msg.has(141)

    def test_reject_zero_ref_seq(self):
        """Test Reject with zero ref_seq_num."""
        # Arrange & Act
        msg = FIXMessageFactory.create_reject("SERVER", "CLIENT", 1, 0)

        # Assert
        assert msg[45] == "0"

    def test_reject_large_ref_seq(self):
        """Test Reject with large ref_seq_num."""
        # Arrange & Act
        msg = FIXMessageFactory.create_reject("SERVER", "CLIENT", 1, 999999)

        # Assert
        assert msg[45] == "999999"

    def test_reject_no_optional_fields(self):
        """Test Reject with no optional fields."""
        # Arrange & Act
        msg = FIXMessageFactory.create_reject("SERVER", "CLIENT", 1, 5)

        # Assert
        assert msg[35] == "3"
        assert msg[45] == "5"
        assert not msg.has(371)
        assert not msg.has(372)
        assert not msg.has(373)
        assert not msg.has(58)

    def test_reject_empty_text(self):
        """Test Reject with empty text (not set)."""
        # Arrange & Act
        msg = FIXMessageFactory.create_reject("SERVER", "CLIENT", 1, 5, text="")

        # Assert - Empty string is falsy, tag not set
        assert not msg.has(58)

    def test_logout_empty_text(self):
        """Test Logout with empty text (not set)."""
        # Arrange & Act
        msg = FIXMessageFactory.create_logout("CLIENT", "SERVER", 1, "")

        # Assert - Empty string is falsy, tag not set
        assert not msg.has(58)

    def test_logout_long_text(self):
        """Test Logout with long text."""
        # Arrange
        long_text = "A" * 1000

        # Act
        msg = FIXMessageFactory.create_logout("CLIENT", "SERVER", 1, long_text)

        # Assert
        assert msg[58] == long_text

    def test_resend_begin_greater_than_end(self):
        """Test ResendRequest with begin > end."""
        # Arrange & Act
        msg = FIXMessageFactory.create_resend_request("CLIENT", "SERVER", 1, 100, 50)

        # Assert
        assert msg[132] == "100"
        assert msg[133] == "50"

    def test_resend_zero_begin(self):
        """Test ResendRequest with zero begin_seq_no."""
        # Arrange & Act
        msg = FIXMessageFactory.create_resend_request("CLIENT", "SERVER", 1, 0)

        # Assert
        assert msg[132] == "0"
        assert msg[133] == "0"

    def test_sequence_reset_zero_new_seq(self):
        """Test SequenceReset with zero new_seq_no."""
        # Arrange & Act
        msg = FIXMessageFactory.create_sequence_reset("SERVER", "CLIENT", 1, 0)

        # Assert
        assert msg[36] == "0"

    def test_sequence_reset_gap_fill_false(self):
        """Test SequenceReset with gap_fill=False."""
        # Arrange & Act
        msg = FIXMessageFactory.create_sequence_reset("SERVER", "CLIENT", 1, 50, False)

        # Assert
        assert msg[35] == "4"
        assert not msg.has(123)

    def test_factory_does_not_set_checksum(self):
        """Test that factory does not set checksum."""
        # Arrange & Act
        msg = FIXMessageFactory.create_heartbeat("CLIENT", "SERVER", 1)

        # Assert
        assert not msg.has(10)
        assert not msg.has(9)

    def test_factory_messages_are_parseable(self):
        """Test that factory messages can be serialized and parsed back."""
        # Arrange
        from fixwire.core.parser import FIXParser

        parser = FIXParser()

        # Act
        msg = FIXMessageFactory.create_logon("CLIENT", "SERVER", 1, 30)
        raw = msg.serialize()
        parsed = parser.parse(raw)

        # Assert
        assert len(parsed) == 1
        assert parsed[0][35] == msg[35]
        assert parsed[0][49] == msg[49]
        assert parsed[0][56] == msg[56]
        assert parsed[0][108] == msg[108]
