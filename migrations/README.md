# Migrations

SQLite migrations are packaged with the adapter under
`packages/storage-sqlite/src/soulmate_storage_sqlite/migrations/` so installed
daemon wheels can migrate without a source checkout. Phase 1 migration
`0001_phase_1` creates the six base tables. Phase 2 migration `0002_phase_2` adds
evidence, revision tracking, derived model state, and versioned snapshots. The
Phase 3 migration `0003_phase_3` adds conversations, messages, and explicit model
and source-message provenance for extracted evidence. Phase 4 migration
`0004_phase_4` adds decision events, options, snapshot-bound predictions, and
resolutions. Phase 7 migration `0005_phase_7` adds secure pairing records. Phase 8
migration `0006_phase_8` adds active questions, answers, outcomes, and versioned
advice. The daemon applies migrations automatically before serving requests or
starting its worker.

Every subsequent persistent schema change requires a new versioned migration and
upgrade/restart tests. Never edit an already released migration to represent a new
schema revision.
