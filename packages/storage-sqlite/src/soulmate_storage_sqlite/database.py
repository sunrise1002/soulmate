"""SQLite engine setup, migrations, and local database diagnostics."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class DatabaseCheck:
    reachable: bool
    integrity: str
    journal_mode: str
    foreign_keys: bool
    current_revision: str | None
    head_revision: str


class Database:
    """Own a SQLite engine without opening or creating it at import time."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.engine: Engine | None = None
        self.session_factory: sessionmaker[Session] | None = None

    @property
    def migration_config(self) -> Config:
        config = Config()
        migrations = Path(__file__).parent / "migrations"
        config.set_main_option("script_location", str(migrations))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.path.as_posix()}")
        return config

    def connect(self) -> None:
        if self.engine is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{self.path.as_posix()}")

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection: object, _record: object) -> None:
            cursor = cast(sqlite3.Connection, connection).cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

        self.engine = engine
        self.session_factory = sessionmaker(engine, expire_on_commit=False)

    def migrate(self) -> None:
        self.connect()
        command.upgrade(self.migration_config, "head")

    def current_revision(self) -> str | None:
        engine = self._engine()
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def head_revision(self) -> str:
        from alembic.script import ScriptDirectory

        head = ScriptDirectory.from_config(self.migration_config).get_current_head()
        if head is None:
            raise RuntimeError("No migration head is configured.")
        return head

    def check(self) -> DatabaseCheck:
        engine = self._engine()
        with engine.connect() as connection:
            integrity = str(connection.execute(text("PRAGMA quick_check")).scalar_one())
            journal_mode = str(connection.execute(text("PRAGMA journal_mode")).scalar_one())
            foreign_keys = bool(connection.execute(text("PRAGMA foreign_keys")).scalar_one())
        return DatabaseCheck(
            reachable=True,
            integrity=integrity,
            journal_mode=journal_mode,
            foreign_keys=foreign_keys,
            current_revision=self.current_revision(),
            head_revision=self.head_revision(),
        )

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        self.engine = None
        self.session_factory = None

    def _engine(self) -> Engine:
        if self.engine is None:
            raise RuntimeError("Database is not connected.")
        return self.engine

    def sessions(self) -> sessionmaker[Session]:
        if self.session_factory is None:
            raise RuntimeError("Database is not connected.")
        return self.session_factory
