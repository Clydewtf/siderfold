# Stargate

Stargate is an MVP website for collecting and exploring support programs:
grants, accelerators, scholarships, funding sources, deadlines, and related
analytics. The current version is frontend-only and uses local seed data.

## Current Version

`v0.2.0` completes the app-shell and local-state milestone over the analytics
engine and expanded seed model:

- five keyboard-accessible sections: home, catalog, analytics, sources, and
  profile;
- versioned local browser state for theme, favorites, recent programs, regions,
  topics, card density, data-quality visibility, and reduced motion;
- shared program details with consistent favorites and recent-view behavior;
- local profile controls and clear demo states for backend-dependent features;
- a filterable analytics API for financial, regional, source, topic, temporal,
  data-quality, support-gap, and transparent demo forecast calculations;
- responsive desktop and mobile coverage without a backend.

The analytics and profile screens remain intentionally lightweight. Forecast
values are transparent demo calculations over seed history, not a real
machine-learning model. User preferences stay in the current browser and are
not synchronized with a server.

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

This repository currently represents the `v0.2.0` MVP app-shell and local-state
milestone. The backend, persistent accounts, production data pipeline, and a
full analytics dashboard are planned future work.
