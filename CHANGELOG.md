# Changelog

All notable project milestones are documented in this file.

## v0.1.2 - 2026-07-09

Analytics Engine.

### Added

- Pure analytics engine for financial, regional, source, topic, temporal, data-quality, support-gap, and demo forecast calculations.
- Filterable analytics API over the expanded seed model.
- Unit coverage for incomplete data, empty inputs, distribution rankings, deadline dynamics, and transparent forecast behavior.

### Notes

- No new UI screen is included in this version.
- Forecast values are demo calculations over seed history, not a real ML model.

## v0.1.1 - 2026-07-09

Data foundation for the Stargate product-platform upgrade.

### Added

- Expanded support program data model with coverage level, regions, active period, funding ranges, currency, update metadata, data quality, and historical points.
- Expanded source data model with coverage level and verification dates.
- Seed validation for required metadata, links, dates, funding ranges, launch years, regions, references, data quality, and history.
- Pure data quality calculation and analytics foundation metrics for finance, regions, coverage levels, and incomplete records.

### Notes

- No backend, authentication, profile, new catalog UI, or analytics UI is included in this version.
- Existing UI changes are limited to TypeScript compatibility with the richer data model.

## v0.1.0 - 2026-07-08

Initial MVP snapshot.

### Added

- Frontend-only Stargate website built with React, TypeScript, Vite, and Tailwind CSS.
- Home, catalog, and sources sections.
- Seed database of support programs and funding/support sources.
- Catalog search, filtering, program cards, and program detail drawer.
- Source browsing with source detail state.
- Lightweight analytics widgets based on seed data.
- Responsive layout and Playwright coverage for desktop and mobile flows.
- Unit and component test coverage for catalog, analytics, formatting, navigation, and tabs.

### Notes

- No backend is included in this version.
- GitHub Releases are not used for this milestone; the version is tracked with package metadata, changelog entry, and a Git tag.
