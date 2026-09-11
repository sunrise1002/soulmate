# Security policy

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue, discussion, log, or
pull request. Use [GitHub private vulnerability reporting](https://github.com/sunrise1002/soulmate/security/advisories/new)
and include the affected version, impact, minimal reproduction, and suggested
mitigation if known. Remove personal data, real credentials, and private prompts.

Maintainers should acknowledge a report within seven days, coordinate validation
and remediation privately, and publish an advisory after a fix or documented risk
decision is available. No bounty or response-time guarantee is currently offered.

## Supported versions

Before the first stable release, only the latest commit on `main` is supported.
After stable releases begin, this section must list supported release lines and
security-update policy explicitly.

## Security-sensitive changes

Changes involving authentication, permissions, networking, secrets, encryption,
egress, data deletion, backups, imports, or audit logs require explicit threat and
privacy consideration in the pull request. Never use production personal data or
live credentials in a reproduction or test fixture.
