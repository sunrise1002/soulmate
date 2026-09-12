"""Build and smoke-test the platform-specific desktop daemon sidecar."""

import argparse
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-missing", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = _target_triple()
    if not _stage_web_client(root):
        print("web client bundle missing; the sidecar will serve the API only", file=sys.stderr)
    extension = ".exe" if sys.platform == "win32" else ""
    output = root / "apps" / "desktop" / "src-tauri" / "binaries"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"decision-twin-{target}{extension}"
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
                "decision-twin",
                "--distpath",
                str(temporary_path / "dist"),
                "--workpath",
                str(temporary_path / "build"),
                "--specpath",
                str(temporary_path),
                "--collect-all",
                "soulmate_storage_sqlite",
                "--collect-data",
                "soulmate_core",
                "--collect-data",
                "soulmate_daemon",
                str(root / "apps" / "daemon" / "sidecar.py"),
            ],
            cwd=root,
            check=True,
        )
        built = temporary_path / "dist" / f"decision-twin{extension}"
        shutil.copy2(built, destination)
    if sys.platform != "win32":
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
    subprocess.run(  # noqa: S603 -- destination is the sidecar produced above.
        [str(destination), "--help"], check=True, capture_output=True, text=True
    )
    subprocess.run(  # noqa: S603 -- destination is the sidecar produced above.
        [str(destination), "evaluate"], check=True, capture_output=True, text=True, timeout=30
    )
    print(destination.relative_to(root))


if __name__ == "__main__":
    main()
