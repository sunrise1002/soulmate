# Migrations

SQLite migrations are packaged with the adapter under
`packages/storage-sqlite/src/soulmate_storage_sqlite/migrations/` so installed
daemon wheels can migrate without a source checkout. Phase 1 migration
`0001_phase_1` creates the six base tables. The daemon applies migrations
automatically before serving requests or starting its worker.

Every subsequent persistent schema change requires a new versioned migration and
upgrade/restart tests. Never edit an already released migration to represent a new
schema revision.
