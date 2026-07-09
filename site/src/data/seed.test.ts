import { describe, expect, it } from 'vitest';
import { programs, sources } from './seed';

const expectUniqueIds = (ids: readonly string[]) => {
  expect(new Set(ids).size).toBe(ids.length);
};

const expectHttpsUrl = (value: string) => {
  const url = new URL(value);
  expect(url.protocol).toBe('https:');
};

const expectDateOnly = (value: string) => {
  expect(value).toMatch(/^\d{4}-\d{2}-\d{2}$/);

  const parsed = new Date(`${value}T00:00:00.000Z`);

  expect(Number.isNaN(parsed.getTime())).toBe(false);
  expect(parsed.toISOString().slice(0, 10)).toBe(value);
};

const coverageLevels = new Set(['federal', 'regional', 'municipal', 'private']);

const expectPositiveInteger = (value: number) => {
  expect(Number.isInteger(value)).toBe(true);
  expect(value).toBeGreaterThan(0);
};

const expectNullableDateOnly = (value: string | null) => {
  if (value !== null) expectDateOnly(value);
};

const assertReadonlySeedTypes = () => {
  // @ts-expect-error exported source collection is readonly
  sources.push(sources[0]);
  // @ts-expect-error nested source topics are readonly
  sources[0].topics.push('ИИ');
  // @ts-expect-error exported program collection is readonly
  programs.push(programs[0]);
  // @ts-expect-error nested program audiences are readonly
  programs[0].audience.push('Студенты');
  // @ts-expect-error nested program topics are readonly
  programs[0].topics.push('Наука');
  // @ts-expect-error nested program requirements are readonly
  programs[0].requirements.push('Новое требование');
  // @ts-expect-error nested program document URLs are readonly
  programs[0].documentUrls.push('https://example.org/docs/extra.pdf');
};

void assertReadonlySeedTypes;

describe('seed data', () => {
  it('contains enough sources and programs for the MVP', () => {
    expect(sources).toHaveLength(10);
    expect(programs).toHaveLength(30);
  });

  it('uses unique source and program IDs', () => {
    expectUniqueIds(sources.map((source) => source.id));
    expectUniqueIds(programs.map((program) => program.id));
  });

  it('links every program to an existing source', () => {
    const sourceIds = new Set<string>(sources.map((source) => source.id));
    expect(programs.every((program) => sourceIds.has(program.sourceId))).toBe(true);
  });

  it('covers varied statuses, funding, deadlines, and missing values', () => {
    expect(new Set(programs.map((program) => program.status)).size).toBeGreaterThanOrEqual(4);
    expect(programs.some((program) => program.deadline === null)).toBe(true);
    expect(programs.some((program) => program.fundingAmountRub === null)).toBe(true);
    expect(programs.some((program) => typeof program.fundingAmountRub === 'number')).toBe(true);
  });

  it('has external source and document links where provided', () => {
    expect(sources.every((source) => source.websiteUrl.startsWith('https://'))).toBe(true);
    expect(programs.some((program) => program.documentUrls.length > 0)).toBe(true);
  });

  it('uses valid HTTPS URLs for sources, programs, and documents', () => {
    sources.forEach((source) => {
      expectHttpsUrl(source.websiteUrl);
    });

    programs.forEach((program) => {
      expectHttpsUrl(program.sourceUrl);
      program.documentUrls.forEach(expectHttpsUrl);
    });
  });

  it('uses parseable YYYY-MM-DD dates for published dates and deadlines', () => {
    programs.forEach((program) => {
      expectDateOnly(program.publishedAt);

      if (program.deadline !== null) {
        expectDateOnly(program.deadline);
      }
    });
  });
});

describe('seed data foundation metadata', () => {
  it('adds required source metadata for backend-ready source records', () => {
    sources.forEach((source) => {
      expect(coverageLevels.has(source.coverageLevel)).toBe(true);
      expect(source.region.trim().length).toBeGreaterThan(0);
      expectDateOnly(source.verifiedAt);
    });

    expect(new Set(sources.map((source) => source.coverageLevel))).toEqual(
      new Set(['federal', 'regional', 'private'])
    );
  });

  it('adds required program timing, region, coverage, funding, currency, and quality metadata', () => {
    programs.forEach((program) => {
      expect(program.regions.length).toBeGreaterThan(0);
      program.regions.forEach((region) => expect(region.trim().length).toBeGreaterThan(0));
      expect(coverageLevels.has(program.coverageLevel)).toBe(true);
      expectPositiveInteger(program.launchYear);
      expect(program.launchYear).toBeGreaterThanOrEqual(2000);
      expect(program.launchYear).toBeLessThanOrEqual(2026);
      expectDateOnly(program.activeFrom);
      expectNullableDateOnly(program.activeTo);
      expectDateOnly(program.publishedAt);
      expectDateOnly(program.updatedAt);
      expect(program.currency).toBe('RUB');
      expect(program.fundingLabel.trim().length).toBeGreaterThan(0);
      expect(program.dataQuality.checkedAt).toBe(program.updatedAt);
      expect(program.dataQuality.score).toBeGreaterThanOrEqual(0);
      expect(program.dataQuality.score).toBeLessThanOrEqual(100);
    });
  });

  it('uses valid funding ranges and keeps exact amounts inside ranges', () => {
    programs.forEach((program) => {
      if (program.fundingMinRub !== null) expectPositiveInteger(program.fundingMinRub);
      if (program.fundingMaxRub !== null) expectPositiveInteger(program.fundingMaxRub);
      if (program.fundingMinRub !== null && program.fundingMaxRub !== null) {
        expect(program.fundingMinRub).toBeLessThanOrEqual(program.fundingMaxRub);
      }
      if (program.fundingAmountRub !== null && program.fundingMinRub !== null) {
        expect(program.fundingAmountRub).toBeGreaterThanOrEqual(program.fundingMinRub);
      }
      if (program.fundingAmountRub !== null && program.fundingMaxRub !== null) {
        expect(program.fundingAmountRub).toBeLessThanOrEqual(program.fundingMaxRub);
      }
      if (
        program.fundingAmountRub === null &&
        program.fundingMinRub === null &&
        program.fundingMaxRub === null
      ) {
        expect(program.dataQuality.missingFields).toContain('funding');
      }
    });
  });

  it('contains historical points that can power demo forecast calculations', () => {
    programs.forEach((program) => {
      expect(program.history).toHaveLength(3);
      expect(program.history.map((point) => point.year)).toEqual(
        [...program.history.map((point) => point.year)].sort()
      );
      expect(program.history.at(-1)?.year).toBe(2026);

      program.history.forEach((point) => {
        expect(point.year).toBeGreaterThanOrEqual(program.launchYear);
        expect(point.year).toBeLessThanOrEqual(2026);
        if (point.fundingAmountRub !== null) expectPositiveInteger(point.fundingAmountRub);
        if (point.applicationsCount !== null) expectPositiveInteger(point.applicationsCount);
        if (point.winnersCount !== null) expectPositiveInteger(point.winnersCount);
      });
    });
  });
});
