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

describe('analytics compatibility and empty states', () => {
  it('preserves lightweight widget fields', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.totalPrograms).toBe(30);
    expect(analytics.totalSources).toBe(10);
    expect(analytics.activePrograms).toBe(22);
    expect(analytics.maxFundingRub).toBe(20000000);
    expect(analytics.fundedShare).toBeCloseTo(15 / 30, 4);
    expect(analytics.bySource.find((item) => item.label === 'Фонд Потанина')?.count).toBe(3);
    expect(analytics.bySupportType.find((item) => item.label === 'Грант')?.count).toBe(10);
    expect(analytics.bySource.map((item) => item.id)).toEqual(
      analytics.sources.byProgramCount.map((item) => item.sourceId)
    );
  });

  it('returns stable empty analytics structures', () => {
    const analytics = buildAnalytics(sources, []);

    expect(analytics.totalPrograms).toBe(0);
    expect(analytics.activePrograms).toBe(0);
    expect(analytics.maxFundingRub).toBeNull();
    expect(analytics.nearestDeadline).toBeNull();
    expect(analytics.nearestDeadlines).toEqual([]);
    expect(analytics.finance.bySupportType).toEqual([]);
    expect(analytics.regional.regions).toEqual([]);
    expect(analytics.topics.topics).toEqual([]);
  });
});

