# Siderfold

Siderfold is an MVP website for collecting and exploring support programs:
grants, accelerators, scholarships, funding sources, deadlines, and related
analytics. The repository combines the local frontend MVP with a backend data
pipeline for controlled source ingestion and review.

## Current Version

`v0.8.0` combines an allowlisted source-ingestion contour with a public catalog
that can use the backend API:

- Python/FastAPI/PostgreSQL backend with canonical, provenance, staging, review,
  and read-API layers;
- allowlisted adapters for the Potanin source and Telegram discovery, with
  fixtures, data-quality checks, idempotency, and no automatic publication;
- deterministic deduplication and separate canonical/discovery review queues;
- a local one-shot scheduler command with locking, bounded retries, rate limits,
  execution metrics, and a recovery runbook.
- published-only public API with filters, Russian word-form search and bounded
  typo tolerance;
- an explicit frontend API mode with loading, empty and safe error states;
- reproducible quality snapshots and protected operator actions for review,
  archival and republishing.

The frontend uses the public API by default. Seed data remains available only
through an explicit development/demo mode. It keeps local preferences and
transparent demo analytics; those are not claims about the complete support
market.

The project is intended to grow into a fuller platform with server-backed
accounts and data, synchronization, and a richer analytics interface.

## Tech Stack

- React 19
- TypeScript
- Vite
- Tailwind CSS
- GSAP
- Vitest and Testing Library
- Playwright

## Getting Started

```bash
cd site
npm install
npm run dev
```

The local development server runs on `127.0.0.1` by default.

## Available Scripts

Run commands from the `site` directory:

```bash
npm run dev
npm test
npm run build
npm run test:e2e
```

- `npm run dev` starts the local Vite server.
- `npm test` runs unit and component tests.
- `npm run build` checks TypeScript and creates a production build.
- `npm run test:e2e` runs Playwright end-to-end tests.

## Project Structure

```txt
site/
  src/
    components/   React screens and shared UI components
    data/         Seed support program and source data
    lib/          Catalog, analytics, and formatting helpers
    motion/       Animation helpers
    test/         Test setup
  e2e/            Playwright test coverage
```

## Versioning

The project uses semantic versioning-style tags:

- `0.x` for MVP and pre-launch development;
- `1.0.0` for the first stable public/dissertation-ready version;
- patch versions for small fixes;
- minor versions for notable user-facing additions.

Release notes are tracked in [CHANGELOG.md](./CHANGELOG.md). GitHub Releases
are intentionally not used yet; important states are fixed with Git tags.

## Status

This repository represents `v0.8.0` and is prepared for a controlled local
catalog workflow: ingest a source, review candidates, publish verified programs
and inspect the result in API mode. A public internet deployment, account
management, automated host scheduling and notification delivery remain explicit
future decisions.
