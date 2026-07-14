# Navigation, favorites, and program drawer polish

**Date:** 2026-07-14  
**Status:** Approved

## Goal

Remove three interaction defects without changing the catalogue data model:

- each top-level section must retain its own reading position;
- favorite controls must be compact, clear, and consistent;
- the program drawer must remain usable with long titles and retain a translucent backdrop in both themes.

## Navigation position

The app will keep a scroll offset for each `TabId` in memory for the current browser session. On a tab change, it records the outgoing tab's `window.scrollY`, then restores the destination tab's recorded offset. A tab that has not yet been visited restores to `0`.

Offsets are not written to local storage. They are navigation context, not a cross-session preference, and stale offsets would be confusing after a reload or data change.

## Favorite controls

All existing program and source favorite toggles will use a shared icon-only button built around the `Star` icon.

- Unselected: outlined star in the normal foreground color.
- Selected: filled yellow star, with the same accessible pressed state and descriptive label as today.
- Catalog and source cards: star sits beside the card title/source metadata rather than creating a wide action row.
- Program drawer: star is in the fixed-size action area at the upper right.
- Profile cards: star is in the card header; the program card retains its bottom-aligned “Открыть” action. Favorite source cards do not gain an empty action row; their header star is the removal control.

The button has a minimum 44 by 44 px hit target, a visible keyboard focus ring, and no visible text label. Screen-reader labels continue to state whether clicking adds or removes the exact program or source.

## Program drawer

The drawer header is a two-column layout: a fluid, `min-width: 0` title column and a non-shrinking fixed-size actions column. This makes a multi-line title wrap independently of the close and favorite controls.

The close control is the farthest-right and topmost control. It is visually distinct, has a 44 by 44 px target, and remains available regardless of title length. The favorite star is immediately to its left.

The overlay remains a full-viewport element, but its color is defined with a dedicated semantic CSS class rather than the generic `bg-ink` utility. This prevents dark-theme overrides from replacing translucency with an opaque black background. The overlay will preserve a translucent dim and blur in light and dark themes.

Clicking the overlay's empty area closes the drawer. Clicks within the dialog do not propagate, and the existing Escape-key close, focus trap, opener restoration, and dialog semantics remain unchanged.

## Validation

Unit/component tests will cover:

- tab position capture/restoration including the zero offset for a never-visited section;
- selected/unselected star buttons and their accessible labels in program, source, drawer, and profile contexts;
- drawer action structure for a long title and overlay click-to-close behavior;
- the dark-theme overlay class remaining translucent rather than matching the generic `bg-ink` override.

The complete test suite, TypeScript build, and browser checks at desktop and mobile widths will be run. Manual browser validation will confirm the visual outcome in both themes.
