---
name: Feature request
about: Propose a new capability or improvement for docpipe-maestro
title: "feat: "
labels: enhancement
assignees: ""
---

## Problem Statement

Describe the RAG pipeline limitation or use case you want to solve.

## Scope Check

Confirm how this fits within `docpipe-maestro`'s library-and-CLI scope (see [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md)):
- [ ] Reachable through the minimal Python API or `docpipe-maestro` CLI (no HTTP server, auth middleware, session state, or UI).
- [ ] Preserves Phase 1 (ingest) vs Phase 2 (read-only query) separation and Library Purity (no config reading in library modules).

## Proposed Behavior

Describe the proposed API signature, CLI flag/subcommand, or chunking/retrieval behavior.
