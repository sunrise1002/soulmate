"""Typed configuration with TOML and explicit environment overrides."""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)


class ConfigurationError(ValueError):
    """Configuration could not be loaded or validated."""


class ConfigModel(BaseModel):
    """Reject misspelled settings instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerConfig(ConfigModel):
    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=7432, ge=1, le=65535)


UNSPECIFIED_BIND_ADDRESSES = frozenset({"0.0.0.0", "::", "[::]", "*"})  # noqa: S104


class NetworkConfig(ConfigModel):
    """Opt-in access from other devices on the local network."""

    lan_enabled: bool = False
    lan_host: str = ""
    lan_port: int = Field(default=7433, ge=1, le=65535)
    tls_dir: Path | None = None
    pairing_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    @field_validator("lan_host")
    @classmethod
    def reject_unspecified_bind_address(cls, value: str) -> str:
        """Refuse wildcard binding so LAN exposure is always an explicit address."""
        if value.strip() in UNSPECIFIED_BIND_ADDRESSES:
            raise ValueError("LAN host must be an explicit address, never a wildcard.")
        return value.strip()


class WebConfig(ConfigModel):
    """Static web client served by the daemon."""

    enabled: bool = True
    client_dir: Path | None = None


class PrivacyConfig(ConfigModel):
    mode: Literal["strict_local", "hybrid", "offline"] = "strict_local"


class StorageConfig(ConfigModel):
    backend: Literal["sqlite"] = "sqlite"
    path: Path | None = None


class S3BackupConfig(ConfigModel):
    """Connection settings shared by R2 and other S3-compatible stores."""

    endpoint_url: AnyHttpUrl | None = None
    region: str = "auto"
    bucket: str = ""
    prefix: str = "soulmate"
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None

    @field_validator("bucket", "region")
    @classmethod
    def reject_blank_required_values(cls, value: str) -> str:
        return value.strip()

    @field_validator("prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if any(part in {".", ".."} for part in normalized.split("/")):
            raise ValueError("Remote backup prefix must not contain dot path segments.")
        return normalized


class RemoteBackupConfig(ConfigModel):
    """Optional encrypted replication of portable archives."""

    backend: Literal["disabled", "s3"] = "disabled"
    automatic_daily: bool = False
    interval_hours: int = Field(default=24, ge=1, le=168)
    passphrase: SecretStr | None = None
    s3: S3BackupConfig = Field(default_factory=S3BackupConfig)

    @model_validator(mode="after")
    def validate_enabled_backend(self) -> "RemoteBackupConfig":
        if self.backend == "disabled":
            if self.automatic_daily:
                raise ValueError("Automatic remote backup requires an enabled backend.")
            return self
        missing: list[str] = []
        if self.passphrase is None or len(self.passphrase.get_secret_value()) < 12:
            missing.append("passphrase (at least 12 characters)")
        if self.s3.endpoint_url is None:
            missing.append("s3.endpoint_url")
        if not self.s3.region:
            missing.append("s3.region")
        if not self.s3.bucket:
            missing.append("s3.bucket")
        if self.s3.access_key_id is None:
            missing.append("s3.access_key_id")
        if self.s3.secret_access_key is None:
            missing.append("s3.secret_access_key")
        if missing:
            raise ValueError(f"Enabled remote backup is missing: {', '.join(missing)}.")
        return self


class VectorConfig(ConfigModel):
    backend: Literal["sqlite_vec", "cosine"] = "sqlite_vec"


class OllamaConfig(ConfigModel):
    base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:11434")
    model: str = ""


class OpenAICompatibleConfig(ConfigModel):
    base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8000/v1")
    model: str = ""
    api_key: SecretStr | None = None


class LLMConfig(ConfigModel):
    provider: Literal["ollama", "openai_compatible"] = "ollama"
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai_compatible: OpenAICompatibleConfig = Field(default_factory=OpenAICompatibleConfig)


class EmbeddingConfig(ConfigModel):
    """Local key embeddings; the pinned artifact is only downloaded on owner request."""

    provider: Literal["none", "local"] = "none"
    model_id: Literal["bge-m3-int8"] = "bge-m3-int8"
    idle_release_seconds: int = Field(default=300, ge=30, le=3600)


class KeyAliasesConfig(ConfigModel):
    """Canonical target key aliases; disabling them rebuilds from original keys."""

    enabled: bool = True


class Settings(ConfigModel):
    data_dir: Path = Path("data")
    server: ServerConfig = Field(default_factory=ServerConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    remote_backup: RemoteBackupConfig = Field(default_factory=RemoteBackupConfig)
    vector: VectorConfig = Field(default_factory=VectorConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    key_aliases: KeyAliasesConfig = Field(default_factory=KeyAliasesConfig)

    @property
    def tls_directory(self) -> Path:
        """Resolve where the local service certificate lives without creating it."""
        directory = self.network.tls_dir
        if directory is None:
            directory = self.data_dir.expanduser() / "tls"
        return directory.expanduser().resolve()

    @property
    def web_client_directory(self) -> Path | None:
        """Resolve the configured web client bundle, or the packaged default."""
        if not self.web.enabled:
            return None
        directory = self.web.client_dir
        if directory is None:
            packaged = Path(__file__).resolve().parent / "web_client"
            return packaged if packaged.is_dir() else None
        return directory.expanduser().resolve()

    @property
    def models_directory(self) -> Path:
        """Resolve where downloaded model artifacts live, without creating anything."""
        return (self.data_dir.expanduser() / "models").resolve()

    @property
    def database_path(self) -> Path:
        """Resolve the future database location without creating anything."""
        path = self.storage.path
        if path is None:
            path = self.data_dir.expanduser() / "soulmate.db"
        return path.expanduser().resolve()


def _apply_override(data: dict[str, Any], keys: list[str], value: str) -> None:
    target = data
    for key in keys[:-1]:
        nested = target.setdefault(key, {})
        if not isinstance(nested, dict):
            raise ConfigurationError(f"Cannot apply nested override to {key!r}.")
        target = nested
    target[keys[-1]] = value


def _reject_remote_backup_secrets_in_toml(data: dict[str, Any]) -> None:
    remote = data.get("remote_backup")
    if not isinstance(remote, dict):
        return
    s3 = remote.get("s3")
    if "passphrase" in remote or (
        isinstance(s3, dict) and {"access_key_id", "secret_access_key"}.intersection(s3)
    ):
        raise ConfigurationError(
            "Remote backup passphrase and credentials must come from the process environment."
        )


def load_settings(
    config_file: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> Settings:
    """Load defaults < TOML < DATA_DIR < SOULMATE_* environment settings.

    An explicitly selected config file must exist. The implicit ./config.toml
    may be absent. This function never creates directories or opens a database.
    """
    env = os.environ if environ is None else environ
    selected = config_file
    if selected is None and "SOULMATE_CONFIG_FILE" in env:
        selected = Path(env["SOULMATE_CONFIG_FILE"])
    explicit = selected is not None
    path = (selected if selected is not None else Path("config.toml")).expanduser()
    data: dict[str, Any] = {}
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except FileNotFoundError as exc:
        if explicit:
            raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"Cannot read configuration file: {path}") from exc

    _reject_remote_backup_secrets_in_toml(data)

    if "DATA_DIR" in env:
        data["data_dir"] = env["DATA_DIR"]
    for name, value in sorted(env.items()):
        if name.startswith("SOULMATE_") and name != "SOULMATE_CONFIG_FILE":
            keys = name.removeprefix("SOULMATE_").lower().split("__")
            _apply_override(data, keys, value)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        raise ConfigurationError(f"Invalid configuration fields: {fields}") from exc
