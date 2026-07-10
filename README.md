# Stargate

Stargate is an MVP website for collecting and exploring support programs:
grants, accelerators, scholarships, funding sources, deadlines, and related
analytics. The current version is frontend-only and uses local seed data.

## Current Version

`v0.1.2` completes the analytics engine milestone over the expanded seed model:

- three main sections: home, catalog, and sources;
- expanded support-program and source data with quality and history metadata;
- a filterable analytics API for financial, regional, source, topic, temporal,
  data-quality, support-gap, and demo forecast calculations;
- unit coverage for incomplete data, empty inputs, rankings, deadline dynamics,
  and transparent forecast behavior;
- search, filters, source cards, and program details;
- responsive React interface without a backend.

This release adds the analytics engine without a new analytics UI screen.
Forecast values are transparent demo calculations over seed history, not a real
machine-learning model.

The project is intended to grow into a fuller platform with user profiles,
backend-backed data, saved items, richer analytics, and expanded navigation.

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

This repository currently represents the `v0.1.2` MVP analytics-engine
milestone. The backend, persistent accounts, production data pipeline, and a
dedicated analytics UI are planned future work.
