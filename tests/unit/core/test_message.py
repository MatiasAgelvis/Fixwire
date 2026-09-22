"""Tests for FIXMessage."""

from datetime import datetime

from fixwire.core.message import SOH, FIXMessage


class TestFIXMessage:
    """Test FIXMessage class."""

    def test_create_empty_message(self):
        """Create an empty message."""
        msg = FIXMessage()
        assert len(msg) == 0
        assert msg.msg_type == ""

    def test_set_and_get_tags(self):
        """Set and get tag values."""
        msg = FIXMessage()
        msg[35] = "D"
        msg[49] = "CLIENT01"
        msg[56] = "MARKET01"

        assert msg[35] == "D"
        assert msg[49] == "CLIENT01"
        assert msg[56] == "MARKET01"
        assert len(msg) == 3

    def test_msg_type_property(self):
        """Test msg_type property."""
        msg = FIXMessage()
        msg.msg_type = "D"
        assert msg.msg_type == "D"
        assert msg[35] == "D"

    def test_sender_target_properties(self):
        """Test sender and target properties."""
        msg = FIXMessage()
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"

        assert msg.sender == "CLIENT01"
        assert msg.target == "MARKET01"
        assert msg[49] == "CLIENT01"
        assert msg[56] == "MARKET01"

    def test_sequence_property(self):
        """Test sequence property."""
        msg = FIXMessage()
        msg.sequence = 42
        assert msg.sequence == 42
        assert msg[34] == "42"

    def test_get_int(self):
        """Test get_int method."""
        msg = FIXMessage()
        msg[38] = "100"
        msg[40] = "2"

        assert msg.get_int(38) == 100
        assert msg.get_int(40) == 2
        assert msg.get_int(999, default=42) == 42

    def test_get_float(self):
        """Test get_float method."""
        msg = FIXMessage()
        msg[44] = "150.50"
        msg[38] = "100"

        assert msg.get_float(44) == 150.50
        assert msg.get_float(38) == 100.0
        assert msg.get_float(999, default=1.5) == 1.5

    def test_delete_tag(self):
        """Test deleting a tag."""
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        del msg[55]
        assert 55 not in msg
        assert msg.has(35)

    def test_contains(self):
        """Test __contains__."""
        msg = FIXMessage()
        msg[35] = "D"

        assert 35 in msg
        assert 55 not in msg

    def test_iteration(self):
        """Test iterating over tags."""
        msg = FIXMessage()
        msg[35] = "D"
        msg[49] = "CLIENT01"
        msg[56] = "MARKET01"

        tags = list(msg)
        assert tags == [35, 49, 56]

    def test_items(self):
        """Test items method."""
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        items = msg.items()
        assert items == [(35, "D"), (55, "AAPL")]

    def test_copy(self):
        """Test copy method."""
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        copy = msg.copy()
        copy[55] = "MSFT"

        assert msg[55] == "AAPL"
        assert copy[55] == "MSFT"

    def test_clear(self):
        """Test clear method."""
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        msg.clear()
        assert len(msg) == 0

    def test_to_dict(self):
        """Test to_dict method."""
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        d = msg.to_dict()
        assert d == {35: "D", 55: "AAPL"}

    def test_from_dict(self):
        """Test from_dict class method."""
        d = {35: "D", 55: "AAPL", 54: "1"}
        msg = FIXMessage.from_dict(d)

        assert msg[35] == "D"
        assert msg[55] == "AAPL"
        assert msg[54] == "1"

    def test_repr(self):
        """Test __repr__."""
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1

        repr_str = repr(msg)
        assert "FIXMessage" in repr_str
        assert "type=D" in repr_str
        assert "sender=CLIENT01" in repr_str

    def test_sending_time_property(self):
        """Test sending_time property."""
        from datetime import datetime

        msg = FIXMessage()
        now = datetime.utcnow()
        msg.sending_time = now

        received = msg.sending_time
        assert received is not None
        assert received.year == now.year
        assert received.month == now.month
        assert received.day == now.day

    def test_serialize_basic(self):
        """Test basic serialization."""
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)
        msg.set(11, "ORD001")
        msg.set(55, "AAPL")
        msg.set(54, "1")
        msg.set(38, "100")
        msg.set(40, "2")
        msg.set(44, "150.50")

        raw = msg.serialize()

        assert raw.startswith(b"8=FIX.4.4")
        assert b"9=" in raw
        assert b"35=D" in raw
        assert b"49=CLIENT01" in raw
        assert b"56=MARKET01" in raw
        assert b"10=" in raw

    def test_serialize_body_length(self):
        """Test body length calculation."""
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)

        raw = msg.serialize()

        # Parse body length from serialized message
        idx = raw.find(b"9=")
        end = raw.find(SOH.encode(), idx)
        body_length = int(raw[idx + 2:end])

        # Verify it matches calculation
        assert body_length == msg.body_length()

    def test_serialize_checksum(self):
        """Test checksum calculation."""
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)

        raw = msg.serialize()

        # Parse checksum from serialized message
        idx = raw.rfind(b"10=")
        checksum = int(raw[idx + 3:idx + 6])

        # Verify checksum is valid (0-255)
        assert 0 <= checksum <= 255
