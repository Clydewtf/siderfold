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
    const sourceIds = new Set(sources.map((source) => source.id));
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
