"""Self-signed service certificate for encrypted access from paired devices."""

import ipaddress
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CERTIFICATE_FILENAME = "service.crt"
PRIVATE_KEY_FILENAME = "service.key"
CERTIFICATE_LIFETIME = timedelta(days=397)
RENEWAL_MARGIN = timedelta(days=7)
COMMON_NAME = "Soulmate local service"
FINGERPRINT_PREFIX = "sha256"


class CertificateError(RuntimeError):
    """The local service certificate could not be created or read."""


@dataclass(frozen=True, slots=True)
class ServiceCertificate:
    """A locally generated certificate and the fingerprint devices pin."""

    certificate_path: Path
    key_path: Path
    fingerprint: str
    not_valid_after: datetime
    addresses: tuple[str, ...]


def fingerprint_of(certificate: x509.Certificate) -> str:
    """Return the pinnable SHA-256 fingerprint of the DER-encoded certificate."""
    return f"{FINGERPRINT_PREFIX}:{certificate.fingerprint(hashes.SHA256()).hex()}"


def _subject_addresses(certificate: x509.Certificate) -> tuple[str, ...]:
    try:
        extension = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return ()
    addresses = extension.value.get_values_for_type(x509.IPAddress)
    hostnames = extension.value.get_values_for_type(x509.DNSName)
    return tuple(str(name) for name in (*addresses, *hostnames))


def _alternative_names(addresses: Sequence[str]) -> list[x509.GeneralName]:
    names: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for address in addresses:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            names.append(x509.DNSName(address))
    return names


def _load(certificate_path: Path) -> x509.Certificate | None:
    try:
        return x509.load_pem_x509_certificate(certificate_path.read_bytes())
    except (OSError, ValueError):
        return None


def _is_usable(certificate: x509.Certificate, addresses: Sequence[str], now: datetime) -> bool:
    covered = set(_subject_addresses(certificate))
    return (
        certificate.not_valid_after_utc - RENEWAL_MARGIN > now
        and certificate.not_valid_before_utc <= now
        and all(address in covered for address in addresses)
    )


def _generate(directory: Path, addresses: Sequence[str], now: datetime) -> x509.Certificate:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, COMMON_NAME)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + CERTIFICATE_LIFETIME)
        .add_extension(x509.SubjectAlternativeName(_alternative_names(addresses)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    directory.mkdir(parents=True, exist_ok=True)
    key_path = directory / PRIVATE_KEY_FILENAME
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    (directory / CERTIFICATE_FILENAME).write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
    )
    return certificate


def ensure_service_certificate(
    directory: Path, addresses: Sequence[str], *, now: datetime | None = None
) -> ServiceCertificate:
    """Reuse a valid certificate covering the addresses, or create a new one."""
    moment = now if now is not None else datetime.now(UTC)
    covered = ("127.0.0.1", "::1", *addresses)
    certificate_path = directory / CERTIFICATE_FILENAME
    key_path = directory / PRIVATE_KEY_FILENAME
    existing = _load(certificate_path) if key_path.is_file() else None
    certificate = (
        existing
        if existing is not None and _is_usable(existing, covered, moment)
        else _generate(directory, covered, moment)
    )
    if not certificate_path.is_file() or not key_path.is_file():
        raise CertificateError("The local service certificate could not be written.")
    return ServiceCertificate(
        certificate_path=certificate_path,
        key_path=key_path,
        fingerprint=fingerprint_of(certificate),
        not_valid_after=certificate.not_valid_after_utc,
        addresses=_subject_addresses(certificate),
    )
