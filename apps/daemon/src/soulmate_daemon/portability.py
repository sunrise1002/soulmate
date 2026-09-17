"""Consistent local backups and encrypted portable archive restore."""

import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast
from uuid import uuid4

from alembic.script import ScriptDirectory
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from soulmate_storage_sqlite import Database, Repositories

from soulmate_daemon.config import Settings
from soulmate_daemon.key_aliases import model_rebuilder
from soulmate_daemon.system import DEFAULT_PROFILE_ID, INSTALLATION_ID_KEY, ensure_installation

ARCHIVE_FORMAT_VERSION = 1
ARCHIVE_MAGIC = b"SOULMATE-DTW\x00"
ARCHIVE_DIRECTORIES = ("objects", "indexes", "models")
MAX_ARCHIVE_ENTRIES = 100_000
MAX_ARCHIVE_SIZE = 512 * 1024 * 1024
MIN_PASSPHRASE_LENGTH = 12
PENDING_RESTORE = ".restore-pending.json"
KDF_N = 2**15
KDF_R = 8
KDF_P = 1
FRESHNESS_QUERIES = (
    ("sources", "SELECT count(*) FROM sources"),
    ("raw_events", "SELECT count(*) FROM raw_events"),
    ("conversations", "SELECT count(*) FROM conversations"),
    ("decision_events", "SELECT count(*) FROM decision_events"),
    ("evidence", "SELECT count(*) FROM evidence"),
    ("target_key_aliases", "SELECT count(*) FROM target_key_aliases"),
    ("target_key_catalog", "SELECT count(*) FROM target_key_catalog"),
    ("service_identities", "SELECT count(*) FROM service_identities"),
    ("paired_devices", "SELECT count(*) FROM paired_devices"),
)
SANITIZE_QUERIES = (
    ("api_credentials", "DELETE FROM api_credentials"),
    ("pairing_tokens", "DELETE FROM pairing_tokens"),
    ("paired_devices", "DELETE FROM paired_devices"),
)
# Derived vectors are tied to one local model; portable exports rebuild them instead.
PORTABLE_EXPORT_QUERIES = (("target_key_embeddings", "DELETE FROM target_key_embeddings"),)
PORTABLE_EXPORT = "encrypted_export"


class PortabilityError(ValueError):
    """An archive operation could not be completed safely."""


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    path: Path
    created_at: datetime
    size_bytes: int
    sha256: str
    encrypted: bool
    schema_revision: str


@dataclass(frozen=True, slots=True)
class RestoreResult:
    schema_revision_before: str
    schema_revision_after: str
    snapshot_version: int
    installation_id: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    result = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return result is not None


def is_fresh_installation(database_path: Path) -> bool:
    """Return whether a missing or initialized database has no owner-created data."""
    if not database_path.is_file():
        return True
    try:
        with sqlite3.connect(database_path) as connection:
            for table, query in FRESHNESS_QUERIES:
                if _table_exists(connection, table):
                    count = cast(int, connection.execute(query).fetchone()[0])
                    if count:
                        return False
    except sqlite3.Error as exc:
        raise PortabilityError("The target database could not be inspected safely.") from exc
    return True


def _sanitize_snapshot(path: Path, artifact_type: str) -> None:
    queries: tuple[tuple[str, str], ...] = SANITIZE_QUERIES
    if artifact_type == PORTABLE_EXPORT:
        queries += PORTABLE_EXPORT_QUERIES
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for table, query in queries:
            if _table_exists(connection, table):
                connection.execute(query)
        if _table_exists(connection, "system_metadata"):
            connection.execute("DELETE FROM system_metadata WHERE key = ?", (INSTALLATION_ID_KEY,))
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise PortabilityError("The backup database failed its integrity check.")
        connection.execute("VACUUM")


def _safe_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    files: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise PortabilityError("Archive source directories must not contain symbolic links.")
        if path.is_file():
            files.append(path)
    return tuple(files)