describe('temporal analytics', () => {
  it('keeps nearest deadline compatibility while exposing richer deadline items', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.nearestDeadline?.programId).toBe('impact-hub-eco-impact');
    expect(analytics.temporal.nearestDeadline).toMatchObject({
      programId: 'impact-hub-eco-impact',
      deadline: '2026-07-12',
      daysUntilDeadline: 11
    });
    expect(analytics.temporal.nearestDeadlines).toHaveLength(5);
  });

  it('lists programs without deadlines', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.temporal.withoutDeadline.map((item) => item.programId)).toContain('fasie-umnik');
    expect(analytics.temporal.withoutDeadline.length).toBeGreaterThan(5);
  });

  it('computes launch and funding dynamics by year', () => {
    const analytics = buildAnalytics(sources, programs);
    const year2026 = analytics.temporal.byYear.find((item) => item.year === 2026);

    expect(analytics.temporal.byYear.map((item) => item.year)).toEqual([2024, 2025, 2026]);
    expect(year2026?.launchedPrograms).toBe(0);
    expect(year2026?.totalFundingRub).toBe(54000000);
    expect(year2026?.activePrograms).toBe(30);
  });

  it('builds temporal analytics from filtered programs only', () => {
    const analytics = buildAnalytics(
      syntheticSources,
      [
        syntheticProgram({
          id: 'included-temporal',
          title: 'Included temporal',
          status: 'Открыта',
          deadline: '2026-07-02',
          launchYear: 2026,
          history: [{ year: 2026, fundingAmountRub: 100, applicationsCount: null, winnersCount: null }]
        }),
        syntheticProgram({
          id: 'excluded-temporal',
          title: 'Excluded temporal',
          status: 'Закрыта',
          deadline: '2026-07-01',
          launchYear: 2026,
          history: [{ year: 2026, fundingAmountRub: 900, applicationsCount: null, winnersCount: null }]
        })
      ],
      { status: 'Открыта' }
    );

    expect(analytics.temporal.nearestDeadlines.map((item) => item.programId)).toEqual(['included-temporal']);
    expect(analytics.temporal.byYear).toEqual([
      { year: 2026, launchedPrograms: 1, activePrograms: 1, totalFundingRub: 100 }
    ]);
  });

  it('aggregates deadlines by calendar month and identifies deterministic peak windows', () => {
    const seasonalityPrograms = [
      syntheticProgram({ id: 'january-a', deadline: '2026-01-05' }),
      syntheticProgram({ id: 'january-b', deadline: '2026-01-25' }),
      syntheticProgram({ id: 'march-a', deadline: '2026-03-01' }),
      syntheticProgram({ id: 'march-b', deadline: '2026-03-15' }),
      syntheticProgram({ id: 'march-c', deadline: '2026-03-31' }),
      syntheticProgram({ id: 'april-a', deadline: '2026-04-10' }),
      syntheticProgram({ id: 'april-b', deadline: '2026-04-20' }),
      syntheticProgram({ id: 'december', deadline: '2026-12-24' }),
      syntheticProgram({ id: 'without-deadline', deadline: null })
    ];
    const result = buildAnalytics(syntheticSources, seasonalityPrograms);

    expect(result.temporal.byDeadlineMonth).toHaveLength(12);
    expect(result.temporal.byDeadlineMonth.map(({ month, deadlineCount }) => ({ month, deadlineCount }))).toEqual([
      { month: 1, deadlineCount: 2 },
      { month: 2, deadlineCount: 0 },
      { month: 3, deadlineCount: 3 },
      { month: 4, deadlineCount: 2 },
      { month: 5, deadlineCount: 0 },
      { month: 6, deadlineCount: 0 },
      { month: 7, deadlineCount: 0 },
      { month: 8, deadlineCount: 0 },
      { month: 9, deadlineCount: 0 },
      { month: 10, deadlineCount: 0 },
      { month: 11, deadlineCount: 0 },
      { month: 12, deadlineCount: 1 }
    ]);
    expect(result.temporal.peakDeadlineMonths).toEqual([
      { month: 3, label: 'март', deadlineCount: 3 },
      { month: 1, label: 'январь', deadlineCount: 2 },
      { month: 4, label: 'апрель', deadlineCount: 2 }
    ]);
  });

  it('rebuilds deadline seasonality after filtering and returns twelve zero months for no matches', () => {
    const filtered = buildAnalytics(sources, programs, { sourceId: 'impact-hub' });
    const empty = buildAnalytics(sources, programs, { sourceId: 'missing-source' });

    expect(filtered.temporal.byDeadlineMonth.reduce((sum, item) => sum + item.deadlineCount, 0))
      .toBe(applyAnalyticsFilters(programs, { sourceId: 'impact-hub' }).filter((program) => program.deadline).length);
    expect(empty.temporal.byDeadlineMonth.every((item) => item.deadlineCount === 0)).toBe(true);
    expect(empty.temporal.peakDeadlineMonths).toEqual([]);
  });

  it('returns empty temporal analytics for empty input', () => {
    const analytics = buildAnalytics(syntheticSources, []);

    expect(analytics.temporal).toEqual({
      nearestDeadline: null,
      nearestDeadlines: [],
      withoutDeadline: [],
      byYear: [],
      byDeadlineMonth: Array.from({ length: 12 }, (_, index) => ({
        month: index + 1,
        label: expect.any(String),
        deadlineCount: 0
      })),
      peakDeadlineMonths: []
    });
  });

  it('includes today, excludes past deadlines, and uses program IDs as final tie-breakers', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({ id: 'same-title-b', title: 'Same title', deadline: '2026-07-01' }),
      syntheticProgram({ id: 'same-title-a', title: 'Same title', deadline: '2026-07-01' }),
      syntheticProgram({ id: 'past', title: 'Past', deadline: '2026-06-30' }),
      syntheticProgram({ id: 'without-b', title: 'Without', deadline: null }),
      syntheticProgram({ id: 'without-a', title: 'Without', deadline: null })
    ]);

    expect(analytics.temporal.nearestDeadlines.map(({ programId, daysUntilDeadline }) => ({
      programId,
      daysUntilDeadline
    }))).toEqual([
      { programId: 'same-title-a', daysUntilDeadline: 0 },
      { programId: 'same-title-b', daysUntilDeadline: 0 }
    ]);
    expect(analytics.temporal.withoutDeadline.map((item) => item.programId)).toEqual(['without-a', 'without-b']);
  });
});

