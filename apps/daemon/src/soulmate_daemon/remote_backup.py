"""Vendor-neutral encrypted remote backup orchestration and S3 adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from soulmate_core.domain import Job, JobRepository, JobStatus, SystemMetadataRepository
from soulmate_llm_providers import EgressDeniedError, EgressPolicy
from soulmate_storage_sqlite import Database

from soulmate_daemon.config import Settings
from soulmate_daemon.portability import MAX_ARCHIVE_SIZE, ArchiveResult, ArchiveService

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

REMOTE_BACKUP_JOB = "remote_backup"
LAST_REMOTE_BACKUP_AT = "remote_backup.last_success_at"
LAST_REMOTE_BACKUP_ENQUEUED_AT = "remote_backup.last_enqueued_at"


class RemoteBackupError(RuntimeError):
    """A remote backup operation failed without exposing credentials."""


@dataclass(frozen=True, slots=True)
class RemoteBackupObject:
    key: str
    size_bytes: int
    last_modified: datetime


@dataclass(frozen=True, slots=True)
class RemoteBackupResult:
    archive: ArchiveResult
    remote: RemoteBackupObject


@dataclass(frozen=True, slots=True)
class RemoteDownloadResult:
    path: Path
    remote: RemoteBackupObject


class RemoteBackupStore(Protocol):
    """Storage port for encrypted archives; implementations may use any provider."""

    def upload(self, archive: ArchiveResult) -> RemoteBackupObject: ...

    def latest(self) -> RemoteBackupObject | None: ...

    def download(self, remote: RemoteBackupObject, destination: Path) -> None: ...


class S3RemoteBackupStore:
    """S3-compatible adapter suitable for R2, S3, B2, and MinIO."""

    def __init__(self, settings: Settings, *, client: S3Client | None = None) -> None:
        configuration = settings.remote_backup.s3
        if configuration.endpoint_url is None:
            raise RemoteBackupError("The S3-compatible endpoint is not configured.")
        endpoint = str(configuration.endpoint_url).rstrip("/")
        try:
            EgressPolicy(settings.privacy.mode).require(
                provider="remote_backup:s3",
                endpoint=endpoint,
                data_classification="encrypted_personal_archive",
            )
        except EgressDeniedError as exc:
            raise RemoteBackupError(
                "The configured privacy mode denied remote backup network access."
            ) from exc
        access_key = configuration.access_key_id
        secret_key = configuration.secret_access_key
        if access_key is None or secret_key is None:
            raise RemoteBackupError("Remote backup credentials are not configured.")
        self._bucket = configuration.bucket
        self._prefix = configuration.prefix
        self._client = client or boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=configuration.region,
            aws_access_key_id=access_key.get_secret_value(),
            aws_secret_access_key=secret_key.get_secret_value(),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _key(self, archive: ArchiveResult) -> str:
        date_path = archive.created_at.astimezone(UTC).strftime("%Y/%m/%d")
        parts = [part for part in (self._prefix, date_path, archive.path.name) if part]
        return "/".join(parts)

    def upload(self, archive: ArchiveResult) -> RemoteBackupObject:
        key = self._key(archive)
        try:
            self._client.upload_file(
                str(archive.path),
                self._bucket,
                key,
                ExtraArgs={
                    "ContentType": "application/vnd.soulmate.archive",
                    "Metadata": {
                        "sha256": archive.sha256,
                        "schema-revision": archive.schema_revision,
                        "encrypted": "true",
                    },
                },
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise RemoteBackupError("The encrypted archive could not be uploaded.") from exc
        return RemoteBackupObject(key, archive.size_bytes, archive.created_at)

    def latest(self) -> RemoteBackupObject | None:
        newest: RemoteBackupObject | None = None
        token: str | None = None
        try:
            while True:
                prefix = f"{self._prefix}/" if self._prefix else ""
                if token is None:
                    response = self._client.list_objects_v2(
                        Bucket=self._bucket,
                        Prefix=prefix,
                    )
                else:
                    response = self._client.list_objects_v2(
                        Bucket=self._bucket,
                        Prefix=prefix,
                        ContinuationToken=token,
                    )
                for item in response.get("Contents", []):
                    key = item.get("Key")
                    size = item.get("Size")
                    modified = item.get("LastModified")
                    if (
                        not isinstance(key, str)
                        or not key.endswith(".dtw")
                        or not isinstance(size, int)
                        or not isinstance(modified, datetime)
                    ):
                        continue
                    candidate = RemoteBackupObject(key, size, modified.astimezone(UTC))
                    if newest is None or candidate.last_modified > newest.last_modified:
                        newest = candidate
                if not response.get("IsTruncated"):
                    break
                next_token = response.get("NextContinuationToken")
                if not isinstance(next_token, str):
                    raise RemoteBackupError("Remote backup listing was incomplete.")
                token = next_token
        except (BotoCoreError, ClientError) as exc:
            raise RemoteBackupError("Remote backups could not be listed.") from exc
        return newest

    def download(self, remote: RemoteBackupObject, destination: Path) -> None:
        if remote.size_bytes > MAX_ARCHIVE_SIZE:
            raise RemoteBackupError("The remote archive exceeds the supported size limit.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            self._client.download_file(self._bucket, remote.key, str(temporary))
            if temporary.stat().st_size != remote.size_bytes:
                raise RemoteBackupError("The downloaded archive size does not match its listing.")
            temporary.replace(destination)
        except RemoteBackupError:
            temporary.unlink(missing_ok=True)
            raise
        except (BotoCoreError, ClientError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            raise RemoteBackupError("The encrypted archive could not be downloaded.") from exc


class RemoteBackupService:
    """Create encrypted portable archives and copy them through a storage port."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        metadata: SystemMetadataRepository,
        store: RemoteBackupStore,
    ) -> None:
        self._settings = settings
        self._database = database
        self._metadata = metadata
        self._store = store

    @property
    def passphrase(self) -> str:
        value = self._settings.remote_backup.passphrase
        if value is None:
            raise RemoteBackupError("The remote backup passphrase is not configured.")
        return value.get_secret_value()

    def create_and_upload(self, now: datetime | None = None) -> RemoteBackupResult:
        created_at = now or datetime.now(UTC)
        timestamp = created_at.strftime("%Y%m%dT%H%M%SZ")
        archive_path = (
            self._settings.data_dir.expanduser().resolve()
            / "backups"
            / f"soulmate-remote-backup-{timestamp}-{uuid4().hex[:8]}.dtw"
        )
        archive = ArchiveService(self._settings, self._database).create(
            archive_path,
            passphrase=self.passphrase,
            created_at=created_at,
            artifact_type="remote_backup",
        )
        try:
            remote = self._store.upload(archive)
        except (OSError, RemoteBackupError):
            archive.path.unlink(missing_ok=True)
            raise
        self._metadata.set(LAST_REMOTE_BACKUP_AT, created_at.isoformat(), created_at)
        return RemoteBackupResult(archive, remote)

    def latest(self) -> RemoteBackupObject | None:
        return self._store.latest()

    def download_latest(self) -> RemoteDownloadResult:
        remote = self._store.latest()
        if remote is None:
            raise RemoteBackupError("No remote backup is available.")
        filename = Path(remote.key).name
        destination = self._settings.data_dir.expanduser().resolve() / "backups" / filename
        self._store.download(remote, destination)
        return RemoteDownloadResult(destination, remote)


