"""Tests for FIXMessage."""

from datetime import datetime

import pytest

from fixwire.core.constants import SOH
from fixwire.core.message import FIXMessage


class TestFIXMessageCreation:
    """Test FIXMessage creation and initialization."""

    def test_create_empty_message(self):
        """Create an empty message."""
        # Arrange & Act
        msg = FIXMessage()

        # Assert
        assert len(msg) == 0
        assert msg.msg_type == ""
        assert msg.sender == ""
        assert msg.target == ""
        assert msg.sequence == 0

    def test_create_from_dict(self):
        """Create message from dictionary."""
        # Arrange
        d = {35: "D", 49: "CLIENT", 56: "SERVER", 55: "AAPL"}

        # Act
        msg = FIXMessage.from_dict(d)

        # Assert
        assert msg[35] == d[35]
        assert msg[49] == d[49]
        assert msg[56] == d[56]
        assert msg[55] == d[55]

    def test_create_from_dict_empty(self):
        """Create message from empty dictionary."""
        # Arrange & Act
        msg = FIXMessage.from_dict({})

        # Assert
        assert len(msg) == 0

    def test_create_from_dict_string_keys(self):
        """from_dict with string keys should cast to int."""
        # Arrange
        d = {"35": "D", "49": "CLIENT"}

        # Act
        msg = FIXMessage.from_dict(d)

        # Assert
        assert isinstance(msg[35], str)
        assert isinstance(msg[49], str)
        assert msg[35] == "D"
        assert msg[49] == "CLIENT"

    def test_create_from_dict_mixed_keys(self):
        """from_dict with mixed key types should work."""
        # Arrange
        d = {35: "D", "49": "CLIENT"}

        # Act
        msg = FIXMessage.from_dict(d)

        # Assert
        assert msg[35] == "D"
        assert msg[49] == "CLIENT"


class TestFIXMessageGetSet:
    """Test tag get/set operations."""

    def test_set_and_get_string(self):
        """Set and get string tag value."""
        # Arrange
        msg = FIXMessage()

        # Act
        msg[35] = "D"

        # Assert
        assert msg[35] == "D"

    def test_set_and_get_int_as_string(self):
        """Set and get integer tag value (stored as string)."""
        # Arrange
        msg = FIXMessage()

        # Act
        msg[34] = "42"

        # Assert
        assert msg[34] == "42"
        assert msg.get_int(34) == 42

    def test_set_and_get_float_as_string(self):
        """Set and get float tag value (stored as string)."""
        # Arrange
        msg = FIXMessage()

        # Act
        msg[44] = "150.50"

        # Assert
        assert msg[44] == "150.50"
        assert msg.get_float(44) == 150.50

    def test_get_with_default(self):
        """Get tag value with default."""
        # Arrange
        msg = FIXMessage()

        # Act & Assert
        assert msg.get(999, "default") == "default"
        assert msg.get(999) == ""

    def test_get_int_with_default(self):
        """Get integer tag value with default."""
        # Arrange
        msg = FIXMessage()

        # Act & Assert
        assert msg.get_int(999, 42) == 42
        assert msg.get_int(999) == 0

    def test_get_float_with_default(self):
        """Get float tag value with default."""
        # Arrange
        msg = FIXMessage()

        # Act & Assert
        assert msg.get_float(999, 1.5) == 1.5
        assert msg.get_float(999) == 0.0

    def test_get_int_invalid_value(self):
        """Get integer from non-numeric string."""
        # Arrange
        msg = FIXMessage()
        msg[34] = "not_a_number"

        # Act & Assert
        assert msg.get_int(34, 0) == 0

    def test_get_float_invalid_value(self):
        """Get float from non-numeric string."""
        # Arrange
        msg = FIXMessage()
        msg[44] = "not_a_number"

        # Act & Assert
        assert msg.get_float(44, 0.0) == 0.0

    def test_has_existing_tag(self):
        """Check if tag exists."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"

        # Act & Assert
        assert msg.has(35) is True

    def test_has_missing_tag(self):
        """Check if missing tag exists."""
        # Arrange
        msg = FIXMessage()

        # Act & Assert
        assert msg.has(35) is False

    def test_delete_tag(self):
        """Delete existing tag."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        # Act
        del msg[55]

        # Assert
        assert msg.has(55) is False
        assert msg.has(35) is True

    def test_delete_missing_tag(self):
        """Delete missing tag raises KeyError."""
        # Arrange
        msg = FIXMessage()

        # Act & Assert
        with pytest.raises(KeyError):
            del msg[999]

    def test_overwrite_tag(self):
        """Overwrite existing tag value."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"

        # Act
        msg[35] = "8"

        # Assert
        assert msg[35] == "8"


class TestFIXMessageIteration:
    """Test iteration and collection methods."""

    def test_iterate_tags(self):
        """Iterate over tags in order."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[49] = "CLIENT"
        msg[56] = "SERVER"

        # Act
        tags = list(msg)

        # Assert
        assert tags == [35, 49, 56]

    def test_items(self):
        """Get all tag-value pairs."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        # Act
        items = msg.items()

        # Assert
        assert items == [(35, "D"), (55, "AAPL")]

    def test_tags(self):
        """Get all tag numbers."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[49] = "CLIENT"

        # Act
        result = msg.tags()

        # Assert
        assert result == [35, 49]

    def test_values(self):
        """Get all tag values."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        # Act
        result = msg.values()

        # Assert
        assert result == ["D", "AAPL"]

    def test_to_dict(self):
        """Convert to dictionary."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        # Act
        d = msg.to_dict()

        # Assert
        assert d == {35: "D", 55: "AAPL"}


