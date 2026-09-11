# SQLite storage adapter

This package implements the SQLite persistence ports with SQLAlchemy 2 and ships
the Alembic migration environment inside its wheel. It enables WAL, foreign-key
enforcement, and a busy timeout on every application connection. Phase 2 adds
provenance-bearing evidence, monotonic evidence revisions, derived model tables,
and immutable versioned snapshots.

The adapter depends inward on `soulmate-core`; core never imports this package or
SQLAlchemy. Schema changes require a new migration under
`src/soulmate_storage_sqlite/migrations/versions/` plus migration and restart
tests.
