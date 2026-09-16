# Changelog

All notable project milestones are documented in this file.

## v0.8.1 - 2026-09-16

Operator Workflow And Catalog Data Improvements.

### Added

- A protected local operator workspace with review queues, source-record details, full data editing, a public-card preview and immutable revision history.
- Explicit handling of program documents, result materials, winner links and official Telegram/VK channels in the public program representation.
- Database-level canonicalization for theme and geography names, including a data migration that merges existing case/whitespace duplicates.

### Changed

- Potanin extraction now classifies documents and winner materials more reliably, preserves programme schedules and avoids promoting inline application links into the document list.
- Public cards derive a human-readable application status from dates at render time, so an open, upcoming, closed or completed programme does not require a republish solely because the date changed.
- Program titles are normalized for display, while source attribution and operator provenance remain intact.

### Fixed

- Manually corrected themes and geographies no longer create duplicate public filter values.
- Winner links for multi-cycle programmes are kept with results rather than being shown as generic resources.

## v0.8.0 - 2026-09-02

Public Catalog And Controlled Moderation.

### Added

- Published-only public API with stable pagination, filters, sorting, safe errors, OpenAPI contracts and source attribution.
- Russian title search with word-form matching, bounded trigram typo tolerance and relevance ordering.
- Explicit frontend API mode for catalog, filters and program cards, with dedicated loading, empty and safe error states; seed data remains an opt-in development/demo mode.
- Reproducible analytics snapshots for freshness, completeness, conflicts, source coverage and review status, while detailed technical metrics stay internal.
- Protected operator endpoints for canonical and discovery review queues, data-quality issues, ingestion runs, idempotent review decisions, program archival and later republishing.

### Notes

- Only reviewed `published` programs reach the public API and frontend. Raw captures, staging records, quality details, review decisions and internal operator data remain private.
- The local workflow is intentionally controlled: source runs create candidates, operators review them, and publication is explicit. There is no automatic publication or uncontrolled background collection.
- The static internal token is appropriate for a local or closed operator environment. A public internet deployment still needs HTTPS, secret rotation and stronger access control.

## v0.7.0 - 2026-09-01

Sources, Review And Local Operations.

### Added

- Allowlisted source registry and common adapter contract with deterministic fixture dry-runs, limits, source ownership and configured access methods.
- Maintained Potanin adapter with normalized program fields, captured auxiliary resources, quality reporting and provenance-safe staging.
- Public Telegram discovery for the configured allowlist channel: cursor/idempotency handling, normalized external URLs, and a separate manual-review queue for candidates without a reliable primary source.
- Deterministic URL/field deduplication, review cases and immutable decision/action history for accept, reject, merge and clarification flows.
- Local one-shot scheduler/runner with PostgreSQL advisory locks, bounded retry/backoff, rate limits, execution journal, safe stderr failure notifications, recovery handling and operational metrics.

### Notes

- Sources remain manually activated until their owner, permitted access and frequency are explicitly approved; the repository does not install a background scheduler or send external notifications.
- Ingestion and discovery never publish a `Program` automatically. Raw captures, staging records, quality issues and review data remain internal and are excluded from the public API.
- The frontend remains on controlled seed data; connecting it to the backend catalog is planned for v0.8.0.

## v0.6.0 - 2026-08-30

Backend Foundation, Provenance And Read API.

### Added

- Python 3.11+ FastAPI backend with environment-based configuration, health/readiness checks, PostgreSQL Compose setup, SQLAlchemy, and Alembic migrations.
- Canonical normalized data model for programs, sources, deadlines, geography, themes, publication status, and exact, ranged, or unknown funding values.
- Ingestion provenance model with runs, immutable raw captures, staging records, data-quality issues, review decisions, and guarded ingestion states.
- Versioned JSON/CSV import bridge with validation, idempotent re-imports, raw-to-staging-to-review flow, and a local Potanin dry-run path.
- Versioned read-only API for published programs, sources, filters, and program details with pagination, sorting, stable errors, OpenAPI schemas, and contract tests.