class TestFIXMessageCopy:
    """Test copy and clear operations."""

    def test_copy_message(self):
        """Copy message creates independent copy."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        # Act
        copy = msg.copy()
        copy[55] = "MSFT"

        # Assert
        assert msg[55] == "AAPL"
        assert copy[55] == "MSFT"

    def test_clear_message(self):
        """Clear removes all tags."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[55] = "AAPL"

        # Act
        msg.clear()

        # Assert
        assert len(msg) == 0


class TestFIXMessageProperties:
    """Test convenience properties."""

    def test_msg_type_property(self):
        """Test msg_type property."""
        # Arrange
        msg = FIXMessage()

        # Act
        msg.msg_type = "D"

        # Assert
        assert msg.msg_type == "D"
        assert msg[35] == "D"

    def test_sender_property(self):
        """Test sender property."""
        # Arrange
        msg = FIXMessage()

        # Act
        msg.sender = "CLIENT01"

        # Assert
        assert msg.sender == "CLIENT01"
        assert msg[49] == "CLIENT01"

    def test_target_property(self):
        """Test target property."""
        # Arrange
        msg = FIXMessage()

        # Act
        msg.target = "MARKET01"

        # Assert
        assert msg.target == "MARKET01"
        assert msg[56] == "MARKET01"

    def test_sequence_property(self):
        """Test sequence property."""
        # Arrange
        msg = FIXMessage()

        # Act
        msg.sequence = 42

        # Assert
        assert msg.sequence == 42
        assert msg[34] == "42"

    def test_sending_time_property(self):
        """Test sending_time property."""
        # Arrange
        msg = FIXMessage()
        now = datetime(2023, 12, 20, 14, 30, 0, 123000)

        # Act
        msg.sending_time = now
        received = msg.sending_time

        # Assert
        assert received is not None
        assert received.year == now.year
        assert received.month == now.month
        assert received.day == now.day
        assert received.hour == now.hour
        assert received.minute == now.minute

    def test_sending_time_none(self):
        """Test sending_time when not set."""
        # Arrange
        msg = FIXMessage()

        # Act & Assert
        assert msg.sending_time is None

    def test_sending_time_invalid_format(self):
        """Test sending_time with invalid format."""
        # Arrange
        msg = FIXMessage()
        msg[52] = "invalid_timestamp"

        # Act & Assert
        assert msg.sending_time is None

    def test_sending_time_short_format(self):
        """Test sending_time with short format."""
        # Arrange
        msg = FIXMessage()
        msg[52] = "20231220-14:30:00"

        # Act
        st = msg.sending_time

        # Assert
        assert st is not None
        assert st.microsecond == 0


