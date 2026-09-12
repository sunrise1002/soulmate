"""Static web client served by the daemon for browsers on any owner device."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

INDEX_FILENAME = "index.html"


def mount_web_client(app: FastAPI, directory: Path | None) -> bool:
    """Serve a built web client at the service root when a bundle is present."""
    if directory is None or not (directory / INDEX_FILENAME).is_file():
        return False
    app.mount("/", StaticFiles(directory=directory, html=True), name="web-client")
    return True