describe('demo forecast analytics', () => {
  it('forecasts next year funding and program count from seed history', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.forecast.nextYear).toBe(2027);
    expect(analytics.forecast.expectedFundingRub).toBeGreaterThan(54000000);
    expect(analytics.forecast.expectedProgramCount).toBeGreaterThanOrEqual(30);
    expect(analytics.forecast.expectedProgramCountChange).not.toBeNull();
    expect(analytics.forecast.confidenceScore).toBeGreaterThan(0);
  });

  it('returns growing topics with confidence and a transparent method explanation', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.forecast.growingTopics.length).toBeGreaterThan(0);
    expect(analytics.forecast.growingTopics[0]).toMatchObject({
      topic: expect.any(String),
      growthRate: expect.any(Number),
      confidence: expect.stringMatching(/high|medium|low/)
    });
    expect(analytics.forecast.method).toContain('Демо-прогноз');
    expect(analytics.forecast.method).toContain('seed');
    expect(analytics.forecast.method).toContain('не настоящая ML');
  });

  it('handles empty forecast input without fake certainty', () => {
    const analytics = buildAnalytics(sources, []);

    expect(analytics.forecast).toMatchObject({
      expectedFundingRub: null,
      expectedProgramCount: null,
      expectedProgramCountChange: null,
      growingTopics: [],
      confidence: 'low',
      confidenceScore: 0
    });
  });
});

describe('financial analytics', () => {
  it('computes total, average, median, max, and missing funding counts', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.finance.totalFundingRub).toBe(54000000);
    expect(analytics.finance.averageFundingRub).toBe(3600000);
    expect(analytics.finance.medianFundingRub).toBe(1500000);
    expect(analytics.finance.maxFundingRub).toBe(20000000);
    expect(analytics.finance.fundedPrograms).toBe(15);
    expect(analytics.finance.unknownFundingPrograms).toBe(15);
  });

  it('builds funding distributions by support type, source, region, and coverage level', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.finance.bySupportType.find((item) => item.id === 'Грант')).toMatchObject({
      label: 'Грант',
      count: 10,
      totalFundingRub: 49100000
    });

    expect(analytics.finance.bySource.find((item) => item.id === 'fasie')).toMatchObject({
      label: 'Фонд содействия инновациям',
      count: 3,
      totalFundingRub: 24500000
    });

    expect(analytics.finance.byRegion.find((item) => item.id === 'Россия')?.totalFundingRub).toBeGreaterThan(50000000);
    expect(analytics.finance.byCoverageLevel.find((item) => item.id === 'federal')).toMatchObject({
      label: 'federal',
      totalFundingRub: 44200000
    });
  });

  it('returns null averages for empty funded groups', () => {
    const analytics = buildAnalytics(sources, programs, { funding: 'withoutFunding' });

    expect(analytics.finance.totalFundingRub).toBe(0);
    expect(analytics.finance.averageFundingRub).toBeNull();
    expect(analytics.finance.medianFundingRub).toBeNull();
    expect(analytics.finance.maxFundingRub).toBeNull();
  });

  it('preserves fractional average funding values', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'one-ruble',
        title: 'One ruble',
        fundingAmountRub: 1
      }),
      syntheticProgram({
        id: 'two-rubles',
        title: 'Two rubles',
        fundingAmountRub: 2
      })
    ]);

    expect(analytics.finance.averageFundingRub).toBe(1.5);
    expect(analytics.finance.bySupportType.find((item) => item.id === 'Грант')?.averageFundingRub).toBe(1.5);
    expect(analytics.averageFundingRub).toBe(1.5);
  });

  it('uses unique known funding as the regional share denominator', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'multi-region-funded',
        title: 'Multi-region funded',
        fundingAmountRub: 100,
        regions: ['Россия', 'Татарстан']
      }),
      syntheticProgram({
        id: 'single-region-funded',
        title: 'Single-region funded',
        fundingAmountRub: 100,
        regions: ['Россия']
      })
    ]);

    expect(analytics.finance.totalFundingRub).toBe(200);
    expect(analytics.finance.byRegion.find((item) => item.id === 'Россия')).toMatchObject({
      totalFundingRub: 200,
      shareOfKnownFunding: 1
    });
    expect(analytics.finance.byRegion.find((item) => item.id === 'Татарстан')).toMatchObject({
      totalFundingRub: 100,
      shareOfKnownFunding: 0.5
    });
  });

  it('sorts money distributions by total funding, count, and label', () => {
    const sortSources = [
      { ...syntheticSources[0], id: 'high', name: 'High total' },
      { ...syntheticSources[0], id: 'count-wins', name: 'Count wins' },
      { ...syntheticSources[0], id: 'single-loses', name: 'Single loses' },
      { ...syntheticSources[0], id: 'alpha', name: 'Alpha' },
      { ...syntheticSources[0], id: 'bravo', name: 'Bravo' }
    ] as const satisfies readonly SupportSource[];
    const analytics = buildAnalytics(sortSources, [
      syntheticProgram({
        id: 'high-total',
        title: 'High total',
        sourceId: 'high',
        fundingAmountRub: 50
      }),
      syntheticProgram({
        id: 'count-wins-1',
        title: 'Count wins 1',
        sourceId: 'count-wins',
        fundingAmountRub: 10
      }),
      syntheticProgram({
        id: 'count-wins-2',
        title: 'Count wins 2',
        sourceId: 'count-wins',
        fundingAmountRub: 10
      }),
      syntheticProgram({
        id: 'single-loses',
        title: 'Single loses',
        sourceId: 'single-loses',
        fundingAmountRub: 20
      }),
      syntheticProgram({
        id: 'alpha',
        title: 'Alpha',
        sourceId: 'alpha',
        fundingAmountRub: 5
      }),
      syntheticProgram({
        id: 'bravo',
        title: 'Bravo',
        sourceId: 'bravo',
        fundingAmountRub: 5
      })
    ]);

    expect(analytics.finance.bySource.map((item) => item.id)).toEqual([
      'high',
      'count-wins',
      'single-loses',
      'alpha',
      'bravo'
    ]);
    expect(analytics.finance.bySource.find((item) => item.id === 'high')?.shareOfKnownFunding).toBe(0.5);
  });

  it('uses distribution IDs when metrics and labels are identical', () => {
    const sameNameSources = [
      { ...syntheticSources[0], id: 'source-b', name: 'Same source' },
      { ...syntheticSources[0], id: 'source-a', name: 'Same source' }
    ] as const satisfies readonly SupportSource[];
    const analytics = buildAnalytics(sameNameSources, [
      syntheticProgram({ id: 'program-b', sourceId: 'source-b', fundingAmountRub: 100 }),
      syntheticProgram({ id: 'program-a', sourceId: 'source-a', fundingAmountRub: 100 })
    ]);

    expect(analytics.finance.bySource.map((item) => item.id)).toEqual(['source-a', 'source-b']);
  });
});

