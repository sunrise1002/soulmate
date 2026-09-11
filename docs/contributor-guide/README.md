# Contributor guide

This directory is the operational source of truth for humans and AI agents making
changes to Soulmate. Read the documents in this order:

1. [Engineering conventions](conventions.md) — language, architecture, code, test,
   privacy, and documentation rules.
2. [Contribution workflow](workflow.md) — issue selection, branches, commits, pull
   requests, reviews, and merges.
3. [Quality gates](quality-gates.md) — local commands, Git hooks, CI checks, and the
   policy for justified exceptions.
4. [Repository settings](repository-settings.md) — maintainer-side GitHub rules that
   cannot be enforced by files in this repository alone.
5. [Configuration](configuration.md) — local daemon configuration and environment
   overrides.

The root [agent instructions](../../AGENTS.md), [phase status](../phase-status.md),
and original [technical specification](../../Open%20Personal%20Decision%20Agent%20%E2%80%94%20Technical%20Product%20Specification%20%26%20Implementation%20Plan.md)
remain authoritative. If documents conflict, follow the specification, explicit
user instructions, the current phase gate, and then the most specific contributor
rule in that order.

Rules are enforced as close to the contributor as practical: editor defaults,
Ruff and mypy, tests, Git hooks, and GitHub Actions. Documentation describes the
intent; executable configuration is the final authority for exact tool behavior.
