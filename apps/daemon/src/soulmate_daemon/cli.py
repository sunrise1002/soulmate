"""Command-line lifecycle and diagnostics for the local daemon."""

import argparse
import getpass
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from alembic.util.exc import CommandError
from soulmate_connector_sdk import discover_connectors
from soulmate_core.evaluation import evaluate_dataset, load_dataset
from soulmate_core.importing import ImportFormat
from soulmate_core.preferences import ModelRebuilder
from soulmate_mcp.server import main as mcp_main
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy.exc import SQLAlchemyError

from soulmate_daemon.config import ConfigurationError, Settings, load_settings
from soulmate_daemon.imports import ChatImportService
from soulmate_daemon.portability import (
    ARCHIVE_MAGIC,
    ArchiveService,
    PortabilityError,
    restore_archive,
)
from soulmate_daemon.providers import build_provider
from soulmate_daemon.serve import serve
from soulmate_daemon.system import DEFAULT_PROFILE_ID, ensure_installation


def _service_url(settings: Settings, path: str) -> str:
    host = f"[{settings.server.host}]" if ":" in settings.server.host else settings.server.host
    return f"http://{host}:{settings.server.port}{path}"


def _read_json(url: str) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("Service returned an invalid response.")
    return value


def _status(settings: Settings) -> int:
    try:
        result = {
            "reachable": True,
            "health": _read_json(_service_url(settings, "/v1/health")),
            "system": _read_json(_service_url(settings, "/v1/system/info")),
        }
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        result = {"reachable": False, "error": "Local service is unavailable."}
        code = 1
    else:
        health = result["health"]
        code = 0 if isinstance(health, dict) and health.get("status") == "healthy" else 1
    print(json.dumps(result, sort_keys=True))
    return code


def _writable_location(path: Path) -> bool:
    candidate = path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def _port_available(settings: Settings) -> bool:
    family = socket.AF_INET6 if ":" in settings.server.host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((settings.server.host, settings.server.port)) != 0


def _doctor(settings: Settings) -> int:
    database_path = settings.database_path
    checks: dict[str, object] = {
        "loopback_binding": settings.server.host in {"127.0.0.1", "::1"},
        "storage_location_writable": _writable_location(database_path),
        "database_exists": database_path.is_file(),
        "port_available": _port_available(settings),
        "provider_check": _provider_check(settings),
        "vector_backend_check": "deferred_until_vector_storage_is_implemented",
    }
    if database_path.is_file():
        database = Database(database_path)
        try:
            database.connect()
            database_check = database.check()
            checks.update(
                database_integrity=database_check.integrity,
                journal_mode=database_check.journal_mode,
                foreign_keys=database_check.foreign_keys,
                migration_current=(database_check.current_revision == database_check.head_revision),
            )
        except (CommandError, OSError, RuntimeError, SQLAlchemyError):
            checks["database_error"] = "Database diagnostics failed."
        finally:
            if database.engine is not None:
                database.engine.dispose()
    healthy = (
        all(
            checks.get(key) is expected
            for key, expected in {
                "loopback_binding": True,
                "storage_location_writable": True,
                "database_exists": True,
                "foreign_keys": True,
                "migration_current": True,
            }.items()
        )
        and checks.get("database_integrity") == "ok"
    )
    print(json.dumps({"healthy": healthy, "checks": checks}, sort_keys=True))
    return 0 if healthy else 1


def _provider_check(settings: Settings) -> str:
    try:
        provider = build_provider(settings)
    except ValueError:
        return "not_configured"
    return f"configured:{provider.model_name}"