describe('support gap analytics', () => {
  it('identifies weak regions, topics, and region-topic pairs', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.supportGaps.weakRegions.length).toBeGreaterThan(0);
    expect(analytics.supportGaps.weakTopics.length).toBeGreaterThan(0);
    expect(analytics.supportGaps.weakRegionTopicPairs.length).toBeGreaterThan(0);
  });

  it('explains support gap reasons and severity', () => {
    const analytics = buildAnalytics(sources, programs);
    const weakPair = analytics.supportGaps.weakRegionTopicPairs[0];

    expect(weakPair).toMatchObject({
      id: expect.any(String),
      label: expect.any(String),
      reason: expect.any(String),
      programCount: expect.any(Number),
      totalFundingRub: expect.any(Number),
      severity: expect.stringMatching(/high|medium|low/)
    });
    expect(weakPair.reason.length).toBeGreaterThan(20);
  });

  it('returns empty gaps and respects filtered input', () => {
    expect(buildAnalytics(syntheticSources, []).supportGaps).toEqual({
      weakRegions: [],
      weakTopics: [],
      weakRegionTopicPairs: []
    });

    const filtered = buildAnalytics(
      syntheticSources,
      [
        syntheticProgram({ id: 'included-gap', status: 'Открыта', regions: ['Included'] }),
        syntheticProgram({ id: 'excluded-gap', status: 'Закрыта', regions: ['Excluded'] })
      ],
      { status: 'Открыта' }
    );

    expect(filtered.supportGaps.weakRegions.map((gap) => gap.id)).toEqual(['region:Included']);
    expect(filtered.supportGaps.weakTopics).toMatchObject([
      { id: 'topic:Технологии', programCount: 1, totalFundingRub: 0 }
    ]);
    expect(filtered.supportGaps.weakRegionTopicPairs).toMatchObject([
      { id: 'topic-region:Технологии:Included', programCount: 1, totalFundingRub: 0 }
    ]);
  });

  it('classifies support-gap severity at exact count and funding boundaries', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({ id: 'high', regions: ['High'], fundingAmountRub: 999999 }),
      syntheticProgram({ id: 'exact-million', regions: ['Exact million'], fundingAmountRub: 1000000 }),
      syntheticProgram({ id: 'medium-1', regions: ['Medium'], fundingAmountRub: 1000000 }),
      syntheticProgram({ id: 'medium-2', regions: ['Medium'], fundingAmountRub: 1999999 }),
      syntheticProgram({ id: 'low-count-1', regions: ['Low count'] }),
      syntheticProgram({ id: 'low-count-2', regions: ['Low count'] }),
      syntheticProgram({ id: 'low-count-3', regions: ['Low count'] }),
      syntheticProgram({ id: 'low-funding', regions: ['Low funding'], fundingAmountRub: 3000000 })
    ]);
    const severityById = Object.fromEntries(
      analytics.supportGaps.weakRegions.map((gap) => [gap.id, gap.severity])
    );

    expect(severityById).toMatchObject({
      'region:High': 'high',
      'region:Exact million': 'medium',
      'region:Medium': 'medium',
      'region:Low count': 'low',
      'region:Low funding': 'low'
    });
  });

  it('sorts equal support gaps deterministically and enforces list limits', () => {
    const topicNames = [
      'Экология',
      'Технологии',
      'Социальные проекты',
      'Региональное развитие',
      'Предпринимательство',
      'Образование',
      'Наука',
      'Культура',
      'ИИ'
    ] as const;
    const analytics = buildAnalytics(
      syntheticSources,
      topicNames.map((topic, index) =>
        syntheticProgram({ id: `gap-${index}`, topics: [topic], regions: [`Region ${index}`] })
      )
    );

    expect(analytics.supportGaps.weakRegions).toHaveLength(5);
    expect(analytics.supportGaps.weakTopics).toHaveLength(5);
    expect(analytics.supportGaps.weakRegionTopicPairs).toHaveLength(8);
    expect(analytics.supportGaps.weakRegions.map((gap) => gap.id)).toEqual([
      'region:Region 0',
      'region:Region 1',
      'region:Region 2',
      'region:Region 3',
      'region:Region 4'
    ]);
    expect(analytics.supportGaps.weakTopics.map((gap) => gap.label)).toEqual([
      'ИИ',
      'Культура',
      'Наука',
      'Образование',
      'Предпринимательство'
    ]);
    expect(analytics.supportGaps.weakRegionTopicPairs.map((gap) => gap.id)).toEqual([
      'topic-region:ИИ:Region 8',
      'topic-region:Культура:Region 7',
      'topic-region:Наука:Region 6',
      'topic-region:Образование:Region 5',
      'topic-region:Предпринимательство:Region 4',
      'topic-region:Региональное развитие:Region 3',
      'topic-region:Социальные проекты:Region 2',
      'topic-region:Технологии:Region 1'
    ]);
  });
});

