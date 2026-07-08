# Stargate

Stargate is an MVP website for collecting and exploring support programs:
grants, accelerators, scholarships, funding sources, deadlines, and related
analytics. The current version is frontend-only and uses local seed data.

## Current Version

`v0.1.0` is the first fixed MVP snapshot:

- three main sections: home, catalog, and sources;
- seed database of support programs and organizations;
- search, filters, source cards, program details, and lightweight analytics;
- responsive React interface without a backend.

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

This repository currently represents an MVP milestone. The backend, persistent
accounts, production data pipeline, and advanced analytics are planned future
work.
