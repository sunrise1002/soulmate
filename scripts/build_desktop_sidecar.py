"""Build and smoke-test the platform-specific desktop daemon sidecar."""

import argparse
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The sidecar was about 43 MB before the embedding runtimes and about 150 MB after
# them; the budget leaves room for patch releases without hiding a jump.
MAX_SIDECAR_MB = 220


def _target_triple() -> str:
    rustc = shutil.which("rustc")
    if rustc is None:
        raise RuntimeError("Rust is required to identify the desktop target triple.")
    result = subprocess.run(  # noqa: S603 -- rustc is resolved from the developer toolchain.
        [rustc, "--print", "host-tuple"],
        check=True,
        capture_output=True,
        text=True,
    )
    target = result.stdout.strip()
    if not target:
        raise RuntimeError("Rust did not report a host target triple.")
    return target


def _stage_web_client(root: Path) -> bool:
    """Copy a built web client into the daemon package so the sidecar serves it."""
    source = root / "apps" / "web" / "dist"
    destination = root / "apps" / "daemon" / "src" / "soulmate_daemon" / "web_client"
    if destination.is_dir():
        shutil.rmtree(destination)
    if not (source / "index.html").is_file():
        return False
    shutil.copytree(source, destination)
    return True


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _smoke_test_managed_shutdown(executable: Path) -> None:
    """Verify that desktop shutdown exits the full one-file process tree."""
    port = _unused_loopback_port()
    with tempfile.TemporaryDirectory(prefix="soulmate-managed-sidecar-") as temporary:
        temporary_path = Path(temporary)
        environment = os.environ.copy()
        environment.update(
            {
                "DATA_DIR": str(temporary_path / "data"),
                "_SOULMATE_DESKTOP_MANAGED": "1",
                "SOULMATE_NETWORK__LAN_ENABLED": "false",
                "SOULMATE_REMOTE_BACKUP__BACKEND": "disabled",
                "SOULMATE_SERVER__HOST": "127.0.0.1",
                "SOULMATE_SERVER__PORT": str(port),
            }
        )
        environment.pop("SOULMATE_CONFIG_FILE", None)
        for _ in range(2):
            process = subprocess.Popen(  # noqa: S603 -- executable is built above.
                [str(executable), "serve"],
                cwd=temporary_path,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = time.monotonic() + 30
                while not _port_is_open(port):
                    if process.poll() is not None:
                        output = process.stdout.read() if process.stdout is not None else ""
                        raise RuntimeError(f"Managed sidecar exited during startup:\n{output}")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Managed sidecar did not bind its loopback port.")
                    time.sleep(0.05)

                if process.stdin is None:
                    raise RuntimeError("Managed sidecar stdin pipe is unavailable.")
                process.stdin.write("shutdown\n")
                process.stdin.flush()
                process.wait(timeout=15)
                output = process.stdout.read() if process.stdout is not None else ""
                if process.returncode != 0:
                    raise RuntimeError(f"Managed sidecar did not stop cleanly:\n{output}")
                if _port_is_open(port):
                    raise RuntimeError("Managed sidecar left its loopback listener running.")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


def _check_size(destination: Path, limit_bytes: int) -> int:
    """Keep the bundled embedding runtimes from growing the sidecar unnoticed."""
    size = destination.stat().st_size
    print(f"sidecar size: {size / 1e6:.1f} MB (limit {limit_bytes / 1e6:.0f} MB)", file=sys.stderr)
    if size > limit_bytes:
        raise RuntimeError(
            f"The sidecar is {size / 1e6:.1f} MB, above the {limit_bytes / 1e6:.0f} MB budget."
        )
    return size


def _smoke_test_embedding_runtime(executable: Path) -> None:
    """Verify the bundled embedding runtimes import; no model is downloaded or loaded."""
    result = subprocess.run(  # noqa: S603 -- executable is the sidecar built above.
        [str(executable), "embedding-model"], check=True, capture_output=True, text=True, timeout=60
    )
    report = json.loads(result.stdout)
    if not report["runtime_available"]:
        raise RuntimeError(f"The sidecar cannot load its embedding runtimes: {report['runtime']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-missing", action="store_true")
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=MAX_SIDECAR_MB,
        help="Fail when the packaged sidecar grows past this size.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = _target_triple()
    if not _stage_web_client(root):
        print("web client bundle missing; the sidecar will serve the API only", file=sys.stderr)
    extension = ".exe" if sys.platform == "win32" else ""
    output = root / "apps" / "desktop" / "src-tauri" / "binaries"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"soulmate-{target}{extension}"
    if args.if_missing and destination.is_file():
        print(destination.relative_to(root))
        return
    with tempfile.TemporaryDirectory(prefix="soulmate-sidecar-") as temporary:
        temporary_path = Path(temporary)
        subprocess.run(  # noqa: S603 -- executable and arguments are controlled build inputs.
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--clean",
                "--noconfirm",
                "--onefile",
                "--name",
                "soulmate",
                "--distpath",
                str(temporary_path / "dist"),
                "--workpath",
                str(temporary_path / "build"),
                "--specpath",
                str(temporary_path),
                "--collect-all",
                "soulmate_connector_local",
                "--collect-all",
                "soulmate_connector_sdk",
                "--copy-metadata",
                "soulmate-local-notes-connector",
                "--collect-all",
                "soulmate_storage_sqlite",
                "--collect-data",
                "soulmate_core",
                "--collect-data",
                "soulmate_daemon",
                # Local embeddings (ADR-016): the runtimes are imported lazily, so
                # they are collected explicitly instead of being found by analysis.
                "--collect-all",
                "onnxruntime",
                "--collect-all",
                "tokenizers",
                "--collect-submodules",
                "numpy",
                str(root / "apps" / "daemon" / "sidecar.py"),
            ],
            cwd=root,
            check=True,
        )
        built = temporary_path / "dist" / f"soulmate{extension}"
        shutil.copy2(built, destination)
    if sys.platform != "win32":
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
    subprocess.run(  # noqa: S603 -- destination is the sidecar produced above.
        [str(destination), "--help"], check=True, capture_output=True, text=True
    )
    subprocess.run(  # noqa: S603 -- destination is the sidecar produced above.
        [str(destination), "evaluate"], check=True, capture_output=True, text=True, timeout=30
    )
    subprocess.run(  # noqa: S603 -- verifies bundled connector metadata and imports.
        [str(destination), "connectors"], check=True, capture_output=True, text=True, timeout=30
    )
    _smoke_test_embedding_runtime(destination)
    _smoke_test_managed_shutdown(destination)
    _check_size(destination, args.max_size_mb * 1_000_000)
    print(destination.relative_to(root))


if __name__ == "__main__":
    main()
