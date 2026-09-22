"""Pytest configuration and shared fixtures."""

import pytest

from fixwire.core.message import FIXMessage
from fixwire.core.parser import FIXParser


@pytest.fixture
def fix_parser() -> FIXParser:
    """FIX parser instance."""
    return FIXParser()


@pytest.fixture
def sample_logon() -> FIXMessage:
    """Sample logon message."""
    msg = FIXMessage()
    msg[8] = "FIX.4.4"
    msg[35] = "A"
    msg[49] = "CLIENT01"
    msg[56] = "MARKET01"
    msg[34] = "1"
    msg[52] = "20231220-14:30:00.000"
    msg[98] = "0"
    msg[108] = "30"
    return msg


@pytest.fixture
def sample_new_order() -> FIXMessage:
    """Sample new order message."""
    msg = FIXMessage()
    msg[35] = "D"
    msg[49] = "CLIENT01"
    msg[56] = "MARKET01"
    msg[11] = "ORD-001"
    msg[21] = "1"
    msg[55] = "AAPL"
    msg[54] = "1"
    msg[38] = "100"
    msg[40] = "2"
    msg[44] = "150.50"
    msg[59] = "0"
    return msg
