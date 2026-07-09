import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import type { SupportProgram, SupportSource } from '../types';
import { buildAnalytics } from './analytics';

const syntheticSources = [
  {
    id: 'synthetic-source',
    name: 'Synthetic Source',
    type: 'Фонд',
    description: 'Synthetic source for analytics tests.',
    topics: ['Технологии'],
    region: 'Россия',
    coverageLevel: 'federal',
    websiteUrl: 'https://example.org',
    logoLabel: 'SS',
    trustNote: 'Synthetic fixture.',
    verifiedAt: '2026-07-01',
    featured: false
  }
] as const satisfies readonly SupportSource[];

const baseSyntheticProgram: SupportProgram = {
  id: 'synthetic-program',
  sourceId: 'synthetic-source',
  title: 'Synthetic program',
  description: 'Synthetic program for analytics tests.',
  status: 'Открыта',
  supportType: 'Грант',
  topics: ['Технологии'],
  audience: ['Стартапы'],
  regions: ['Россия'],
  coverageLevel: 'federal',
  launchYear: 2026,
  activeFrom: '2026-07-01',
  activeTo: null,
  deadline: null,
  fundingAmountRub: null,
  fundingMinRub: null,
  fundingMaxRub: null,
  fundingLabel: 'нет финансирования',
  currency: 'RUB',
  requirements: ['Synthetic requirement'],
  sourceUrl: 'https://example.org/program',
  documentUrls: [],
  publishedAt: '2026-07-01',
  updatedAt: '2026-07-01',
  featured: false,
  dataQuality: {
    score: 100,
    level: 'high',
    missingFields: [],
    checkedAt: '2026-07-01'
  },
  history: []
};

function syntheticProgram(overrides: Partial<SupportProgram>): SupportProgram {
  return { ...baseSyntheticProgram, ...overrides };
}

describe('analytics', () => {
  it('computes metrics from seed data', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.totalPrograms).toBe(30);
    expect(analytics.totalSources).toBe(10);
    expect(analytics.activePrograms).toBe(22);
    expect(analytics.maxFundingRub).toBe(20000000);
    expect(analytics.fundedShare).toBeGreaterThanOrEqual(0.5);
    expect(analytics.nearestDeadline?.programId).toBe('impact-hub-eco-impact');
  });

  it('builds distributions and nearest deadlines', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.bySupportType.find((item) => item.label === 'Грант')?.count).toBe(10);
    expect(analytics.bySource.find((item) => item.label === 'Фонд Потанина')?.count).toBe(3);
    expect(analytics.nearestDeadlines.map((item) => item.programId).slice(0, 3)).toEqual([
      'impact-hub-eco-impact',
      'rsv-volunteer-region',
      'potanin-university-grant-2026'
    ]);
  });

  it('computes finance, region, coverage, and quality foundations from enriched seed data', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.totalFundingRub).toBe(54000000);
    expect(analytics.averageFundingRub).toBe(3600000);
    expect(analytics.medianFundingRub).toBe(1500000);
    expect(analytics.byRegion.find((item) => item.label === 'Россия')?.count).toBeGreaterThan(20);
    expect(analytics.byCoverageLevel.find((item) => item.id === 'federal')?.count).toBeGreaterThan(15);
    expect(analytics.dataQuality.averageScore).toBeGreaterThan(60);
    expect(analytics.dataQuality.incompletePrograms.length).toBeGreaterThan(0);
  });

  it('uses exact, max, and min funding values as comparable funding', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'exact-only',
        title: 'Exact only',
        fundingAmountRub: 1000
      }),
      syntheticProgram({
        id: 'max-only',
        title: 'Max only',
        fundingMaxRub: 5000
      }),
      syntheticProgram({
        id: 'min-only',
        title: 'Min only',
        fundingMinRub: 3000
      }),
      syntheticProgram({
        id: 'no-funding',
        title: 'No funding'
      })
    ]);

    expect(analytics.maxFundingRub).toBe(5000);
    expect(analytics.totalFundingRub).toBe(9000);
    expect(analytics.averageFundingRub).toBe(3000);
    expect(analytics.medianFundingRub).toBe(3000);
    expect(analytics.fundedShare).toBe(0.75);
  });
});
