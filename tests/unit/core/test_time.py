"""Tests for time helpers."""

from datetime import UTC, datetime, timedelta

from fixwire.core.time import utc_now


class TestUtcNow:
    """Test utc_now behavior."""

    def test_returns_datetime(self):
        """Test utc_now returns a datetime instance."""
        # Act
        result = utc_now()

        # Assert
        assert isinstance(result, datetime)

    def test_is_timezone_aware(self):
        """Test returned datetime is timezone-aware."""
        # Act
        result = utc_now()

        # Assert
        assert result.tzinfo is not None

    def test_tzinfo_is_utc(self):
        """Test returned datetime uses UTC timezone."""
        # Act
        result = utc_now()

        # Assert
        assert result.tzinfo is UTC

    def test_utcoffset_is_zero(self):
        """Test UTC offset is zero."""
        # Act
        result = utc_now()

        # Assert
        offset = result.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0

    def test_is_close_to_actual_now(self):
        """Test returned time is close to datetime.now(UTC)."""
        # Arrange
        before = datetime.now(UTC)

        # Act
        result = utc_now()

        # Arrange
        after = datetime.now(UTC)

        # Assert
        assert before <= result <= after

    def test_subsequent_calls_are_monotonic(self):
        """Test later calls return a time not before earlier calls."""
        # Arrange
        first = utc_now()

        # Act
        second = utc_now()

        # Assert
        assert second >= first

    def test_dst_is_zero(self):
        """Test UTC has no daylight saving time offset."""
        # Act
        result = utc_now()

        # Assert
        assert result.dst() in (None, timedelta(0))