### Notes

- The frontend remains on seed data and is not connected to the backend yet.
- Authentication, moderation endpoints, queues, cloud infrastructure, and automatic publication are not included in this milestone.
- Large raw files remain outside PostgreSQL; the database stores their metadata, hash, and external reference.

## v0.5.1 - 2026-08-29

MVP End-To-End Stability.

### Fixed

- Compact-density program cards now assert the intended card container and preserve the expected spacing and density.
- The mobile source flow now follows the actual interface behavior when opening a source.

### Notes

- This is an E2E-stability patch for the frontend MVP; no new backend functionality is included.

## v0.5.0 - 2026-07-13

Profile, Polish And End-To-End QA.

### Added

- Complete local profile workspace with favorite programs, favorite sources, recent programs, preferred regions and topics, theme, density, data-quality visibility, and reduced-motion settings.
- Honest demo states for sign-in, registration, user data, notifications, documents, applications, profile synchronization, and report export.
- Mobile, tablet, and desktop browser coverage for the main product journey, keyboard access, persistence, and horizontal-overflow safety.

### Changed

- Home, catalog, analytics, sources, profile, and the app shell now share a more cohesive nearly final visual hierarchy and responsive system.
- Profile collections are actionable and reuse the shared program drawer and app state instead of duplicating product logic.
- Project version is now `0.5.0` for the nearly final frontend-only milestone.

### Notes

- Account, backend, notifications, documents, applications, synchronization, and real exports are not connected; unavailable actions are explicitly marked as demo states.
- Favorites, recents, preferences, and display settings remain local to the current browser and device.
- Analytics and forecasts continue to describe the current seed database, not the complete support market.

## v0.4.0 - 2026-07-13

Analytics UI.

### Added

- Dedicated analytics section with presentation overview and filterable BI monitoring.
- Financial, regional, source, topic, temporal, data-quality and support-gap views over the shared analytics engine.
- Transparent demo forecast over historical seed data and backend-only report/CSV export actions.
- Component and end-to-end coverage for analytics filters, empty states, accessibility and responsive behavior.

### Changed

- Analytics now exposes deadline seasonality and peak activity windows as a minimal pure-engine aggregate.
- Project version is now `0.4.0` for the new user-facing analytics module.

### Notes

- All conclusions and forecasts are calculated from the current seed database and do not describe the complete support market.
- Report and CSV export remain unavailable until backend integration.

## v0.3.0 - 2026-07-12

Catalog And Sources Upgrade.

### Added

- Extended catalog filters for region, program level, launch year, active period, funding availability and range, deadline, status, topic, audience, support type, and source.
- Relevance-aware search and sorting across program, source, requirement, region, topic, and audience data.
- Mature program cards and detail drawer with local favorites and recently viewed workflows.
- Source filters and analytics-backed source cards with related program navigation.

### Changed

- Catalog and source screens now use the expanded data model and shared analytics calculations.
- Empty and incomplete-data states distinguish an empty database from filters with no matches.

### Notes

- Favorites and recent views remain local to the current browser and device.
- Source metrics are calculated from the current seed database; backend synchronization is not connected.

## v0.2.0 - 2026-07-10

App Shell, Navigation And Local State.

### Added

- Five-section navigation for Home, Catalog, Analytics, Sources, and Profile with keyboard-accessible tab behavior.
- Versioned local user state for theme, program and source favorites, recent programs, preferred regions and topics, and display settings.
- Local profile controls and honest demo states for account features that require backend services.

### Changed

- Program details are owned by the shared app state so recent views and favorites behave consistently across entry points.
- Theme colors use light and dark CSS tokens with system-theme support.

### Notes

- User state remains local to the current browser and device.
- Authentication, server sync, notifications, documents, applications, and report export are not connected.

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

Data foundation for the Siderfold product-platform upgrade.

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

- Frontend-only Siderfold website built with React, TypeScript, Vite, and Tailwind CSS.
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
