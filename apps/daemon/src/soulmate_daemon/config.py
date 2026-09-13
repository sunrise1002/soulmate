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
    provider: Literal["local"] = "local"


class Settings(ConfigModel):
    data_dir: Path = Path("data")
    server: ServerConfig = Field(default_factory=ServerConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    vector: VectorConfig = Field(default_factory=VectorConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

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
