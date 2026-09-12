# Soulmate Connector SDK

This package defines the stable, provider-neutral contract for optional source
connectors. A connector is an independently installable Python package that
registers one `soulmate.connectors` entry point and emits validated `ConnectorEvent`
records. The daemon assigns local IDs, wraps accepted records as provenance-linked
`RawEvent` values, and never lets a connector mutate Evidence or the Personal Model.

Each manifest must exactly declare its data-read, network, credential, and learning
permissions. The owner grants those permissions when enabling the connector.
Credentials come from process environment variables and are never persisted in
SQLite. Network-capable connectors receive the daemon's allowlisted, privacy-mode
aware HTTP client through `ConnectorContext`; they should not open network clients
directly.

```toml
[project.entry-points."soulmate.connectors"]
example = "example_connector:ExampleConnector"
```

The `soulmate-local-notes-connector` workspace package is the reference
implementation.
