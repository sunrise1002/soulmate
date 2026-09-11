# Privacy and security boundaries

The foundation binds to loopback only, has no product routes, performs no provider
calls, creates no personal database, and includes no telemetry. Configuration error
messages identify fields without printing their rejected values.

Future work must keep persistence and audit logs local, hash API credentials,
store provider secrets in an operating-system credential store or encrypted
fallback, validate provider output, enforce central network egress policy, and
minimize context sent externally. LAN access requires explicit activation and
encrypted pairing. These are architecture requirements, not completed features.

Do not put personal data or secrets into issue reports, logs, fixtures, source
control, or CI artifacts. Use synthetic fixtures and keep runtime data outside
tracked source. See ADR-001, ADR-005, ADR-006, and ADR-008.
