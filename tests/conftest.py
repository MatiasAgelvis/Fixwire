"""Pytest configuration and shared fixtures."""

import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

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


class TestCerts(NamedTuple):
    """Paths to a throwaway CA and the certificates it signed."""

    ca: Path
    server_cert: Path
    server_key: Path
    client_cert: Path
    client_key: Path


def _openssl(directory: Path, *args: str) -> None:
    subprocess.run(
        ["openssl", *args], cwd=directory, check=True, capture_output=True
    )


@pytest.fixture(scope="session")
def tls_certs(tmp_path_factory) -> TestCerts:
    """Generate a CA, a server certificate and a client certificate.

    Generated per run rather than committed: private keys in a repository
    are a liability even when they are obviously fake, and openssl is
    present wherever this suite runs. The server certificate carries a SAN
    for ``localhost`` so hostname verification actually exercises something.
    """
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required to generate test certificates")

    directory = tmp_path_factory.mktemp("tls")
    _openssl(
        directory, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", "ca.key", "-out", "ca.pem", "-days", "1",
        "-subj", "/CN=fixwire-test-ca",
    )
    _openssl(
        directory, "req", "-newkey", "rsa:2048", "-nodes",
        "-keyout", "server.key", "-out", "server.csr",
        "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
    )
    _openssl(
        directory, "x509", "-req", "-in", "server.csr", "-CA", "ca.pem",
        "-CAkey", "ca.key", "-CAcreateserial", "-out", "server.pem",
        "-days", "1", "-copy_extensions", "copy",
    )
    _openssl(
        directory, "req", "-newkey", "rsa:2048", "-nodes",
        "-keyout", "client.key", "-out", "client.csr",
        "-subj", "/CN=fixwire-client",
    )
    _openssl(
        directory, "x509", "-req", "-in", "client.csr", "-CA", "ca.pem",
        "-CAkey", "ca.key", "-CAcreateserial", "-out", "client.pem",
        "-days", "1",
    )
    return TestCerts(
        ca=directory / "ca.pem",
        server_cert=directory / "server.pem",
        server_key=directory / "server.key",
        client_cert=directory / "client.pem",
        client_key=directory / "client.key",
    )