def _zip_payload(
    data_dir: Path,
    database_snapshot: Path,
    destination: Path,
    *,
    created_at: datetime,
    schema_revision: str,
    artifact_type: str,
) -> None:
    entries: list[str] = ["database.sqlite"]
    total_size = database_snapshot.stat().st_size
    for directory_name in ARCHIVE_DIRECTORIES:
        directory = data_dir / directory_name
        for path in _safe_files(directory):
            entries.append(f"{directory_name}/{path.relative_to(directory).as_posix()}")
            total_size += path.stat().st_size
    if len(entries) + 1 > MAX_ARCHIVE_ENTRIES or total_size > MAX_ARCHIVE_SIZE:
        raise PortabilityError("The local data exceeds the supported archive size limit.")
    manifest = {
        "format": "soulmate-portable-archive",
        "format_version": ARCHIVE_FORMAT_VERSION,
        "artifact_type": artifact_type,
        "created_at": created_at.isoformat(),
        "database_schema_revision": schema_revision,
        "database_sha256": _sha256(database_snapshot),
        "credentials_included": False,
        "model_migration": "rebuild_from_evidence",
        "entries": entries,
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        archive.write(database_snapshot, "database.sqlite")
        for entry in entries[1:]:
            archive.write(data_dir / entry, entry)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise PortabilityError(
            f"The export passphrase must contain at least {MIN_PASSPHRASE_LENGTH} characters."
        )
    if len(passphrase.encode()) > 1024:
        raise PortabilityError("The export passphrase is too long.")
    return Scrypt(salt=salt, length=32, n=KDF_N, r=KDF_R, p=KDF_P).derive(
        passphrase.encode("utf-8")
    )


def _encrypt_payload(payload: bytes, passphrase: str) -> bytes:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = json.dumps(
        {
            "format_version": ARCHIVE_FORMAT_VERSION,
            "cipher": "AES-256-GCM",
            "kdf": "scrypt",
            "n": KDF_N,
            "r": KDF_R,
            "p": KDF_P,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ciphertext = AESGCM(_derive_key(passphrase, salt)).encrypt(nonce, payload, header)
    return ARCHIVE_MAGIC + struct.pack(">I", len(header)) + header + ciphertext


def _decrypt_payload(payload: bytes, passphrase: str | None) -> bytes:
    if not payload.startswith(ARCHIVE_MAGIC):
        return payload
    if passphrase is None:
        raise PortabilityError("This portable archive requires a passphrase.")
    offset = len(ARCHIVE_MAGIC)
    if len(payload) < offset + 4:
        raise PortabilityError("The portable archive header is incomplete.")
    header_length = struct.unpack(">I", payload[offset : offset + 4])[0]
    header_start = offset + 4
    header_end = header_start + header_length
    if header_length > 16_384 or header_end >= len(payload):
        raise PortabilityError("The portable archive header is invalid.")
    header_bytes = payload[header_start:header_end]
    try:
        header = json.loads(header_bytes)
        if (
            not isinstance(header, dict)
            or header.get("format_version") != ARCHIVE_FORMAT_VERSION
            or header.get("cipher") != "AES-256-GCM"
            or header.get("kdf") != "scrypt"
            or header.get("n") != KDF_N
            or header.get("r") != KDF_R
            or header.get("p") != KDF_P
        ):
            raise PortabilityError("The portable archive encryption header is unsupported.")
        salt = base64.b64decode(str(header["salt"]), validate=True)
        nonce = base64.b64decode(str(header["nonce"]), validate=True)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PortabilityError("The portable archive encryption header is invalid.") from exc
    if len(salt) != 16 or len(nonce) != 12:
        raise PortabilityError("The portable archive encryption parameters are invalid.")
    try:
        return AESGCM(_derive_key(passphrase, salt)).decrypt(
            nonce, payload[header_end:], header_bytes
        )
    except InvalidTag as exc:
        raise PortabilityError("The passphrase is incorrect or the archive was modified.") from exc


def _validated_members(archive: zipfile.ZipFile) -> tuple[zipfile.ZipInfo, ...]:
    members = tuple(archive.infolist())
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise PortabilityError("The archive contains too many entries.")
    if sum(item.file_size for item in members) > MAX_ARCHIVE_SIZE:
        raise PortabilityError("The archive expands beyond the supported size limit.")
    names: set[str] = set()
    allowed_roots = {"manifest.json", "database.sqlite", *ARCHIVE_DIRECTORIES}
    for member in members:
        path = PurePosixPath(member.filename)
        if (
            member.is_dir()
            or path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] not in allowed_roots
            or member.filename in names
            or stat.S_ISLNK(member.external_attr >> 16)
        ):
            raise PortabilityError("The archive contains an unsafe entry.")
        names.add(member.filename)
    if "manifest.json" not in names or "database.sqlite" not in names:
        raise PortabilityError("The archive is missing required files.")
    return members


def _extract_payload(payload: bytes, destination: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            members = _validated_members(archive)
            try:
                manifest_value: object = json.loads(archive.read("manifest.json"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PortabilityError("The archive manifest is invalid.") from exc
            if not isinstance(manifest_value, dict):
                raise PortabilityError("The archive manifest is invalid.")
            manifest = cast(dict[str, object], manifest_value)
            if (
                manifest.get("format") != "soulmate-portable-archive"
                or manifest.get("format_version") != ARCHIVE_FORMAT_VERSION
                or manifest.get("credentials_included") is not False
            ):
                raise PortabilityError("The archive format or credential policy is unsupported.")
            destination.mkdir(parents=True, exist_ok=False)
            for member in members:
                target = destination.joinpath(*PurePosixPath(member.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise PortabilityError("The archive payload is not a valid ZIP container.") from exc
    expected = manifest.get("database_sha256")
    if not isinstance(expected, str) or _sha256(destination / "database.sqlite") != expected:
        raise PortabilityError("The restored database checksum does not match its manifest.")
    return manifest


def _validate_database(path: Path) -> str:
    try:
        with sqlite3.connect(path) as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            if (
                integrity is None
                or integrity[0] != "ok"
                or not _table_exists(connection, "alembic_version")
            ):
                raise PortabilityError("The restored database failed validation.")
            revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error as exc:
        raise PortabilityError("The restored database could not be inspected.") from exc
    if revision_row is None or not isinstance(revision_row[0], str):
        raise PortabilityError("The restored database has no schema revision.")
    revision = revision_row[0]
    scripts = ScriptDirectory.from_config(Database(path).migration_config)
    known_revisions = {item.revision for item in scripts.walk_revisions()}
    if revision not in known_revisions:
        raise PortabilityError("The restored database uses a newer or unknown schema revision.")
    return revision


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class ArchiveService:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database

    def create(
        self,
        output: Path,
        *,
        passphrase: str | None = None,
        created_at: datetime | None = None,
        artifact_type: str | None = None,
    ) -> ArchiveResult:
        now = created_at if created_at is not None else datetime.now(UTC)
        resolved_output = output.expanduser().resolve()
        if resolved_output == self._settings.database_path:
            raise PortabilityError("An archive cannot overwrite the live database.")
        if resolved_output.exists():
            raise PortabilityError("The archive output path already exists.")
        schema_revision = self._database.current_revision()
        if schema_revision is None:
            raise PortabilityError("The database schema revision is unavailable.")
        with tempfile.TemporaryDirectory(prefix="soulmate-archive-") as temporary:
            workspace = Path(temporary)
            snapshot = workspace / "database.sqlite"
            payload_path = workspace / "payload.zip"
            resolved_type = (
                artifact_type
                if artifact_type is not None
                else PORTABLE_EXPORT
                if passphrase is not None
                else "local_backup"
            )
            self._database.backup_to(snapshot)
            _sanitize_snapshot(snapshot, resolved_type)
            _zip_payload(
                self._settings.data_dir.expanduser().resolve(),
                snapshot,
                payload_path,
                created_at=now,
                schema_revision=schema_revision,
                artifact_type=resolved_type,
            )
            payload = payload_path.read_bytes()
            encrypted = passphrase is not None
            if passphrase is not None:
                payload = _encrypt_payload(payload, passphrase)
            _write_atomic(resolved_output, payload)
        resolved = resolved_output
        return ArchiveResult(
            path=resolved,
            created_at=now,
            size_bytes=resolved.stat().st_size,
            sha256=_sha256(resolved),
            encrypted=encrypted,
            schema_revision=schema_revision,
        )


def stage_restore(settings: Settings, payload: bytes, passphrase: str | None = None) -> str:
    data_dir = settings.data_dir.expanduser().resolve()
    marker = data_dir / PENDING_RESTORE
    if marker.exists():
        raise PortabilityError("A restore is already waiting for the daemon to restart.")
    if not is_fresh_installation(settings.database_path):
        raise PortabilityError("Restore is allowed only into a fresh installation.")
    plaintext = _decrypt_payload(payload, passphrase)
    stage = data_dir / f".restore-{uuid4().hex}"
    try:
        manifest = _extract_payload(plaintext, stage)
        revision = _validate_database(stage / "database.sqlite")
        manifest_revision = manifest.get("database_schema_revision")
        if manifest_revision != revision:
            raise PortabilityError("The archive schema revision does not match its database.")
        marker_payload = {
            "stage": stage.name,
            "database_sha256": _sha256(stage / "database.sqlite"),
            "schema_revision": revision,
        }
        _write_atomic(marker, json.dumps(marker_payload, sort_keys=True).encode("utf-8"))
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return revision


def _copy_restore_files(stage: Path, data_dir: Path) -> None:
    for directory_name in ARCHIVE_DIRECTORIES:
        source_root = stage / directory_name
        if not source_root.is_dir():
            continue
        for source in _safe_files(source_root):
            relative = source.relative_to(source_root)
            target = data_dir / directory_name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file() or _sha256(target) != _sha256(source):
                    raise PortabilityError("Restored files conflict with the fresh installation.")
                continue
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            shutil.copy2(source, temporary)
            temporary.replace(target)


def apply_pending_restore(settings: Settings) -> str | None:
    data_dir = settings.data_dir.expanduser().resolve()
    marker = data_dir / PENDING_RESTORE
    if not marker.is_file():
        return None
    try:
        metadata_value: object = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(metadata_value, dict):
            raise PortabilityError("The pending restore marker is invalid.")
        metadata = cast(dict[str, object], metadata_value)
        stage_name = metadata.get("stage")
        expected_hash = metadata.get("database_sha256")
        revision = metadata.get("schema_revision")
        if (
            not isinstance(stage_name, str)
            or not stage_name.startswith(".restore-")
            or "/" in stage_name
            or not isinstance(expected_hash, str)
            or not isinstance(revision, str)
        ):
            raise PortabilityError("The pending restore marker is invalid.")
        stage = data_dir / stage_name
        restored_database = stage / "database.sqlite"
        if not restored_database.is_file() or _sha256(restored_database) != expected_hash:
            raise PortabilityError("The staged restore database is missing or modified.")
        current_matches = (
            settings.database_path.is_file() and _sha256(settings.database_path) == expected_hash
        )
        if not current_matches and not is_fresh_installation(settings.database_path):
            raise PortabilityError("Restore is allowed only into a fresh installation.")
        _copy_restore_files(stage, data_dir)
        if not current_matches:
            settings.database_path.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(f"{settings.database_path}{suffix}").unlink(missing_ok=True)
            temporary = settings.database_path.with_name(
                f".{settings.database_path.name}.{uuid4().hex}.restore"
            )
            shutil.copy2(restored_database, temporary)
            temporary.replace(settings.database_path)
        marker.unlink()
        shutil.rmtree(stage)
        return revision
    except (OSError, json.JSONDecodeError) as exc:
        raise PortabilityError("The pending restore could not be applied safely.") from exc


def restore_archive(
    settings: Settings, archive_path: Path, passphrase: str | None = None
) -> RestoreResult:
    try:
        resolved_archive = archive_path.expanduser().resolve()
        if resolved_archive.stat().st_size > MAX_ARCHIVE_SIZE:
            raise PortabilityError("The restore archive exceeds the supported size limit.")
        payload = resolved_archive.read_bytes()
    except OSError as exc:
        raise PortabilityError("The restore archive could not be read.") from exc
    before = stage_restore(settings, payload, passphrase)
    applied = apply_pending_restore(settings)
    if applied is None:
        raise PortabilityError("The staged restore was not applied.")
    database = Database(settings.database_path)
    try:
        database.migrate()
        repositories = Repositories(database.sessions())
        installation_id = ensure_installation(repositories.system_metadata, repositories.profiles)
        snapshot = model_rebuilder(repositories, settings).rebuild(DEFAULT_PROFILE_ID)
        after = database.current_revision()
        if after is None:
            raise PortabilityError("The restored schema revision is unavailable.")
    finally:
        database.close()
    return RestoreResult(before, after, snapshot.version, installation_id)
