# Support Programs Aggregator Site

A Vite + React MVP for exploring support programs, funding sources, deadlines,
and lightweight analytics in one responsive interface.

## Setup

```bash
cd site
npm install
```

## Development

```bash
npm run dev
```

The dev server runs on `127.0.0.1` by default.

## Verification

```bash
npm test
npm run build
```

End-to-end tests are available with:

```bash
npm run test:e2e
```

## Project Layout

- `site/src/components` - app screens and shared UI components.
- `site/src/data` - seed catalog data for programs and sources.
- `site/src/lib` - catalog, analytics, and formatting helpers.
- `site/e2e` - Playwright coverage for the main user flows.
