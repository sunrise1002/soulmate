"""Configuration precedence, validation, and side-effect guarantees."""

from pathlib import Path

import pytest
from soulmate_daemon.config import ConfigurationError, load_settings


def test_defaults_are_local_and_do_not_create_storage(tmp_path: Path) -> None:
    settings = load_settings(environ={})
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 7432
    assert settings.privacy.mode == "strict_local"
    assert settings.database_path == tmp_path / "data" / "soulmate.db"
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
    assert settings.database_path == tmp_path / "prefixed-data" / "soulmate.db"


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


def test_lan_access_is_disabled_with_a_loopback_default() -> None:
    # Given: an installation without network configuration, when settings load,
    settings = load_settings(None, environ={})

    # Then: no other device can reach the service and TLS lives under the data dir
    assert settings.network.lan_enabled is False
    assert settings.network.lan_host == ""
    assert settings.network.lan_port == 7433
    assert settings.tls_directory == (Path.cwd() / "data" / "tls").resolve()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "[::]", "*", " 0.0.0.0 "])
def test_wildcard_lan_hosts_are_rejected_by_configuration(tmp_path: Path, host: str) -> None:
    # Given: a configuration file that would expose every interface
    config = tmp_path / "config.toml"
    config.write_text(f'[network]\nlan_host = "{host}"\n', encoding="utf-8")

    # When/Then: loading fails instead of silently binding a wildcard
    with pytest.raises(ConfigurationError, match=r"network\.lan_host"):
        load_settings(config)


@pytest.mark.parametrize("seconds", [29, 3601, 0, -1])
def test_pairing_lifetime_outside_the_supported_range_is_rejected(
    tmp_path: Path, seconds: int
) -> None:
    # Given: a configuration with an unusable pairing lifetime
    config = tmp_path / "config.toml"
    config.write_text(f"[network]\npairing_ttl_seconds = {seconds}\n", encoding="utf-8")

    # When/Then: the boundary is enforced at load time
    with pytest.raises(ConfigurationError, match="pairing_ttl_seconds"):
        load_settings(config)


@pytest.mark.parametrize("seconds", [30, 300, 3600])
def test_supported_pairing_lifetimes_are_accepted(tmp_path: Path, seconds: int) -> None:
    # Given: a configuration at the edges of the supported range
    config = tmp_path / "config.toml"
    config.write_text(f"[network]\npairing_ttl_seconds = {seconds}\n", encoding="utf-8")

    # When/Then: the value is preserved
    assert load_settings(config).network.pairing_ttl_seconds == seconds


def test_lan_access_can_be_enabled_from_the_environment() -> None:
    # Given: the desktop shell enabling LAN access for the daemon it manages
    environ = {
        "SOULMATE_NETWORK__LAN_ENABLED": "true",
        "SOULMATE_NETWORK__LAN_HOST": "192.168.1.20",
        "SOULMATE_NETWORK__LAN_PORT": "7500",
    }

    # When: settings are loaded
    settings = load_settings(None, environ=environ)

    # Then: the explicit address and port are used
    assert settings.network.lan_enabled is True
    assert settings.network.lan_host == "192.168.1.20"
    assert settings.network.lan_port == 7500


def test_web_client_directory_is_resolved_only_when_the_client_is_enabled(
    tmp_path: Path,
) -> None:
    # Given: a configured web client bundle
    bundle = tmp_path / "web"
    enabled = load_settings(None, environ={"SOULMATE_WEB__CLIENT_DIR": str(bundle)})
    disabled = load_settings(
        None, environ={"SOULMATE_WEB__CLIENT_DIR": str(bundle), "SOULMATE_WEB__ENABLED": "false"}
    )

    # When/Then: disabling the web client removes it from the served surface
    assert enabled.web_client_directory == bundle.resolve()
    assert disabled.web_client_directory is None
