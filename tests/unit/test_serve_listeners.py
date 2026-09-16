"""Verify how the daemon binds loopback and optional LAN listeners."""

import io
import signal
from pathlib import Path

import pytest
from soulmate_daemon import serve as serve_module
from soulmate_daemon.config import Settings
from soulmate_daemon.network import LanEndpoint, NetworkConfigurationError
from soulmate_daemon.serve import (
    _lan_config,
    _listen_for_desktop_shutdown,
    _loopback_config,
    _ManagedServer,
)
from soulmate_daemon.tls import ensure_service_certificate

LAN_ADDRESS = "192.168.1.20"


def _settings(tmp_path: Path, **network: object) -> Settings:
    return Settings.model_validate({"data_dir": str(tmp_path), "network": network})


def _endpoint(tmp_path: Path) -> LanEndpoint:
    return LanEndpoint(
        host=LAN_ADDRESS,
        port=7433,
        certificate=ensure_service_certificate(tmp_path / "tls", (LAN_ADDRESS,)),
    )


def test_loopback_listener_never_leaves_the_owner_machine(tmp_path: Path) -> None:
    # Given: default settings
    settings = _settings(tmp_path)

    # When: the loopback listener is configured
    config = _loopback_config(object(), settings)  # type: ignore[arg-type]

    # Then: it binds loopback without TLS and keeps request logs off
    assert (config.host, config.port) == ("127.0.0.1", 7432)
    assert config.ssl_certfile is None
    assert config.access_log is False


def test_lan_listener_uses_tls_and_the_explicit_address(tmp_path: Path) -> None:
    # Given: a prepared LAN endpoint
    endpoint = _endpoint(tmp_path)

    # When: the LAN listener is configured
    config = _lan_config(object(), endpoint)  # type: ignore[arg-type]

    # Then: it serves TLS on the explicit address and leaves lifespan to loopback
    assert (config.host, config.port) == (LAN_ADDRESS, 7433)
    assert config.ssl_certfile == str(endpoint.certificate.certificate_path)
    assert config.ssl_keyfile == str(endpoint.certificate.key_path)
    assert config.lifespan == "off"
    assert endpoint.url == f"https://{LAN_ADDRESS}:7433"


def test_lan_endpoint_is_absent_until_the_owner_enables_it(tmp_path: Path) -> None:
    # Given: an installation that did not enable access from other devices
    # When/Then: no LAN listener is prepared and no certificate is written
    assert serve_module.resolve_lan_endpoint(_settings(tmp_path)) is None
    assert not (tmp_path / "tls").exists()


def test_lan_failure_keeps_the_loopback_service_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: LAN access enabled on a machine with no usable network address
    settings = _settings(tmp_path, lan_enabled=True)

    def _fail(*_: object, **__: object) -> LanEndpoint:
        raise NetworkConfigurationError("No local network address is available.")

    monkeypatch.setattr(serve_module, "prepare_lan_endpoint", _fail)

    # When/Then: startup degrades to loopback instead of failing
    assert serve_module.resolve_lan_endpoint(settings) is None


def test_managed_servers_leave_signal_handling_to_the_process() -> None:
    # Given: the process owns shutdown so all listeners stop together
    original = signal.getsignal(signal.SIGINT)
    server = _ManagedServer.__new__(_ManagedServer)

    # When: a listener runs under its signal context
    with server.capture_signals():
        during = signal.getsignal(signal.SIGINT)

    # Then: uvicorn never replaces the process signal handlers
    assert during is original


def test_desktop_shutdown_command_stops_every_listener() -> None:
    # Given: the managed desktop daemon owns loopback and LAN listeners
    loopback = _ManagedServer.__new__(_ManagedServer)
    lan = _ManagedServer.__new__(_ManagedServer)
    loopback.should_exit = False
    lan.should_exit = False

    # When: the desktop sends its private shutdown command over stdin
    _listen_for_desktop_shutdown([loopback, lan], io.StringIO("ignored\nshutdown\n"))

    # Then: every listener participates in one graceful process shutdown
    assert loopback.should_exit is True
    assert lan.should_exit is True


def test_closed_desktop_control_pipe_stops_the_managed_daemon() -> None:
    # Given: a managed daemon whose desktop control pipe is open
    server = _ManagedServer.__new__(_ManagedServer)
    server.should_exit = False

    # When: the desktop exits and its private input stream reaches EOF
    _listen_for_desktop_shutdown([server], io.StringIO(""))

    # Then: the sidecar does not survive as an orphan process
    assert server.should_exit is True
