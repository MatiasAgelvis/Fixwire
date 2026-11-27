"""TLS configuration for FIX over WSS.

Verification is on by default and the tests pin that: a FIX session carries
orders, so an unverified peer is an unauthenticated one.
"""

import ssl

import pytest

from fixwire.transport.tls import TLSConfig, TLSError, build_ssl_context


class TestClientContext:
    """Client-side defaults matter most: they are what ships."""

    def test_verification_is_required_by_default(self):
        """No configuration means verify the peer and its hostname."""
        # Act
        context = build_ssl_context(TLSConfig())

        # Assert
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_verification_can_be_disabled_for_tests(self):
        """Opting out is explicit, and also turns off hostname checking."""
        # Act
        context = build_ssl_context(TLSConfig(verify=False))

        # Assert
        assert context.verify_mode == ssl.CERT_NONE
        assert context.check_hostname is False

    def test_ca_bundle_must_exist(self, tmp_path):
        """A typo in a CA path fails at startup, not at handshake time."""
        # Act & Assert
        with pytest.raises(TLSError, match="ca_file"):
            build_ssl_context(TLSConfig(ca_file=tmp_path / "missing.pem"))

    def test_a_certificate_without_its_key_is_rejected(self):
        """Half a client identity is a configuration error, not a default."""
        # Act & Assert
        with pytest.raises(TLSError, match="key_file"):
            build_ssl_context(TLSConfig(cert_file="client.pem"))

    def test_a_key_without_its_certificate_is_rejected(self):
        """Same in the other direction."""
        # Act & Assert
        with pytest.raises(TLSError, match="cert_file"):
            build_ssl_context(TLSConfig(key_file="client.key"))

    def test_certificate_files_must_exist(self, tmp_path):
        """Both halves present but pointing at nothing."""
        # Act & Assert
        with pytest.raises(TLSError, match="cert_file"):
            build_ssl_context(
                TLSConfig(
                    cert_file=tmp_path / "missing.pem",
                    key_file=tmp_path / "missing.key",
                )
            )


class TestServerContext:
    """Server-side TLS must present a certificate to be useful."""

    def test_a_server_requires_a_certificate(self):
        """There is no anonymous TLS server."""
        # Act & Assert
        with pytest.raises(TLSError, match="cert_file"):
            build_ssl_context(TLSConfig(server_side=True))

    def test_requiring_client_certs_needs_a_ca(self):
        """Without a CA there is nothing to verify a client against."""
        # Act & Assert
        with pytest.raises(TLSError, match="ca_file"):
            build_ssl_context(
                TLSConfig(
                    server_side=True,
                    cert_file="server.pem",
                    key_file="server.key",
                    require_client_cert=True,
                )
            )

    def test_requiring_client_certs_without_verification_is_rejected(self):
        """Contradictory settings are caught instead of silently weakening."""
        # Act & Assert
        with pytest.raises(TLSError, match="verify"):
            build_ssl_context(
                TLSConfig(
                    server_side=True,
                    cert_file="server.pem",
                    key_file="server.key",
                    ca_file="ca.pem",
                    require_client_cert=True,
                    verify=False,
                )
            )