class TestFIXMessagePropertiesExtended:
    """Test all convenience properties."""

    def test_client_order_id(self):
        """Test client_order_id property."""
        # Arrange
        msg = FIXMessage()
        msg[11] = "ORD-001"

        # Act & Assert
        assert msg.client_order_id == "ORD-001"

    def test_order_id(self):
        """Test order_id property."""
        # Arrange
        msg = FIXMessage()
        msg[37] = "12345"

        # Act & Assert
        assert msg.order_id == "12345"

    def test_execution_id(self):
        """Test execution_id property."""
        # Arrange
        msg = FIXMessage()
        msg[17] = "EXEC-001"

        # Act & Assert
        assert msg.execution_id == "EXEC-001"

    def test_original_client_order_id(self):
        """Test original_client_order_id property."""
        # Arrange
        msg = FIXMessage()
        msg[41] = "ORD-000"

        # Act & Assert
        assert msg.original_client_order_id == "ORD-000"

    def test_symbol(self):
        """Test symbol property."""
        # Arrange
        msg = FIXMessage()
        msg[55] = "AAPL"

        # Act & Assert
        assert msg.symbol == "AAPL"

    def test_side(self):
        """Test side property."""
        # Arrange
        msg = FIXMessage()
        msg[54] = "1"

        # Act & Assert
        assert msg.side == "1"

    def test_order_quantity(self):
        """Test order_quantity property."""
        # Arrange
        msg = FIXMessage()
        msg[38] = "100"

        # Act & Assert
        assert msg.order_quantity == 100.0

    def test_price(self):
        """Test price property."""
        # Arrange
        msg = FIXMessage()
        msg[44] = "150.50"

        # Act & Assert
        assert msg.price == 150.50

    def test_order_type(self):
        """Test order_type property."""
        # Arrange
        msg = FIXMessage()
        msg[40] = "2"

        # Act & Assert
        assert msg.order_type == "2"

    def test_time_in_force(self):
        """Test time_in_force property."""
        # Arrange
        msg = FIXMessage()
        msg[59] = "0"

        # Act & Assert
        assert msg.time_in_force == "0"

    def test_account(self):
        """Test account property."""
        # Arrange
        msg = FIXMessage()
        msg[1] = "ACC-001"

        # Act & Assert
        assert msg.account == "ACC-001"

    def test_order_status(self):
        """Test order_status property."""
        # Arrange
        msg = FIXMessage()
        msg[39] = "0"

        # Act & Assert
        assert msg.order_status == "0"

    def test_execution_type(self):
        """Test execution_type property."""
        # Arrange
        msg = FIXMessage()
        msg[150] = "2"

        # Act & Assert
        assert msg.execution_type == "2"

    def test_last_fill_quantity(self):
        """Test last_fill_quantity property."""
        # Arrange
        msg = FIXMessage()
        msg[32] = "50"

        # Act & Assert
        assert msg.last_fill_quantity == 50.0

    def test_last_fill_price(self):
        """Test last_fill_price property."""
        # Arrange
        msg = FIXMessage()
        msg[31] = "150.25"

        # Act & Assert
        assert msg.last_fill_price == 150.25

    def test_filled_quantity(self):
        """Test filled_quantity property."""
        # Arrange
        msg = FIXMessage()
        msg[14] = "75"

        # Act & Assert
        assert msg.filled_quantity == 75.0

    def test_average_price(self):
        """Test average_price property."""
        # Arrange
        msg = FIXMessage()
        msg[6] = "150.30"

        # Act & Assert
        assert msg.average_price == 150.30

    def test_remaining_quantity(self):
        """Test remaining_quantity property."""
        # Arrange
        msg = FIXMessage()
        msg[151] = "25"

        # Act & Assert
        assert msg.remaining_quantity == 25.0

    def test_message_type(self):
        """Test message_type property."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"

        # Act & Assert
        assert msg.message_type == "D"

    def test_heartbeat_interval(self):
        """Test heartbeat_interval property."""
        # Arrange
        msg = FIXMessage()
        msg[108] = "30"

        # Act & Assert
        assert msg.heartbeat_interval == 30

    def test_test_request_id(self):
        """Test test_request_id property."""
        # Arrange
        msg = FIXMessage()
        msg[112] = "TEST-001"

        # Act & Assert
        assert msg.test_request_id == "TEST-001"

    def test_reset_sequence_numbers(self):
        """Test reset_sequence_numbers property."""
        # Arrange
        msg = FIXMessage()
        msg[141] = "Y"

        # Act & Assert
        assert msg.reset_sequence_numbers is True

    def test_reset_sequence_numbers_false(self):
        """Test reset_sequence_numbers property when false."""
        # Arrange
        msg = FIXMessage()
        msg[141] = "N"

        # Act & Assert
        assert msg.reset_sequence_numbers is False

    def test_begin_sequence_number(self):
        """Test begin_sequence_number property."""
        # Arrange
        msg = FIXMessage()
        msg[132] = "1"

        # Act & Assert
        assert msg.begin_sequence_number == 1

    def test_end_sequence_number(self):
        """Test end_sequence_number property."""
        # Arrange
        msg = FIXMessage()
        msg[133] = "100"

        # Act & Assert
        assert msg.end_sequence_number == 100

    def test_new_sequence_number(self):
        """Test new_sequence_number property."""
        # Arrange
        msg = FIXMessage()
        msg[36] = "50"

        # Act & Assert
        assert msg.new_sequence_number == 50

    def test_gap_fill_flag(self):
        """Test gap_fill_flag property."""
        # Arrange
        msg = FIXMessage()
        msg[123] = "Y"

        # Act & Assert
        assert msg.gap_fill_flag is True

    def test_gap_fill_flag_false(self):
        """Test gap_fill_flag property when false."""
        # Arrange
        msg = FIXMessage()
        msg[123] = "N"

        # Act & Assert
        assert msg.gap_fill_flag is False

    def test_reference_sequence_number(self):
        """Test reference_sequence_number property."""
        # Arrange
        msg = FIXMessage()
        msg[45] = "10"

        # Act & Assert
        assert msg.reference_sequence_number == 10

    def test_reference_tag_id(self):
        """Test reference_tag_id property."""
        # Arrange
        msg = FIXMessage()
        msg[371] = "35"

        # Act & Assert
        assert msg.reference_tag_id == 35

    def test_reference_message_type(self):
        """Test reference_message_type property."""
        # Arrange
        msg = FIXMessage()
        msg[372] = "D"

        # Act & Assert
        assert msg.reference_message_type == "D"

    def test_reject_reason(self):
        """Test reject_reason property."""
        # Arrange
        msg = FIXMessage()
        msg[373] = "5"

        # Act & Assert
        assert msg.reject_reason == 5

    def test_text(self):
        """Test text property."""
        # Arrange
        msg = FIXMessage()
        msg[58] = "Invalid message"

        # Act & Assert
        assert msg.text == "Invalid message"


class TestFIXMessageSerialization:
    """Test message serialization."""

    def test_serialize_basic(self):
        """Test basic serialization."""
        # Arrange
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)

        # Act
        raw = msg.serialize()

        # Assert
        assert raw.startswith(b"8=FIX.4.4")
        assert b"9=" in raw
        assert b"35=D" in raw
        assert b"49=CLIENT01" in raw
        assert b"56=MARKET01" in raw
        assert b"10=" in raw

    def test_serialize_sets_sending_time(self):
        """Test that serialization sets sending_time if not set."""
        # Arrange
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1

        # Act
        raw = msg.serialize()

        # Assert
        assert b"52=" in raw

    def test_serialize_preserves_sending_time(self):
        """Test that serialization preserves existing sending_time."""
        # Arrange
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)

        # Act
        raw = msg.serialize()

        # Assert
        assert b"52=20231220-14:30:00.123" in raw

    def test_serialize_body_length(self):
        """Test body length calculation."""
        # Arrange
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)

        # Act
        raw = msg.serialize()

        # Assert
        idx = raw.find(b"9=")
        end = raw.find(SOH.encode(), idx)
        body_length = int(raw[idx + 2:end])
        assert body_length == msg.body_length()

    def test_serialize_checksum(self):
        """Test checksum calculation."""
        # Arrange
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)

        # Act
        raw = msg.serialize()

        # Assert
        idx = raw.rfind(b"10=")
        checksum = int(raw[idx + 3:idx + 6])
        assert 0 <= checksum <= 255

    def test_serialize_checksum_format(self):
        """Test checksum is 3-digit zero-padded."""
        # Arrange
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1
        msg.sending_time = datetime(2023, 12, 20, 14, 30, 0, 123000)

        # Act
        raw = msg.serialize()

        # Assert
        idx = raw.rfind(b"10=")
        checksum_str = raw[idx + 3:idx + 6]
        assert len(checksum_str) == 3
        assert checksum_str.isdigit()


class TestFIXMessageRepr:
    """Test string representations."""

    def test_repr(self):
        """Test __repr__."""
        # Arrange
        msg = FIXMessage()
        msg.msg_type = "D"
        msg.sender = "CLIENT01"
        msg.target = "MARKET01"
        msg.sequence = 1

        # Act
        repr_str = repr(msg)

        # Assert
        assert "FIXMessage" in repr_str
        assert "type=D" in repr_str
        assert "sender=CLIENT01" in repr_str
        assert "target=MARKET01" in repr_str
        assert "seq=1" in repr_str

    def test_str(self):
        """Test __str__."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"
        msg[49] = "CLIENT01"

        # Act
        str_repr = str(msg)

        # Assert
        assert "35" in str_repr
        assert "D" in str_repr
        assert "49" in str_repr
        assert "CLIENT01" in str_repr

    def test_to_debug_string(self):
        """Test to_debug_string."""
        # Arrange
        msg = FIXMessage()
        msg[35] = "D"

        # Act
        debug_str = msg.to_debug_string()

        # Assert
        assert "35" in debug_str
        assert "MsgType" in debug_str
        assert "D" in debug_str