describe('regional analytics', () => {
  it('computes region counts, active counts, funding, and coverage-level breakdowns', () => {
    const analytics = buildAnalytics(sources, programs);
    const russia = analytics.regional.regions.find((item) => item.region === 'Россия');

    expect(russia).toMatchObject({
      region: 'Россия',
      programCount: 26,
      activeProgramCount: 18,
      federalProgramCount: 17,
      regionalProgramCount: 0,
      privateProgramCount: 9,
      municipalProgramCount: 0
    });
    expect(russia?.totalFundingRub).toBe(53400000);
    expect(russia?.coverageScore).toBeGreaterThan(0);
  });

  it('identifies high and low coverage regions from observed seed coverage', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.regional.highCoverageRegions[0].region).toBe('Россия');
    expect(analytics.regional.lowCoverageRegions.map((item) => item.region)).toContain('Москва');
  });

  it('counts federal, regional, private, and municipal programs', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.regional.federalPrograms).toBe(18);
    expect(analytics.regional.regionalPrograms).toBe(3);
    expect(analytics.regional.privatePrograms).toBe(9);
    expect(analytics.regional.municipalPrograms).toBe(0);
  });

  it('counts coverage levels from filtered programs only', () => {
    const analytics = buildAnalytics(
      syntheticSources,
      [
        syntheticProgram({
          id: 'filtered-federal',
          title: 'Filtered federal',
          coverageLevel: 'federal',
          status: 'Открыта'
        }),
        syntheticProgram({
          id: 'filtered-private',
          title: 'Filtered private',
          coverageLevel: 'private',
          status: 'Открыта'
        }),
        syntheticProgram({
          id: 'filtered-municipal',
          title: 'Filtered municipal',
          coverageLevel: 'municipal',
          status: 'Открыта'
        }),
        syntheticProgram({
          id: 'excluded-regional',
          title: 'Excluded regional',
          coverageLevel: 'regional',
          status: 'Закрыта'
        }),
        syntheticProgram({
          id: 'excluded-private',
          title: 'Excluded private',
          coverageLevel: 'private',
          status: 'Закрыта'
        })
      ],
      { status: 'Открыта' }
    );

    expect(analytics.regional.federalPrograms).toBe(1);
    expect(analytics.regional.regionalPrograms).toBe(0);
    expect(analytics.regional.privatePrograms).toBe(1);
    expect(analytics.regional.municipalPrograms).toBe(1);
  });

  it('attributes full funding to every region on multi-region programs', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'multi-region-full-funding',
        title: 'Multi-region full funding',
        fundingAmountRub: 1200000,
        regions: ['Россия', 'Татарстан']
      })
    ]);

    expect(analytics.regional.regions.find((item) => item.region === 'Россия')).toMatchObject({
      totalFundingRub: 1200000,
      averageFundingRub: 1200000
    });
    expect(analytics.regional.regions.find((item) => item.region === 'Татарстан')).toMatchObject({
      totalFundingRub: 1200000,
      averageFundingRub: 1200000
    });
  });

  it('sorts regions deterministically by score and region name', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'gamma-funded-1',
        title: 'Gamma funded 1',
        fundingAmountRub: 2000000,
        regions: ['Гамма']
      }),
      syntheticProgram({
        id: 'gamma-funded-2',
        title: 'Gamma funded 2',
        fundingAmountRub: 1000000,
        regions: ['Гамма']
      }),
      syntheticProgram({
        id: 'alpha-funded',
        title: 'Alpha funded',
        fundingAmountRub: 1000000,
        regions: ['Альфа']
      }),
      syntheticProgram({
        id: 'beta-funded',
        title: 'Beta funded',
        fundingAmountRub: 1000000,
        regions: ['Бета']
      }),
      syntheticProgram({
        id: 'delta-unfunded',
        title: 'Delta unfunded',
        regions: ['Дельта']
      })
    ]);
    const gamma = analytics.regional.regions.find((item) => item.region === 'Гамма');

    expect(analytics.regional.regions.map((item) => item.region)).toEqual(['Гамма', 'Альфа', 'Бета', 'Дельта']);
    expect(analytics.regional.highCoverageRegions.map((item) => item.region)).toEqual([
      'Гамма',
      'Альфа',
      'Бета',
      'Дельта'
    ]);
    expect(analytics.regional.lowCoverageRegions.map((item) => item.region)).toEqual([
      'Дельта',
      'Альфа',
      'Бета',
      'Гамма'
    ]);
    expect(gamma).toMatchObject({
      programCount: 2,
      totalFundingRub: 3000000,
      coverageScore: 2 * 2 + Math.round(3000000 / 1_000_000)
    });
  });
});