def _rebuild_model(settings: Settings) -> int:
    database = Database(settings.database_path)
    try:
        database.migrate()
        repositories = Repositories(database.sessions())
        ensure_installation(repositories.system_metadata, repositories.profiles)
        snapshot = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
            DEFAULT_PROFILE_ID
        )
    except (CommandError, OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        print(
            json.dumps(
                {"rebuilt": False, "error": f"Model rebuild failed with {type(exc).__name__}."},
                sort_keys=True,
            )
        )
        return 1
    finally:
        database.close()
    print(
        json.dumps(
            {
                "rebuilt": True,
                "profile_id": snapshot.profile_id,
                "snapshot_version": snapshot.version,
                "evidence_revision": snapshot.evidence_revision,
                "algorithm_version": snapshot.algorithm_version,
            },
            sort_keys=True,
        )
    )
    return 0


def _evaluate(dataset_path: Path | None) -> int:
    try:
        report = evaluate_dataset(load_dataset(dataset_path))
    except ValueError as exc:
        print(json.dumps({"evaluated": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"evaluated": True, **report.as_dict()}, sort_keys=True))
    return 0


def _list_connectors() -> int:
    catalog = discover_connectors()
    print(
        json.dumps(
            {
                "connectors": [
                    {
                        "connector_id": connector.manifest.connector_id,
                        "name": connector.manifest.name,
                        "version": connector.manifest.version,
                        "permissions": [
                            permission.value for permission in connector.manifest.permissions
                        ],
                    }
                    for connector in sorted(
                        catalog.connectors.values(), key=lambda item: item.manifest.connector_id
                    )
                ],
                "load_failures": [
                    {
                        "entry_point": failure.entry_point,
                        "error_type": failure.error_type,
                    }
                    for failure in catalog.failures
                ],
            },
            sort_keys=True,
        )
    )
    return 0 if not catalog.failures else 1


def _default_archive_path(settings: Settings, kind: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    extension = ".dtwb" if kind == "backup" else ".dtw"
    filename = f"soulmate-{kind}-{timestamp}{extension}"
    candidate = settings.data_dir.expanduser().resolve() / "backups" / filename
    if not candidate.exists():
        return candidate
    return candidate.with_stem(f"{candidate.stem}-{datetime.now(UTC).microsecond:06d}")


def _passphrase(path: Path | None, prompt: str) -> str:
    if path is None:
        try:
            return getpass.getpass(prompt)
        except EOFError as exc:
            raise PortabilityError(
                "A passphrase prompt requires a terminal or --passphrase-file."
            ) from exc
    try:
        return path.expanduser().read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, OSError, UnicodeDecodeError) as exc:
        raise PortabilityError("The passphrase file could not be read.") from exc


def _create_archive(
    settings: Settings,
    *,
    kind: str,
    output: Path | None,
    passphrase_file: Path | None = None,
) -> int:
    database = Database(settings.database_path)
    try:
        database.migrate()
        repositories = Repositories(database.sessions())
        ensure_installation(repositories.system_metadata, repositories.profiles)
        passphrase = None
        if kind == "export":
            passphrase = _passphrase(passphrase_file, "Export passphrase: ")
        result = ArchiveService(settings, database).create(
            output or _default_archive_path(settings, kind), passphrase=passphrase
        )
    except (OSError, RuntimeError, SQLAlchemyError, PortabilityError) as exc:
        print(
            json.dumps(
                {"created": False, "error": f"Archive creation failed: {exc}"},
                sort_keys=True,
            )
        )
        return 1
    finally:
        database.close()
    print(
        json.dumps(
            {
                "created": True,
                "path": str(result.path),
                "encrypted": result.encrypted,
                "size_bytes": result.size_bytes,
                "sha256": result.sha256,
                "schema_revision": result.schema_revision,
            },
            sort_keys=True,
        )
    )
    return 0


def _restore(settings: Settings, archive: Path, passphrase_file: Path | None) -> int:
    passphrase = None
    try:
        with archive.expanduser().open("rb") as source:
            encrypted = source.read(len(ARCHIVE_MAGIC)) == ARCHIVE_MAGIC
    except OSError as exc:
        print(json.dumps({"restored": False, "error": str(exc)}, sort_keys=True))
        return 1
    if encrypted or passphrase_file is not None:
        try:
            passphrase = _passphrase(passphrase_file, "Archive passphrase: ")
        except PortabilityError as exc:
            print(json.dumps({"restored": False, "error": str(exc)}, sort_keys=True))
            return 1
    try:
        result = restore_archive(settings, archive, passphrase)
    except (OSError, RuntimeError, SQLAlchemyError, PortabilityError) as exc:
        print(json.dumps({"restored": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "restored": True,
                "schema_revision_before": result.schema_revision_before,
                "schema_revision_after": result.schema_revision_after,
                "snapshot_version": result.snapshot_version,
                "installation_id": result.installation_id,
            },
            sort_keys=True,
        )
    )
    return 0


def _import_history(
    settings: Settings, path: Path, import_format: ImportFormat, name: str | None
) -> int:
    try:
        content = path.expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            json.dumps(
                {"imported": False, "error": f"Import file could not be read: {exc}"},
                sort_keys=True,
            )
        )
        return 1
    database = Database(settings.database_path)
    try:
        database.migrate()
        repositories = Repositories(database.sessions())
        ensure_installation(repositories.system_metadata, repositories.profiles)
        result = ChatImportService(repositories.sources).import_content(
            DEFAULT_PROFILE_ID,
            name or path.name,
            content,
            import_format,
        )
    except (OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        print(json.dumps({"imported": False, "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        database.close()
    print(
        json.dumps(
            {
                "imported": True,
                "source_id": result.source.id,
                "format": result.detected_format.value,
                "conversation_count": result.conversation_count,
                "message_count": result.message_count,
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decision-twin", description="Soulmate local daemon")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("serve", "Start the local Soulmate daemon"),
        ("status", "Query the running local daemon"),
        ("doctor", "Inspect local configuration and persistence"),
        ("rebuild-model", "Rebuild the Personal Model from stored evidence"),
    ):
        subcommand = commands.add_parser(command, help=help_text)
        subcommand.add_argument("--config", type=Path, help="Path to a TOML configuration file")
    evaluate = commands.add_parser("evaluate", help="Run reproducible decision evaluation")
    evaluate.add_argument("--dataset", type=Path, help="Path to an evaluation JSON dataset")
    commands.add_parser("mcp", help="Run the scoped MCP stdio adapter")
    commands.add_parser("connectors", help="List installed connector plugins")
    for command, help_text in (
        ("backup", "Create a local credential-free backup archive"),
        ("export", "Create an encrypted portable archive"),
    ):
        archive = commands.add_parser(command, help=help_text)
        archive.add_argument("--config", type=Path, help="Path to a TOML configuration file")
        archive.add_argument("--output", type=Path, help="Archive output path")
        if command == "export":
            archive.add_argument(
                "--passphrase-file",
                type=Path,
                help="Read the passphrase from a local file instead of prompting",
            )
    restore = commands.add_parser("restore", help="Restore a backup into a fresh installation")
    restore.add_argument("archive", type=Path, help="Backup or encrypted portable archive")
    restore.add_argument("--config", type=Path, help="Path to a TOML configuration file")
    restore.add_argument(
        "--passphrase-file", type=Path, help="Read the archive passphrase from a file"
    )
    import_command = commands.add_parser("import", help="Import static chat history")
    import_command.add_argument("path", type=Path, help="UTF-8 JSON, Markdown, or text file")
    import_command.add_argument("--config", type=Path, help="Path to a TOML configuration file")
    import_command.add_argument(
        "--format",
        type=ImportFormat,
        choices=list(ImportFormat),
        default=ImportFormat.AUTO,
    )
    import_command.add_argument("--name", help="Owner-visible source name")
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.command == "evaluate":
        raise SystemExit(_evaluate(args.dataset))
    if args.command == "mcp":
        mcp_main()
        return
    if args.command == "connectors":
        raise SystemExit(_list_connectors())
    try:
        settings = load_settings(args.config)
    except ConfigurationError as exc:
        parser.error(str(exc))
    if args.command == "serve":
        serve(settings)
        return
    if args.command == "status":
        raise SystemExit(_status(settings))
    if args.command == "doctor":
        raise SystemExit(_doctor(settings))
    if args.command == "backup":
        raise SystemExit(_create_archive(settings, kind="backup", output=args.output))
    if args.command == "export":
        raise SystemExit(
            _create_archive(
                settings,
                kind="export",
                output=args.output,
                passphrase_file=args.passphrase_file,
            )
        )
    if args.command == "restore":
        raise SystemExit(_restore(settings, args.archive, args.passphrase_file))
    if args.command == "import":
        raise SystemExit(_import_history(settings, args.path, args.format, args.name))
    raise SystemExit(_rebuild_model(settings))
