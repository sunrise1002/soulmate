"""Verify local TLS certificate generation, reuse, and renewal."""

import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from soulmate_daemon.tls import (
    CERTIFICATE_FILENAME,
    CERTIFICATE_LIFETIME,
    PRIVATE_KEY_FILENAME,
    RENEWAL_MARGIN,
    ensure_service_certificate,
)

NOW = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
LAN_ADDRESS = "192.168.1.20"


def test_certificate_is_generated_with_a_pinnable_fingerprint_and_private_key(
    tmp_path: Path,
) -> None:
    # Given: an installation with no certificate yet
    # When: the daemon prepares LAN access
    certificate = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)

    # Then: both files exist, the key is owner-only, and the fingerprint is pinnable
    assert certificate.certificate_path == tmp_path / CERTIFICATE_FILENAME
    assert certificate.key_path == tmp_path / PRIVATE_KEY_FILENAME
    assert certificate.fingerprint.startswith("sha256:")
    assert len(certificate.fingerprint.removeprefix("sha256:")) == 64
    assert certificate.not_valid_after == NOW + CERTIFICATE_LIFETIME
    assert stat.S_IMODE(certificate.key_path.stat().st_mode) == 0o600


def test_certificate_covers_loopback_and_the_requested_lan_address(tmp_path: Path) -> None:
    # Given/When: a certificate is generated for a LAN address
    certificate = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)

    # Then: loopback and LAN names are both usable
    assert {"127.0.0.1", "::1", LAN_ADDRESS, "localhost"} <= set(certificate.addresses)


def test_valid_certificates_are_reused_so_pinned_devices_keep_working(tmp_path: Path) -> None:
    # Given: an existing certificate
    first = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)

    # When: the daemon restarts within the certificate lifetime
    second = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW + timedelta(days=30))

    # Then: the fingerprint devices pinned is unchanged
    assert second.fingerprint == first.fingerprint


def test_certificate_is_replaced_when_the_lan_address_changes(tmp_path: Path) -> None:
    # Given: a certificate issued for one network
    first = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)

    # When: the machine moves to another network
    second = ensure_service_certificate(tmp_path, ("10.0.0.7",), now=NOW)

    # Then: a new certificate covering the new address is issued
    assert second.fingerprint != first.fingerprint
    assert "10.0.0.7" in second.addresses


@pytest.mark.parametrize(
    ("offset", "renewed"),
    [
        (CERTIFICATE_LIFETIME - RENEWAL_MARGIN - timedelta(minutes=1), False),
        (CERTIFICATE_LIFETIME - RENEWAL_MARGIN, True),
        (CERTIFICATE_LIFETIME + timedelta(days=1), True),
    ],
)
def test_certificate_renews_before_it_expires(
    tmp_path: Path, offset: timedelta, renewed: bool
) -> None:
    # Given: a certificate issued at a known time
    first = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)

    # When: it is loaded close to the end of its lifetime
    second = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW + offset)

    # Then: renewal happens only inside the renewal margin
    assert (second.fingerprint != first.fingerprint) is renewed


def test_missing_private_key_forces_a_new_certificate(tmp_path: Path) -> None:
    # Given: a certificate whose private key was removed
    first = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)
    (tmp_path / PRIVATE_KEY_FILENAME).unlink()

    # When: the daemon prepares LAN access again
    second = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)

    # Then: a complete, usable pair is restored
    assert second.fingerprint != first.fingerprint
    assert second.key_path.is_file()


@pytest.mark.parametrize("content", [b"", b"not a certificate"])
def test_unreadable_certificate_files_are_regenerated(tmp_path: Path, content: bytes) -> None:
    # Given: a corrupt certificate file next to a valid key
    ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)
    (tmp_path / CERTIFICATE_FILENAME).write_bytes(content)

    # When: the daemon prepares LAN access again
    certificate = ensure_service_certificate(tmp_path, (LAN_ADDRESS,), now=NOW)

    # Then: a valid certificate is available again
    assert certificate.fingerprint.startswith("sha256:")


def test_certificate_directory_is_created_on_demand(tmp_path: Path) -> None:
    # Given: a data directory without a TLS folder
    directory = tmp_path / "missing" / "tls"

    # When: the daemon prepares LAN access
    certificate = ensure_service_certificate(directory, (LAN_ADDRESS,), now=NOW)

    # Then: the folder and files are created
    assert certificate.certificate_path.is_file()