describe('source analytics', () => {
  it('ranks sources by total programs, active programs, funding, and data quality', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.sources.byProgramCount.find((item) => item.sourceId === 'asi')).toMatchObject({
      sourceId: 'asi',
      programCount: 3
    });
    expect(analytics.sources.byActiveProgramCount[0].activeProgramCount).toBe(3);
    expect(analytics.sources.byFunding[0]).toMatchObject({
      sourceId: 'fasie',
      totalFundingRub: 24500000
    });
    expect(analytics.sources.byDataQuality[0].dataCompletenessScore).toBeGreaterThanOrEqual(
      analytics.sources.byDataQuality.at(-1)?.dataCompletenessScore ?? 0
    );
  });

  it('counts incomplete programs per source', () => {
    const analytics = buildAnalytics(sources, programs);
    const skolkovo = analytics.sources.byProgramCount.find((item) => item.sourceId === 'skolkovo');

    expect(skolkovo).toMatchObject({
      sourceName: 'Сколково',
      programCount: 3,
      incompleteProgramCount: 2
    });
  });

  it('uses source IDs as final tie-breakers for every source ranking', () => {
    const sameNameSources = [
      { ...syntheticSources[0], id: 'source-b', name: 'Same source' },
      { ...syntheticSources[0], id: 'source-a', name: 'Same source' }
    ] as const satisfies readonly SupportSource[];
    const analytics = buildAnalytics(sameNameSources, [
      syntheticProgram({ id: 'program-b', sourceId: 'source-b', fundingAmountRub: 100 }),
      syntheticProgram({ id: 'program-a', sourceId: 'source-a', fundingAmountRub: 100 })
    ]);

    expect(analytics.sources.byProgramCount.map((item) => item.sourceId)).toEqual(['source-a', 'source-b']);
    expect(analytics.sources.byActiveProgramCount.map((item) => item.sourceId)).toEqual(['source-a', 'source-b']);
    expect(analytics.sources.byFunding.map((item) => item.sourceId)).toEqual(['source-a', 'source-b']);
    expect(analytics.sources.byDataQuality.map((item) => item.sourceId)).toEqual(['source-a', 'source-b']);
  });
});

