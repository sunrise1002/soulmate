"""Local listeners: loopback plaintext for the owner, TLS for paired devices."""

import asyncio
import contextlib
import logging
import os
import signal
import sys
import threading
from collections.abc import Iterable, Iterator
from typing import TextIO

import uvicorn
from fastapi import FastAPI

from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.network import LanEndpoint, NetworkConfigurationError, prepare_lan_endpoint
from soulmate_daemon.tls import CertificateError

LOGGER = logging.getLogger("soulmate.serve")
RUNTIME_READY_TIMEOUT = 30.0
RUNTIME_POLL_INTERVAL = 0.05
DESKTOP_MANAGED_ENV = "_SOULMATE_DESKTOP_MANAGED"
DESKTOP_SHUTDOWN_COMMAND = "shutdown"


class _ManagedServer(uvicorn.Server):
    """A listener whose shutdown is driven by this process, not by uvicorn."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def _loopback_config(app: FastAPI, settings: Settings) -> uvicorn.Config:
    return uvicorn.Config(
        app, host=settings.server.host, port=settings.server.port, access_log=False
    )


def _lan_config(app: FastAPI, endpoint: LanEndpoint) -> uvicorn.Config:
    """Bind the explicit LAN address with TLS; the loopback server owns lifespan."""
    return uvicorn.Config(
        app,
        host=endpoint.host,
        port=endpoint.port,
        access_log=False,
        lifespan="off",
        ssl_certfile=str(endpoint.certificate.certificate_path),
        ssl_keyfile=str(endpoint.certificate.key_path),
    )


def resolve_lan_endpoint(settings: Settings) -> LanEndpoint | None:
    """Return the LAN endpoint when enabled, keeping loopback usable on failure."""
    if not settings.network.lan_enabled:
        return None
    try:
        return prepare_lan_endpoint(settings)
    except (CertificateError, NetworkConfigurationError, OSError):
        LOGGER.warning("LAN access is enabled but could not be configured; serving loopback only.")
        return None


async def _wait_for_runtime(app: FastAPI) -> None:
    waited = 0.0
    while getattr(app.state, "runtime", None) is None and waited < RUNTIME_READY_TIMEOUT:
        await asyncio.sleep(RUNTIME_POLL_INTERVAL)
        waited += RUNTIME_POLL_INTERVAL


def _request_shutdown(servers: Iterable[uvicorn.Server]) -> None:
    for server in servers:
        server.should_exit = True


def _listen_for_desktop_shutdown(servers: Iterable[uvicorn.Server], input_stream: TextIO) -> None:
    """Stop managed listeners when the desktop closes their private stdin pipe."""
    try:
        for line in input_stream:
            if line.strip() == DESKTOP_SHUTDOWN_COMMAND:
                break
    except (OSError, ValueError):
        pass
    _request_shutdown(servers)


def _start_desktop_shutdown_listener(servers: Iterable[uvicorn.Server]) -> None:
    if os.environ.get(DESKTOP_MANAGED_ENV) != "1":
        return
    threading.Thread(
        target=_listen_for_desktop_shutdown,
        args=(servers, sys.stdin),
        name="soulmate-desktop-shutdown",
        daemon=True,
    ).start()


async def _run_listeners(app: FastAPI, configs: list[uvicorn.Config]) -> None:
    servers = [_ManagedServer(config) for config in configs]
    _start_desktop_shutdown_listener(servers)
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(name, _request_shutdown, servers)
    primary = asyncio.create_task(servers[0].serve(), name="soulmate-loopback")
    await _wait_for_runtime(app)
    secondary = [
        asyncio.create_task(server.serve(), name=f"soulmate-lan-{index}")
        for index, server in enumerate(servers[1:])
    ]
    try:
        await primary
    finally:
        _request_shutdown(servers)
        for task in secondary:
            with contextlib.suppress(asyncio.CancelledError):
                await task


def serve(settings: Settings) -> None:
    """Start the local service, adding the TLS listener when LAN access is on."""
    endpoint = resolve_lan_endpoint(settings)
    app = create_app(settings, lan=endpoint)
    configs = [_loopback_config(app, settings)]
    if endpoint is not None:
        configs.append(_lan_config(app, endpoint))
    if len(configs) == 1:
        server = uvicorn.Server(configs[0])
        _start_desktop_shutdown_listener([server])
        server.run()
        return
    asyncio.run(_run_listeners(app, configs))
