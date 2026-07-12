# Catalog final fix report

Date: 2026-07-12
Branch: `stargate-catalog-sources-upgrade`
Base accepted HEAD before fix: `8f4d7e2`

## Scope handled

- Funding-bound precedence in [site/src/lib/catalog.ts](/Users/clyde/projects/stargate/site/src/lib/catalog.ts) with regression coverage in [site/src/lib/catalog.test.ts](/Users/clyde/projects/stargate/site/src/lib/catalog.test.ts)
- Whole-token relevance scoring in [site/src/lib/catalog.ts](/Users/clyde/projects/stargate/site/src/lib/catalog.ts) with regression coverage in [site/src/lib/catalog.test.ts](/Users/clyde/projects/stargate/site/src/lib/catalog.test.ts)
- Selected source button `aria-pressed` in [site/src/components/SourceCard.tsx](/Users/clyde/projects/stargate/site/src/components/SourceCard.tsx) with coverage in [site/src/components/SourcesTab.test.tsx](/Users/clyde/projects/stargate/site/src/components/SourcesTab.test.tsx)

## Changed files

- [site/src/lib/catalog.ts](/Users/clyde/projects/stargate/site/src/lib/catalog.ts)
- [site/src/lib/catalog.test.ts](/Users/clyde/projects/stargate/site/src/lib/catalog.test.ts)
- [site/src/components/SourceCard.tsx](/Users/clyde/projects/stargate/site/src/components/SourceCard.tsx)
- [site/src/components/SourcesTab.test.tsx](/Users/clyde/projects/stargate/site/src/components/SourcesTab.test.tsx)

## TDD record

### 1) Add failing regression tests

Added:

- `prefers explicit funding bounds over exact funding fallback when both are present`
- `ranks a whole-token relevance hit ahead of an incidental substring-only title hit`
- `exposes selected-source buttons as pressed and unselected ones as not pressed`

### 2) Red run

Command:

```bash
cd /Users/clyde/projects/stargate/site
npx vitest run src/lib/catalog.test.ts src/components/SourcesTab.test.tsx
```

Output:

```text
RUN  v2.1.9 /Users/clyde/projects/stargate/site

❯ src/lib/catalog.test.ts (18 tests | 2 failed)
  × catalog selectors > prefers explicit funding bounds over exact funding fallback when both are present
    → expected [] to deeply equal [ 'range-wins-over-exact' ]
  × catalog selectors > ranks a whole-token relevance hit ahead of an incidental substring-only title hit
    → expected [ 'substring-only-newer', …(1) ] to deeply equal [ 'whole-token-older', …(1) ]

❯ src/components/SourcesTab.test.tsx (17 tests | 1 failed)
  × SourcesTab > exposes selected-source buttons as pressed and unselected ones as not pressed
    → Expected the element to have attribute:
      aria-pressed="true"
      Received: null

Test Files  2 failed (2)
Tests  3 failed | 32 passed (35)
```

### 3) Minimal implementation

- Changed funding-bound resolution to prefer explicit `fundingMinRub` / `fundingMaxRub` whenever either exists, with `fundingAmountRub` used only when both bounds are absent.
- Replaced substring-based relevance weighting with token-set matching for section-level and per-token boosts while preserving the separate exact-title bonus and existing tie-break order.
- Added `aria-pressed={selected}` to the source-selection button only; favorite button behavior and callback wiring were left unchanged.

### 4) Green run

Command:

```bash
cd /Users/clyde/projects/stargate/site
npx vitest run src/lib/catalog.test.ts src/components/SourcesTab.test.tsx
```

Output:

```text
RUN  v2.1.9 /Users/clyde/projects/stargate/site

✓ src/lib/catalog.test.ts (18 tests)
✓ src/components/SourcesTab.test.tsx (17 tests)

Test Files  2 passed (2)
Tests  35 passed (35)
Duration  1.17s
```

## Verification

Command:

```bash
cd /Users/clyde/projects/stargate/site
npm run lint
```

Output:

```text
> support-programs-aggregator-site@0.3.0 lint
> tsc -b --pretty false
```

Exit code: `0`

## Self-review

- Scope stayed limited to the four files named in the findings.
- Funding semantics now follow the human resolution: explicit bounds win over exact amount when present.
- Whole-token relevance still preserves exact-title preference and deterministic tie behavior; the pre-existing exact-title and tie-break tests remained green in the covering suite.
- Selected-source pressed state is now exposed on the stateful source-selection button, and the pre-existing favorite-button pressed/callback coverage remained green.

## Concerns

- None on the implemented scope.