describe('data quality analytics', () => {
  it('computes missing-field shares and overall completeness index', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.dataQuality.missingFundingShare).toBeCloseTo(15 / 30, 4);
    expect(analytics.dataQuality.missingDeadlineShare).toBeCloseTo(10 / 30, 4);
    expect(analytics.dataQuality.missingRegionShare).toBe(0);
    expect(analytics.dataQuality.missingUpdatedAtShare).toBe(0);
    expect(analytics.dataQuality.completenessIndex).toBeGreaterThan(70);
  });

  it('computes completeness by source', () => {
    const analytics = buildAnalytics(sources, programs);
    const fasie = analytics.dataQuality.bySource.find((item) => item.sourceId === 'fasie');

    expect(fasie).toMatchObject({
      sourceName: 'Фонд содействия инновациям',
      incompleteProgramCount: 1
    });
    expect(fasie?.completenessIndex).toBeGreaterThan(80);
  });

  it('keeps unobserved sources nullable and behind measured quality under a narrow filter', () => {
    const filteredSources = [
      syntheticSources[0],
      { ...syntheticSources[0], id: 'unobserved-z', name: 'Unobserved' },
      { ...syntheticSources[0], id: 'unobserved-a', name: 'Unobserved' }
    ] as const satisfies readonly SupportSource[];
    const analytics = buildAnalytics(
      filteredSources,
      [
        syntheticProgram({
          dataQuality: {
            score: 75,
            level: 'medium',
            missingFields: ['deadline'],
            checkedAt: '2026-07-01'
          }
        })
      ],
      { sourceId: 'synthetic-source' }
    );

    expect(analytics.dataQuality.completenessIndex).toBe(75);
    expect(
      analytics.dataQuality.bySource.map(({ sourceId, completenessIndex }) => ({
        sourceId,
        completenessIndex
      }))
    ).toEqual([
      { sourceId: 'synthetic-source', completenessIndex: 75 },
      { sourceId: 'unobserved-a', completenessIndex: null },
      { sourceId: 'unobserved-z', completenessIndex: null }
    ]);
    expect(
      analytics.sources.byDataQuality.map(({ sourceId, dataCompletenessScore }) => ({
        sourceId,
        dataCompletenessScore
      }))
    ).toEqual([
      { sourceId: 'synthetic-source', dataCompletenessScore: 75 },
      { sourceId: 'unobserved-a', dataCompletenessScore: null },
      { sourceId: 'unobserved-z', dataCompletenessScore: null }
    ]);
    expect(analytics.sources.byProgramCount).toHaveLength(3);
    expect(
      analytics.sources.byProgramCount.find((item) => item.sourceId === 'unobserved-a')?.programCount
    ).toBe(0);
  });

  it('handles empty data quality input safely', () => {
    const analytics = buildAnalytics(sources, []);

    expect(analytics.dataQuality).toMatchObject({
      missingFundingShare: 0,
      missingDeadlineShare: 0,
      missingRegionShare: 0,
      missingUpdatedAtShare: 0,
      completenessIndex: 0
    });
  });

  it('uses score below 100 as the canonical incomplete-program rule', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'perfect-with-missing-field',
        title: 'Perfect with missing field',
        dataQuality: {
          score: 100,
          level: 'high',
          missingFields: ['deadline'],
          checkedAt: '2026-07-01'
        }
      }),
      syntheticProgram({
        id: 'imperfect-without-missing-fields',
        title: 'Imperfect without missing fields',
        dataQuality: {
          score: 99,
          level: 'high',
          missingFields: [],
          checkedAt: '2026-07-01'
        }
      })
    ]);

    expect(analytics.sources.byProgramCount[0].incompleteProgramCount).toBe(1);
    expect(analytics.dataQuality.bySource[0].incompleteProgramCount).toBe(1);
    expect(analytics.dataQuality.incompletePrograms).toEqual([
      {
        programId: 'imperfect-without-missing-fields',
        title: 'Imperfect without missing fields',
        missingFields: []
      }
    ]);
  });
});

