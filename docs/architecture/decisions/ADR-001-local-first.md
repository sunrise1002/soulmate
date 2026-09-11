# ADR-001: Local-first architecture

Status: Accepted for architecture; implementation follows the roadmap.

## Context

The Personal Model belongs to one owner and must remain useful without a Soulmate
cloud account or centralized infrastructure (specification sections 1–3, 7, 68).

## Decision

Use a self-hosted modular monolith. Persist personal data on owner-controlled
storage. Default to loopback access and strict-local inference. Introduce external
access only through explicit configuration and privacy/security boundaries.

## Consequences

Local installation, backup, and inspection remain first-class requirements.
Cross-device access needs deliberate pairing and transport security. No central
SaaS service, microservices, queues, or cloud synchronization is required.
