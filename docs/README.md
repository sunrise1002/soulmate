# Documentation

Start with **[index.html](index.html)** ([bản tiếng Việt](index.vi.html)) — the single-page project guide covering
vision, core concepts, architecture, technology, setup, usage, API, privacy, and
current status. Open it in a browser; it is self-contained and needs no build step.

Everything else here is the detailed source of truth behind that page.

## Map

| Document | Use it for |
| --- | --- |
| [index.html](index.html) ([Tiếng Việt](index.vi.html)) | Orientation for newcomers and a consolidated reference for everyone |
| [phase-status.md](phase-status.md) | What is built, what is authorized, and the current phase gate |
| [phases/](phases/README.md) | Durable per-phase plan, verification, known issues, and handoff |
| [architecture/](architecture/README.md) | Layering rules and ADR-001 through ADR-013 |
| [security/](security/README.md) | Privacy and security boundaries in force |
| [contributor-guide/](contributor-guide/README.md) | Conventions, workflow, quality gates, repository settings, configuration |

Repository-root documents: the
[technical specification](<../Open Personal Decision Agent — Technical Product Specification & Implementation Plan.md>)
(authoritative product definition), [README](../README.md),
[CONTRIBUTING](../CONTRIBUTING.md), [AGENTS](../AGENTS.md),
[SECURITY](../SECURITY.md), and [CHANGELOG](../CHANGELOG.md).

## Precedence

When documents disagree, follow the specification, then explicit user
instructions, then the current phase gate, then the most specific contributor
rule. Documentation describes intent; executable configuration is the final
authority on exact tool behavior.

Keep `index.html` in sync when a change alters product scope, architecture,
setup, configuration defaults, the API surface, or the privacy boundary.