describe('topic analytics', () => {
  it('computes program counts, active counts, funding, region counts, and strength by topic', () => {
    const analytics = buildAnalytics(sources, programs);
    const technology = analytics.topics.topics.find((item) => item.topic === 'Технологии');

    expect(technology).toMatchObject({
      topic: 'Технологии',
      programCount: 13,
      activeProgramCount: 10,
      strength: 'strong'
    });
    expect(technology?.totalFundingRub).toBeGreaterThan(30000000);
    expect(technology?.regionCount).toBeGreaterThanOrEqual(2);
  });

  it('identifies strong and weak topics', () => {
    const analytics = buildAnalytics(sources, programs);
    const weakAnalytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'weak-ecology-topic',
        title: 'Weak ecology topic',
        topics: ['Экология'],
        fundingAmountRub: 1000000
      })
    ]);

    expect(analytics.topics.strongTopics.map((item) => item.topic)).toContain('Технологии');
    expect(weakAnalytics.topics.topics.find((item) => item.topic === 'Экология')).toMatchObject({
      programCount: 1,
      totalFundingRub: 1000000,
      strength: 'weak'
    });
    expect(weakAnalytics.topics.weakTopics.map((item) => item.topic)).toContain('Экология');
  });

  it('builds topic and region intersections', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.topics.intersections).toContainEqual(
      expect.objectContaining({
        topic: 'ИИ',
        region: 'Россия',
        programCount: expect.any(Number),
        totalFundingRub: expect.any(Number)
      })
    );
  });

  it('builds exact topic-region intersections in deterministic order', () => {
    const analytics = buildAnalytics(syntheticSources, [
      syntheticProgram({
        id: 'technology-ecology',
        topics: ['Технологии', 'Экология'],
        regions: ['Россия', 'Татарстан'],
        fundingAmountRub: 100
      }),
      syntheticProgram({
        id: 'technology',
        topics: ['Технологии'],
        regions: ['Россия'],
        fundingAmountRub: 200
      }),
      syntheticProgram({
        id: 'ecology',
        topics: ['Экология'],
        regions: ['Татарстан'],
        fundingAmountRub: 50
      })
    ]);

    expect(analytics.topics.intersections).toEqual([
      { topic: 'Технологии', region: 'Россия', programCount: 2, totalFundingRub: 300 },
      { topic: 'Экология', region: 'Татарстан', programCount: 2, totalFundingRub: 150 },
      { topic: 'Технологии', region: 'Татарстан', programCount: 1, totalFundingRub: 100 },
      { topic: 'Экология', region: 'Россия', programCount: 1, totalFundingRub: 100 }
    ]);
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
