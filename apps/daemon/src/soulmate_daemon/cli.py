"""Minimal development entry point for the Phase 0 daemon shell."""

import argparse
from pathlib import Path

import uvicorn

from soulmate_daemon.app import create_app
from soulmate_daemon.config import ConfigurationError, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="decision-twin", description="Soulmate local daemon")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the empty local development daemon")
    serve.add_argument("--config", type=Path, help="Path to a TOML configuration file")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
    except ConfigurationError as exc:
        parser.error(str(exc))
    uvicorn.run(
        create_app(settings),
        host=settings.server.host,
        port=settings.server.port,
        access_log=False,
    )
