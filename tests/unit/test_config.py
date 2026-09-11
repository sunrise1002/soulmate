"""Configuration precedence, validation, and side-effect guarantees."""

from pathlib import Path

import pytest
from soulmate_daemon.config import ConfigurationError, load_settings


def test_defaults_are_local_and_do_not_create_storage(tmp_path: Path) -> None:
    settings = load_settings(environ={})
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 7432
    assert settings.privacy.mode == "strict_local"
    assert settings.database_path == tmp_path / "data" / "decision-twin.db"
    assert not settings.database_path.parent.exists()


def test_nested_environment_overrides_preserve_other_toml_settings(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[server]\nhost = "::1"\nport = 8000\n', encoding="utf-8")
    settings = load_settings(config, environ={"SOULMATE_SERVER__PORT": "9000"})
    assert settings.server.host == "::1"
    assert settings.server.port == 9000


def test_data_directory_precedence(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('data_dir = "toml-data"\n', encoding="utf-8")
    assert load_settings(config, environ={}).data_dir == Path("toml-data")
    assert load_settings(config, environ={"DATA_DIR": "env-data"}).data_dir == Path("env-data")
    settings = load_settings(
        config, environ={"DATA_DIR": "env-data", "SOULMATE_DATA_DIR": "prefixed-data"}
    )
    assert settings.database_path == tmp_path / "prefixed-data" / "decision-twin.db"


def test_explicit_storage_path_overrides_derived_path(tmp_path: Path) -> None:
    settings = load_settings(
        environ={"DATA_DIR": "elsewhere", "SOULMATE_STORAGE__PATH": "custom/store.db"}
    )
    assert settings.database_path == tmp_path / "custom" / "store.db"


def test_explicit_config_argument_overrides_environment_selector(tmp_path: Path) -> None:
    config = tmp_path / "chosen.toml"
    config.write_text("[server]\nport = 8001\n", encoding="utf-8")
    env = {"SOULMATE_CONFIG_FILE": str(tmp_path / "missing.toml")}
    assert load_settings(config, environ=env).server.port == 8001
    assert load_settings(environ={"SOULMATE_CONFIG_FILE": str(config)}).server.port == 8001


@pytest.mark.parametrize("use_environment", [True, False])
def test_explicit_missing_file_is_an_error(tmp_path: Path, use_environment: bool) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(ConfigurationError, match="not found"):
        if use_environment:
            load_settings(environ={"SOULMATE_CONFIG_FILE": str(missing)})
        else:
            load_settings(missing, environ={})


@pytest.mark.parametrize(
    "environment",
    [
        {"SOULMATE_SERVER__PORT": "0"},
        {"SOULMATE_SERVER__PORT": "65536"},
        {"SOULMATE_SERVER__PORT": "invalid"},
        {"SOULMATE_SERVER__HOST": "0.0.0.0"},
        {"SOULMATE_SERVER__HOST": "192.168.1.10"},
        {"SOULMATE_PRIVACY__MODE": "unknown"},
        {"SOULMATE_STORAGE__BACKEND": "postgresql"},
        {"SOULMATE_SERVER__PROT": "8000"},
    ],
)
def test_invalid_overrides_are_rejected(environment: dict[str, str]) -> None:
    with pytest.raises(ConfigurationError, match="Invalid configuration fields"):
        load_settings(environ=environment)


@pytest.mark.parametrize("content", ["[invalid", "[server]\nprot = 8000\n"])
def test_malformed_or_unknown_toml_is_rejected(tmp_path: Path, content: str) -> None:
    config = tmp_path / "config.toml"
    config.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_settings(config, environ={})


def test_nested_override_cannot_hide_malformed_section(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('server = "invalid"\n', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="nested override"):
        load_settings(config, environ={"SOULMATE_SERVER__PORT": "8000"})


def test_non_utf8_file_reports_a_configuration_error(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_bytes(b"\xff\xfe")
    with pytest.raises(ConfigurationError, match="Cannot read configuration file"):
        load_settings(config, environ={})


def test_directory_cannot_be_used_as_a_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Cannot read configuration file"):
        load_settings(tmp_path, environ={})


def test_error_does_not_disclose_invalid_setting_value() -> None:
    private_value = "private-configuration-value"
    with pytest.raises(ConfigurationError) as error:
        load_settings(environ={"SOULMATE_PRIVACY__MODE": private_value})
    assert private_value not in str(error.value)


def test_example_configuration_is_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = load_settings(root / "config.example.toml", environ={})
    assert settings.privacy.mode == "strict_local"
    assert settings.llm.provider == "ollama"
