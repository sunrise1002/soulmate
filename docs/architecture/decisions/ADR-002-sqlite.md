# ADR-002: SQLite as default persistence

Status: Accepted for architecture; persistence starts in Phase 1.

## Context

A single-owner installation needs simple setup, offline operation, restart
durability, and portable backups (specification sections 9–12, 51, 54).

## Decision

Use SQLite with WAL and foreign keys enabled, SQLAlchemy 2 adapters, and Alembic
migrations. Core owns repository ports without importing database libraries.
Prefer sqlite-vec behind a VectorStore port; retain application-side cosine
similarity as a fallback. Store attachments in local content-addressed files.

## Consequences

No database server or dedicated vector service is required. Every schema change
needs a migration. Future backup must handle live WAL state correctly. Optional
PostgreSQL support is a future adapter, not a baseline dependency.
