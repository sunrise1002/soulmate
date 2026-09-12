# SQLite storage adapter

This package implements the SQLite persistence ports with SQLAlchemy 2 and ships
the Alembic migration environment inside its wheel. It enables WAL, foreign-key
enforcement, and a busy timeout on every application connection. Phase 2 adds
provenance-bearing evidence, monotonic evidence revisions, derived model tables,
and immutable versioned snapshots.
Phase 3 adds conversations and source-message provenance. Phase 4 adds decisions,
structured options, model-snapshot-bound predictions, and actual resolutions.
Phase 7 adds hashed pairing tokens and paired-device credentials. Phase 8 adds
active questions and answers, decision outcomes, and snapshot-bound advice.

The adapter depends inward on `soulmate-core`; core never imports this package or
SQLAlchemy. Schema changes require a new migration under
`src/soulmate_storage_sqlite/migrations/versions/` plus migration and restart
tests.