def build_remote_backup_store(settings: Settings) -> RemoteBackupStore | None:
    """Compose a configured adapter while keeping the service vendor-neutral."""
    if settings.remote_backup.backend == "disabled":
        return None
    if settings.remote_backup.backend == "s3":
        return S3RemoteBackupStore(settings)
    raise RemoteBackupError("The configured remote backup backend is unsupported.")


def parse_metadata_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def remote_backup_is_due(
    metadata: SystemMetadataRepository, now: datetime, interval: timedelta
) -> bool:
    """Return whether neither a success nor an enqueue covers the current interval."""
    last_success = parse_metadata_time(metadata.get(LAST_REMOTE_BACKUP_AT))
    last_enqueued = parse_metadata_time(metadata.get(LAST_REMOTE_BACKUP_ENQUEUED_AT))
    last_activity = max(
        (item for item in (last_success, last_enqueued) if item is not None),
        default=None,
    )
    return last_activity is None or now - last_activity >= interval


def enqueue_remote_backup_if_due(
    jobs: JobRepository,
    metadata: SystemMetadataRepository,
    *,
    now: datetime | None = None,
    interval: timedelta = timedelta(hours=24),
) -> Job | None:
    """Persist one restart-safe remote backup job when the daily interval elapsed."""
    current = now or datetime.now(UTC)
    if not remote_backup_is_due(metadata, current, interval):
        return None
    job = Job(
        id=f"job_remote_backup_{uuid4().hex}",
        job_type=REMOTE_BACKUP_JOB,
        payload={},
        status=JobStatus.QUEUED,
        attempts=0,
        max_attempts=3,
        available_at=current,
        created_at=current,
        updated_at=current,
    )
    jobs.enqueue(job)
    metadata.set(LAST_REMOTE_BACKUP_ENQUEUED_AT, current.isoformat(), current)
    return job
