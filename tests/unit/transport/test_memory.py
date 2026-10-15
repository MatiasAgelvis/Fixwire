"""Tests for InMemoryTransport."""

import pytest

from fixwire.transport import InMemoryTransport, Transport
from fixwire.transport.memory import InMemoryTransport as DirectImport


class TestInMemoryTransportConformance:
    """InMemoryTransport must satisfy the Transport Protocol."""

    def test_protocol_satisfied(self):
        """A typed assignment to Transport compiles and runs."""
        # Act
        transport: Transport = InMemoryTransport()

        # Assert
        assert transport.is_connected is True

    def test_same_class_via_package_and_module(self):
        """The package re-export is the same class as the module."""
        # Assert
        assert InMemoryTransport is DirectImport


class TestInMemoryTransportSend:
    """Test outbound behavior."""

    @pytest.mark.asyncio
    async def test_send_records_bytes(self):
        """Test that sent bytes are recorded in order."""
        # Arrange
        transport = InMemoryTransport()

        # Act
        await transport.send(b"first")
        await transport.send(b"second")

        # Assert
        assert transport.sent == [b"first", b"second"]

    @pytest.mark.asyncio
    async def test_send_raises_after_close(self):
        """Test that sending after close raises ConnectionError."""
        # Arrange
        transport = InMemoryTransport()
        await transport.close()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.send(b"data")


class TestInMemoryTransportReceive:
    """Test inbound behavior."""

    @pytest.mark.asyncio
    async def test_receive_returns_injected_bytes(self):
        """Test that feed() makes bytes available to receive()."""
        # Arrange
        transport = InMemoryTransport()
        transport.feed(b"hello")

        # Act
        received = await transport.receive()

        # Assert
        assert received == b"hello"

    @pytest.mark.asyncio
    async def test_receive_raises_after_close(self):
        """Test that receiving after close raises ConnectionError."""
        # Arrange
        transport = InMemoryTransport()
        await transport.close()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.receive()


class TestInMemoryTransportClose:
    """Test close behavior."""

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self):
        """Test that repeated close calls do not raise and are counted."""
        # Arrange
        transport = InMemoryTransport()

        # Act
        await transport.close()
        await transport.close()

        # Assert
        assert transport.close_count == 2
        assert transport.is_connected is False
