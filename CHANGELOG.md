# Changelog

All notable project milestones are documented in this file.

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
