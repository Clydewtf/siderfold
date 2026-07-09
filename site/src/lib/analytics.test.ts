import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import type { SupportProgram, SupportSource } from '../types';
import {
  applyAnalyticsFilters,
  buildAnalytics,
  defaultAnalyticsFilters,
  getProgramFundingValue,
  median,
  normalizeAnalyticsFilters
} from './analytics';

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

describe('analytics filters and funding helpers', () => {
  it('keeps a complete default filter contract', () => {
    expect(defaultAnalyticsFilters).toEqual({
      region: 'Все регионы',
      year: 'Все годы',
      coverageLevel: 'Все уровни',
      sourceId: 'Все источники',
      supportType: 'Все типы',
      topic: 'Все тематики',
      audience: 'Все аудитории',
      status: 'Все статусы',
      funding: 'all',
      deadline: 'all'
    });
  });

  it('uses exact funding before max and min funding values', () => {
    expect(
      getProgramFundingValue({
        fundingAmountRub: 300,
        fundingMaxRub: 500,
        fundingMinRub: 100
      })
    ).toBe(300);

    expect(
      getProgramFundingValue({
        fundingAmountRub: null,
        fundingMaxRub: 500,
        fundingMinRub: 100
      })
    ).toBe(500);

    expect(
      getProgramFundingValue({
        fundingAmountRub: null,
        fundingMaxRub: null,
        fundingMinRub: 100
      })
    ).toBe(100);

    expect(
      getProgramFundingValue({
        fundingAmountRub: null,
        fundingMaxRub: null,
        fundingMinRub: null
      })
    ).toBeNull();
  });

  it('calculates median values for odd, even, and empty arrays', () => {
    expect(median([5, 1, 3])).toBe(3);
    expect(median([10, 2, 4, 8])).toBe(6);
    expect(median([])).toBeNull();
  });

  it('keeps summary median funding numeric when no programs have funding', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'no-funding-summary',
        title: 'No funding summary'
      })
    ]);

    expect(analytics.medianFundingRub).toBe(0);
  });

  it('ignores explicitly undefined filter values while normalizing filters', () => {
    const filters = normalizeAnalyticsFilters({
      sourceId: undefined,
      funding: 'withFunding'
    });

    expect(filters).toEqual({
      ...defaultAnalyticsFilters,
      funding: 'withFunding'
    });
  });

  it.each([
    {
      label: 'region',
      filters: { region: 'Татарстан' },
      input: [
        syntheticProgram({ id: 'region-match', regions: ['Татарстан'] }),
        syntheticProgram({ id: 'region-miss', regions: ['Россия'] })
      ],
      expected: ['region-match']
    },
    {
      label: 'year via launchYear',
      filters: { year: 2025 },
      input: [
        syntheticProgram({ id: 'launch-year-match', launchYear: 2025 }),
        syntheticProgram({ id: 'launch-year-miss', launchYear: 2026 })
      ],
      expected: ['launch-year-match']
    },
    {
      label: 'year via history',
      filters: { year: 2024 },
      input: [
        syntheticProgram({
          id: 'history-year-match',
          launchYear: 2026,
          history: [{ year: 2024, fundingAmountRub: 1000, applicationsCount: null, winnersCount: null }]
        }),
        syntheticProgram({ id: 'history-year-miss', launchYear: 2026, history: [] })
      ],
      expected: ['history-year-match']
    },
    {
      label: 'coverageLevel',
      filters: { coverageLevel: 'regional' },
      input: [
        syntheticProgram({ id: 'coverage-match', coverageLevel: 'regional' }),
        syntheticProgram({ id: 'coverage-miss', coverageLevel: 'federal' })
      ],
      expected: ['coverage-match']
    },
    {
      label: 'sourceId',
      filters: { sourceId: 'matching-source' },
      input: [
        syntheticProgram({ id: 'source-match', sourceId: 'matching-source' }),
        syntheticProgram({ id: 'source-miss', sourceId: 'other-source' })
      ],
      expected: ['source-match']
    },
    {
      label: 'supportType',
      filters: { supportType: 'Обучение' },
      input: [
        syntheticProgram({ id: 'support-type-match', supportType: 'Обучение' }),
        syntheticProgram({ id: 'support-type-miss', supportType: 'Грант' })
      ],
      expected: ['support-type-match']
    },
    {
      label: 'topic',
      filters: { topic: 'ИИ' },
      input: [
        syntheticProgram({ id: 'topic-match', topics: ['ИИ'] }),
        syntheticProgram({ id: 'topic-miss', topics: ['Экология'] })
      ],
      expected: ['topic-match']
    },
    {
      label: 'audience',
      filters: { audience: 'НКО' },
      input: [
        syntheticProgram({ id: 'audience-match', audience: ['НКО'] }),
        syntheticProgram({ id: 'audience-miss', audience: ['Стартапы'] })
      ],
      expected: ['audience-match']
    },
    {
      label: 'status',
      filters: { status: 'Ожидается' },
      input: [
        syntheticProgram({ id: 'status-match', status: 'Ожидается' }),
        syntheticProgram({ id: 'status-miss', status: 'Открыта' })
      ],
      expected: ['status-match']
    },
    {
      label: 'funding all',
      filters: { funding: 'all' },
      input: [
        syntheticProgram({ id: 'funding-all-funded', fundingAmountRub: 1000 }),
        syntheticProgram({ id: 'funding-all-empty' })
      ],
      expected: ['funding-all-funded', 'funding-all-empty']
    },
    {
      label: 'funding withFunding',
      filters: { funding: 'withFunding' },
      input: [
        syntheticProgram({ id: 'with-funding-match', fundingMaxRub: 1000 }),
        syntheticProgram({ id: 'with-funding-miss' })
      ],
      expected: ['with-funding-match']
    },
    {
      label: 'funding withoutFunding',
      filters: { funding: 'withoutFunding' },
      input: [
        syntheticProgram({ id: 'without-funding-miss', fundingMinRub: 1000 }),
        syntheticProgram({ id: 'without-funding-match' })
      ],
      expected: ['without-funding-match']
    },
    {
      label: 'deadline withDeadline',
      filters: { deadline: 'withDeadline' },
      input: [
        syntheticProgram({ id: 'with-deadline-match', deadline: '2026-07-15' }),
        syntheticProgram({ id: 'with-deadline-miss', deadline: null })
      ],
      expected: ['with-deadline-match']
    },
    {
      label: 'deadline withoutDeadline',
      filters: { deadline: 'withoutDeadline' },
      input: [
        syntheticProgram({ id: 'without-deadline-miss', deadline: '2026-07-15' }),
        syntheticProgram({ id: 'without-deadline-match', deadline: null })
      ],
      expected: ['without-deadline-match']
    },
    {
      label: 'deadline next30',
      filters: { deadline: 'next30' },
      input: [
        syntheticProgram({ id: 'next30-match', deadline: '2026-07-31' }),
        syntheticProgram({ id: 'next30-miss', deadline: '2026-08-01' })
      ],
      expected: ['next30-match']
    },
    {
      label: 'deadline next90',
      filters: { deadline: 'next90' },
      input: [
        syntheticProgram({ id: 'next90-match', deadline: '2026-09-29' }),
        syntheticProgram({ id: 'next90-miss', deadline: '2026-09-30' })
      ],
      expected: ['next90-match']
    }
  ] as const)('filters by $label independently', ({ input, filters, expected }) => {
    expect(applyAnalyticsFilters(input, filters).map((program) => program.id)).toEqual(expected);
  });

  it('filters analytics input by region, year, level, source, topic, type, audience, status, funding, and deadline', () => {
    const filtered = applyAnalyticsFilters(programs, {
      region: 'Россия',
      year: 2026,
      coverageLevel: 'federal',
      sourceId: 'fasie',
      supportType: 'Грант',
      topic: 'ИИ',
      audience: 'Стартапы',
      status: 'Открыта',
      funding: 'withFunding',
      deadline: 'next90'
    });

    expect(filtered.map((program) => program.id)).toEqual(['fasie-start-ai']);
  });

  it('applies partial filters through buildAnalytics without mutating the default filters', () => {
    const analytics = buildAnalytics(sources, programs, { sourceId: 'fasie', funding: 'withFunding' });

    expect(analytics.filters).toEqual({
      ...defaultAnalyticsFilters,
      sourceId: 'fasie',
      funding: 'withFunding'
    });
    expect(defaultAnalyticsFilters.sourceId).toBe('Все источники');
    expect(analytics.totalPrograms).toBe(3);
    expect(analytics.filteredPrograms).toBe(3);
  });
});
