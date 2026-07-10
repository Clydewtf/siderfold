import type {
  Audience,
  CoverageLevel,
  DeadlineFilter,
  ProgramStatus,
  SupportProgram,
  SupportSource,
  SourceType,
  SupportType,
  Topic
} from '../types';
import { daysUntilDeadline, isActiveStatus } from './catalog';

export type AnalyticsFilters = {
  region: string | 'Все регионы';
  year: number | 'Все годы';
  coverageLevel: CoverageLevel | 'Все уровни';
  sourceId: string | 'Все источники';
  supportType: SupportType | 'Все типы';
  topic: Topic | 'Все тематики';
  audience: Audience | 'Все аудитории';
  status: ProgramStatus | 'Все статусы';
  funding: 'all' | 'withFunding' | 'withoutFunding';
  deadline: DeadlineFilter;
};

export const defaultAnalyticsFilters: AnalyticsFilters = {
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
};

type FundingLike = Pick<SupportProgram, 'fundingAmountRub' | 'fundingMaxRub' | 'fundingMinRub'>;

export function getProgramFundingValue(program: FundingLike): number | null {
  return program.fundingAmountRub ?? program.fundingMaxRub ?? program.fundingMinRub;
}

export function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const midpoint = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[midpoint];
  return (sorted[midpoint - 1] + sorted[midpoint]) / 2;
}

function matchesAnalyticsDeadline(program: SupportProgram, filter: DeadlineFilter): boolean {
  const days = daysUntilDeadline(program.deadline);
  if (filter === 'all') return true;
  if (filter === 'withDeadline') return program.deadline !== null;
  if (filter === 'withoutDeadline') return program.deadline === null;
  if (filter === 'next30') return days !== null && days >= 0 && days <= 30;
  if (filter === 'next90') return days !== null && days >= 0 && days <= 90;
  return true;
}

export function normalizeAnalyticsFilters(filters: Partial<AnalyticsFilters> = {}): AnalyticsFilters {
  const definedFilters = Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined)
  ) as Partial<AnalyticsFilters>;
  return { ...defaultAnalyticsFilters, ...definedFilters };
}

export function applyAnalyticsFilters(
  programs: readonly SupportProgram[],
  filters: Partial<AnalyticsFilters> = {}
): SupportProgram[] {
  const normalized = normalizeAnalyticsFilters(filters);

  return programs.filter((program) => {
    const fundingValue = getProgramFundingValue(program);

    return (
      (normalized.region === 'Все регионы' || program.regions.includes(normalized.region)) &&
      (normalized.year === 'Все годы' ||
        program.launchYear === normalized.year ||
        program.history.some((point) => point.year === normalized.year)) &&
      (normalized.coverageLevel === 'Все уровни' || program.coverageLevel === normalized.coverageLevel) &&
      (normalized.sourceId === 'Все источники' || program.sourceId === normalized.sourceId) &&
      (normalized.supportType === 'Все типы' || program.supportType === normalized.supportType) &&
      (normalized.topic === 'Все тематики' || program.topics.includes(normalized.topic)) &&
      (normalized.audience === 'Все аудитории' || program.audience.includes(normalized.audience)) &&
      (normalized.status === 'Все статусы' || program.status === normalized.status) &&
      (normalized.funding === 'all' ||
        (normalized.funding === 'withFunding' && fundingValue !== null) ||
        (normalized.funding === 'withoutFunding' && fundingValue === null)) &&
      matchesAnalyticsDeadline(program, normalized.deadline)
    );
  });
}

type DistributionItem = {
  id: string;
  label: string;
  count: number;
};

export type MoneyDistributionItem = {
  id: string;
  label: string;
  count: number;
  totalFundingRub: number;
  averageFundingRub: number | null;
  shareOfKnownFunding: number;
};

export type FinancialAnalytics = {
  totalFundingRub: number;
  averageFundingRub: number | null;
  medianFundingRub: number | null;
  maxFundingRub: number | null;
  fundedPrograms: number;
  unknownFundingPrograms: number;
  bySupportType: MoneyDistributionItem[];
  bySource: MoneyDistributionItem[];
  byRegion: MoneyDistributionItem[];
  byCoverageLevel: MoneyDistributionItem[];
};

export type RegionAnalyticsItem = {
  region: string;
  programCount: number;
  activeProgramCount: number;
  totalFundingRub: number;
  averageFundingRub: number | null;
  federalProgramCount: number;
  regionalProgramCount: number;
  privateProgramCount: number;
  municipalProgramCount: number;
  coverageScore: number;
};

export type RegionalAnalytics = {
  regions: RegionAnalyticsItem[];
  highCoverageRegions: RegionAnalyticsItem[];
  lowCoverageRegions: RegionAnalyticsItem[];
  federalPrograms: number;
  regionalPrograms: number;
  privatePrograms: number;
  municipalPrograms: number;
};

export type SourceAnalyticsItem = {
  sourceId: string;
  sourceName: string;
  sourceType: SourceType;
  coverageLevel: CoverageLevel;
  programCount: number;
  activeProgramCount: number;
  totalFundingRub: number;
  averageFundingRub: number | null;
  dataCompletenessScore: number;
  incompleteProgramCount: number;
};

export type SourceAnalytics = {
  byProgramCount: SourceAnalyticsItem[];
  byActiveProgramCount: SourceAnalyticsItem[];
  byFunding: SourceAnalyticsItem[];
  byDataQuality: SourceAnalyticsItem[];
};

export type TopicAnalyticsItem = {
  topic: Topic;
  programCount: number;
  activeProgramCount: number;
  totalFundingRub: number;
  averageFundingRub: number | null;
  regionCount: number;
  strength: 'strong' | 'moderate' | 'weak';
};

export type TopicRegionIntersection = {
  topic: Topic;
  region: string;
  programCount: number;
  totalFundingRub: number;
};

export type TopicAnalytics = {
  topics: TopicAnalyticsItem[];
  strongTopics: TopicAnalyticsItem[];
  weakTopics: TopicAnalyticsItem[];
  intersections: TopicRegionIntersection[];
};

export type SupportGap = {
  id: string;
  label: string;
  reason: string;
  programCount: number;
  totalFundingRub: number;
  severity: 'high' | 'medium' | 'low';
};

export type SupportGapsAnalytics = {
  weakRegions: SupportGap[];
  weakTopics: SupportGap[];
  weakRegionTopicPairs: SupportGap[];
};

export type YearAnalyticsItem = {
  year: number;
  launchedPrograms: number;
  activePrograms: number;
  totalFundingRub: number;
};

export type DeadlineAnalyticsItem = {
  programId: string;
  title: string;
  deadline: string;
  daysUntilDeadline: number;
};

export type TemporalAnalytics = {
  nearestDeadline: DeadlineAnalyticsItem | null;
  nearestDeadlines: DeadlineAnalyticsItem[];
  withoutDeadline: { programId: string; title: string }[];
  byYear: YearAnalyticsItem[];
};

export type ForecastAnalytics = {
  nextYear: number;
  expectedFundingRub: number | null;
  expectedProgramCount: number | null;
  expectedProgramCountChange: number | null;
  growingTopics: { topic: Topic; growthRate: number; confidence: 'high' | 'medium' | 'low' }[];
  confidence: 'high' | 'medium' | 'low';
  confidenceScore: number;
  method: string;
};

type MoneySummary = {
  totalFundingRub: number;
  averageFundingRub: number;
  medianFundingRub: number;
};

type DataQualitySummary = {
  averageScore: number;
  incompletePrograms: { programId: string; title: string; missingFields: readonly string[] }[];
};

export type DataQualityAnalytics = DataQualitySummary & {
  missingFundingShare: number;
  missingDeadlineShare: number;
  missingRegionShare: number;
  missingUpdatedAtShare: number;
  completenessIndex: number;
  bySource: {
    sourceId: string;
    sourceName: string;
    completenessIndex: number;
    incompleteProgramCount: number;
  }[];
};

export type AnalyticsSummary = MoneySummary & {
  totalPrograms: number;
  totalSources: number;
  filteredPrograms: number;
  activePrograms: number;
  maxFundingRub: number | null;
  fundedShare: number;
  filters: AnalyticsFilters;
  nearestDeadline: { programId: string; title: string; deadline: string } | null;
  nearestDeadlines: { programId: string; title: string; deadline: string }[];
  bySource: DistributionItem[];
  bySupportType: DistributionItem[];
  byRegion: DistributionItem[];
  byCoverageLevel: DistributionItem[];
  finance: FinancialAnalytics;
  regional: RegionalAnalytics;
  sources: SourceAnalytics;
  topics: TopicAnalytics;
  supportGaps: SupportGapsAnalytics;
  temporal: TemporalAnalytics;
  forecast: ForecastAnalytics;
  dataQuality: DataQualityAnalytics;
};

function buildDistribution(labels: readonly string[]): DistributionItem[] {
  return Array.from(new Set(labels))
    .sort((a, b) => a.localeCompare(b, 'ru'))
    .map((label) => ({
      id: label,
      label,
      count: labels.filter((item) => item === label).length
    }));
}

function sum(values: readonly number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

function average(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  return sum(values) / values.length;
}

function share(count: number, total: number): number {
  return total === 0 ? 0 : count / total;
}

function buildDataQualityAnalytics(
  sources: readonly SupportSource[],
  programs: readonly SupportProgram[]
): DataQualityAnalytics {
  const total = programs.length;
  const completenessIndex = average(programs.map((program) => program.dataQuality.score)) ?? 0;

  return {
    missingFundingShare: share(
      programs.filter((program) => program.dataQuality.missingFields.includes('funding')).length,
      total
    ),
    missingDeadlineShare: share(
      programs.filter((program) => program.dataQuality.missingFields.includes('deadline')).length,
      total
    ),
    missingRegionShare: share(
      programs.filter((program) => program.dataQuality.missingFields.includes('regions')).length,
      total
    ),
    missingUpdatedAtShare: share(
      programs.filter((program) => program.dataQuality.missingFields.includes('updatedAt')).length,
      total
    ),
    completenessIndex,
    bySource: sources
      .map((source) => {
        const related = programs.filter((program) => program.sourceId === source.id);
        return {
          sourceId: source.id,
          sourceName: source.name,
          completenessIndex: average(related.map((program) => program.dataQuality.score)) ?? 0,
          incompleteProgramCount: related.filter((program) => program.dataQuality.score < 100).length
        };
      })
      .sort(
        (a, b) =>
          a.completenessIndex - b.completenessIndex ||
          b.incompleteProgramCount - a.incompleteProgramCount ||
          a.sourceName.localeCompare(b.sourceName, 'ru')
      ),
    averageScore: completenessIndex,
    incompletePrograms: programs
      .filter((program) => program.dataQuality.missingFields.length > 0)
      .map((program) => ({
        programId: program.id,
        title: program.title,
        missingFields: program.dataQuality.missingFields
      }))
  };
}

function fundingValues(programs: readonly SupportProgram[]): number[] {
  return programs.map(getProgramFundingValue).filter((value): value is number => value !== null);
}

function buildMoneyDistribution(
  entries: readonly { id: string; label: string; program: SupportProgram }[],
  knownFundingDenominator = sum(entries.map((entry) => getProgramFundingValue(entry.program) ?? 0))
): MoneyDistributionItem[] {
  const groups = new Map<string, { label: string; programs: SupportProgram[] }>();

  entries.forEach((entry) => {
    const group = groups.get(entry.id) ?? { label: entry.label, programs: [] };
    group.programs.push(entry.program);
    groups.set(entry.id, group);
  });

  return Array.from(groups.entries())
    .map(([id, group]) => {
      const values = fundingValues(group.programs);
      const totalFundingRub = sum(values);
      return {
        id,
        label: group.label,
        count: group.programs.length,
        totalFundingRub,
        averageFundingRub: average(values),
        shareOfKnownFunding: knownFundingDenominator === 0 ? 0 : totalFundingRub / knownFundingDenominator
      };
    })
    .sort((a, b) => b.totalFundingRub - a.totalFundingRub || b.count - a.count || a.label.localeCompare(b.label, 'ru'));
}

function buildFinancialAnalytics(
  sources: readonly SupportSource[],
  programs: readonly SupportProgram[]
): FinancialAnalytics {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  const values = fundingValues(programs);
  const totalFundingRub = sum(values);

  return {
    totalFundingRub,
    averageFundingRub: average(values),
    medianFundingRub: median(values),
    maxFundingRub: values.length > 0 ? Math.max(...values) : null,
    fundedPrograms: values.length,
    unknownFundingPrograms: programs.length - values.length,
    bySupportType: buildMoneyDistribution(
      programs.map((program) => ({
        id: program.supportType,
        label: program.supportType,
        program
      }))
    ),
    bySource: buildMoneyDistribution(
      programs.map((program) => {
        const source = sourceById.get(program.sourceId);
        return {
          id: program.sourceId,
          label: source?.name ?? program.sourceId,
          program
        };
      })
    ),
    byRegion: buildMoneyDistribution(
      programs.flatMap((program) =>
        program.regions.map((region) => ({
          id: region,
          label: region,
          program
        }))
      ),
      totalFundingRub
    ),
    byCoverageLevel: buildMoneyDistribution(
      programs.map((program) => ({
        id: program.coverageLevel,
        label: program.coverageLevel,
        program
      }))
    )
  };
}

function countCoverage(programs: readonly SupportProgram[], level: CoverageLevel): number {
  return programs.filter((program) => program.coverageLevel === level).length;
}

function buildRegionalAnalytics(programs: readonly SupportProgram[]): RegionalAnalytics {
  const regions = Array.from(new Set(programs.flatMap((program) => program.regions))).sort((a, b) =>
    a.localeCompare(b, 'ru')
  );

  const items = regions
    .map((region) => {
      const related = programs.filter((program) => program.regions.includes(region));
      const values = fundingValues(related);
      const totalFundingRub = sum(values);

      return {
        region,
        programCount: related.length,
        activeProgramCount: related.filter((program) => isActiveStatus(program.status)).length,
        totalFundingRub,
        averageFundingRub: average(values),
        federalProgramCount: countCoverage(related, 'federal'),
        regionalProgramCount: countCoverage(related, 'regional'),
        privateProgramCount: countCoverage(related, 'private'),
        municipalProgramCount: countCoverage(related, 'municipal'),
        coverageScore: related.length * 2 + Math.round(totalFundingRub / 1_000_000)
      };
    })
    .sort((a, b) => b.coverageScore - a.coverageScore || a.region.localeCompare(b.region, 'ru'));

  return {
    regions: items,
    highCoverageRegions: items.slice(0, 5),
    lowCoverageRegions: [...items]
      .sort((a, b) => a.coverageScore - b.coverageScore || a.region.localeCompare(b.region, 'ru'))
      .slice(0, 5),
    federalPrograms: countCoverage(programs, 'federal'),
    regionalPrograms: countCoverage(programs, 'regional'),
    privatePrograms: countCoverage(programs, 'private'),
    municipalPrograms: countCoverage(programs, 'municipal')
  };
}

function topicStrength(programCount: number, totalFundingRub: number): TopicAnalyticsItem['strength'] {
  if (programCount >= 5 || totalFundingRub >= 10_000_000) return 'strong';
  if (programCount >= 3 || totalFundingRub >= 2_000_000) return 'moderate';
  return 'weak';
}

function buildTopicAnalytics(programs: readonly SupportProgram[]): TopicAnalytics {
  const topics = Array.from(new Set(programs.flatMap((program) => program.topics))).sort((a, b) =>
    a.localeCompare(b, 'ru')
  );

  const items = topics
    .map((topic) => {
      const related = programs.filter((program) => program.topics.includes(topic));
      const values = fundingValues(related);
      const regions = new Set(related.flatMap((program) => program.regions));
      const totalFundingRub = sum(values);

      return {
        topic,
        programCount: related.length,
        activeProgramCount: related.filter((program) => isActiveStatus(program.status)).length,
        totalFundingRub,
        averageFundingRub: average(values),
        regionCount: regions.size,
        strength: topicStrength(related.length, totalFundingRub)
      };
    })
    .sort((a, b) => b.programCount - a.programCount || b.totalFundingRub - a.totalFundingRub);

  const intersections = topics
    .flatMap((topic) => {
      const regions = Array.from(
        new Set(programs.filter((program) => program.topics.includes(topic)).flatMap((program) => program.regions))
      );

      return regions.map((region) => {
        const related = programs.filter((program) => program.topics.includes(topic) && program.regions.includes(region));
        return {
          topic,
          region,
          programCount: related.length,
          totalFundingRub: sum(fundingValues(related))
        };
      });
    })
    .sort(
      (a, b) =>
        b.programCount - a.programCount ||
        b.totalFundingRub - a.totalFundingRub ||
        a.topic.localeCompare(b.topic, 'ru') ||
        a.region.localeCompare(b.region, 'ru')
    );

  return {
    topics: items,
    strongTopics: items.filter((item) => item.strength === 'strong'),
    weakTopics: items.filter((item) => item.strength === 'weak'),
    intersections
  };
}

function gapSeverity(programCount: number, totalFundingRub: number): SupportGap['severity'] {
  if (programCount <= 1 && totalFundingRub < 1_000_000) return 'high';
  if (programCount <= 2 && totalFundingRub < 3_000_000) return 'medium';
  return 'low';
}

function buildSupportGapsAnalytics(regional: RegionalAnalytics, topics: TopicAnalytics): SupportGapsAnalytics {
  const weakRegions = [...regional.regions]
    .sort((a, b) => a.coverageScore - b.coverageScore || a.region.localeCompare(b.region, 'ru'))
    .slice(0, 5)
    .map((region) => ({
      id: `region:${region.region}`,
      label: region.region,
      reason: `В текущей seed-базе регион имеет ${region.programCount} программ и ${region.totalFundingRub} ₽ известного объема поддержки.`,
      programCount: region.programCount,
      totalFundingRub: region.totalFundingRub,
      severity: gapSeverity(region.programCount, region.totalFundingRub)
    }));

  const weakTopics = [...topics.topics]
    .sort((a, b) => a.programCount - b.programCount || a.totalFundingRub - b.totalFundingRub)
    .slice(0, 5)
    .map((topic) => ({
      id: `topic:${topic.topic}`,
      label: topic.topic,
      reason: `В текущей seed-базе тематика имеет ${topic.programCount} программ и ${topic.totalFundingRub} ₽ известного объема поддержки.`,
      programCount: topic.programCount,
      totalFundingRub: topic.totalFundingRub,
      severity: gapSeverity(topic.programCount, topic.totalFundingRub)
    }));

  const weakRegionTopicPairs = [...topics.intersections]
    .sort((a, b) => a.programCount - b.programCount || a.totalFundingRub - b.totalFundingRub)
    .slice(0, 8)
    .map((intersection) => ({
      id: `topic-region:${intersection.topic}:${intersection.region}`,
      label: `${intersection.topic} / ${intersection.region}`,
      reason: `Сочетание тематики и региона в текущей seed-базе представлено ${intersection.programCount} программами и ${intersection.totalFundingRub} ₽ известного объема поддержки.`,
      programCount: intersection.programCount,
      totalFundingRub: intersection.totalFundingRub,
      severity: gapSeverity(intersection.programCount, intersection.totalFundingRub)
    }));

  return { weakRegions, weakTopics, weakRegionTopicPairs };
}

function buildSourceAnalytics(
  sources: readonly SupportSource[],
  programs: readonly SupportProgram[]
): SourceAnalytics {
  const items = sources.map((source) => {
    const related = programs.filter((program) => program.sourceId === source.id);
    const values = fundingValues(related);
    const completenessScores = related.map((program) => program.dataQuality.score);

    return {
      sourceId: source.id,
      sourceName: source.name,
      sourceType: source.type,
      coverageLevel: source.coverageLevel,
      programCount: related.length,
      activeProgramCount: related.filter((program) => isActiveStatus(program.status)).length,
      totalFundingRub: sum(values),
      averageFundingRub: average(values),
      dataCompletenessScore: average(completenessScores) ?? 0,
      incompleteProgramCount: related.filter((program) => program.dataQuality.score < 100).length
    };
  });

  const byProgramCount = [...items].sort(
    (a, b) => b.programCount - a.programCount || a.sourceName.localeCompare(b.sourceName, 'ru')
  );
  const byActiveProgramCount = [...items].sort(
    (a, b) => b.activeProgramCount - a.activeProgramCount || a.sourceName.localeCompare(b.sourceName, 'ru')
  );
  const byFunding = [...items].sort(
    (a, b) => b.totalFundingRub - a.totalFundingRub || a.sourceName.localeCompare(b.sourceName, 'ru')
  );
  const byDataQuality = [...items].sort(
    (a, b) => b.dataCompletenessScore - a.dataCompletenessScore || a.sourceName.localeCompare(b.sourceName, 'ru')
  );

  return { byProgramCount, byActiveProgramCount, byFunding, byDataQuality };
}

function buildTemporalAnalytics(programs: readonly SupportProgram[]): TemporalAnalytics {
  const nearestDeadlines = programs
    .map((program) => {
      const days = daysUntilDeadline(program.deadline);
      if (program.deadline === null || days === null || days < 0) return null;
      return {
        programId: program.id,
        title: program.title,
        deadline: program.deadline,
        daysUntilDeadline: days
      };
    })
    .filter((item): item is DeadlineAnalyticsItem => item !== null)
    .sort((a, b) => a.daysUntilDeadline - b.daysUntilDeadline || a.title.localeCompare(b.title, 'ru'))
    .slice(0, 5);

  const years = Array.from(new Set(programs.flatMap((program) => program.history.map((point) => point.year)))).sort(
    (a, b) => a - b
  );

  const byYear = years.map((year) => ({
    year,
    launchedPrograms: programs.filter((program) => program.launchYear === year).length,
    activePrograms: programs.filter((program) => program.history.some((point) => point.year === year)).length,
    totalFundingRub: sum(
      programs.flatMap((program) =>
        program.history
          .filter((point) => point.year === year)
          .map((point) => point.fundingAmountRub)
          .filter((value): value is number => value !== null)
      )
    )
  }));

  return {
    nearestDeadline: nearestDeadlines[0] ?? null,
    nearestDeadlines,
    withoutDeadline: programs
      .filter((program) => program.deadline === null)
      .map((program) => ({ programId: program.id, title: program.title }))
      .sort((a, b) => a.title.localeCompare(b.title, 'ru')),
    byYear
  };
}

function growthRate(previous: number, current: number): number | null {
  if (previous <= 0) return null;
  return (current - previous) / previous;
}

function smoothGrowthRate(rates: readonly number[]): number {
  if (rates.length === 0) return 0;
  const clamped = rates.map((rate) => Math.max(-0.5, Math.min(0.75, rate)));
  return average(clamped) ?? 0;
}

function forecastConfidence(programs: readonly SupportProgram[], yearCount: number): {
  confidence: ForecastAnalytics['confidence'];
  confidenceScore: number;
} {
  if (programs.length === 0 || yearCount < 2) return { confidence: 'low', confidenceScore: 0 };
  const historyCompleteness = programs.filter((program) => program.history.length >= 3).length / programs.length;
  const fundingCompleteness = fundingValues(programs).length / programs.length;
  const confidenceScore = Math.round(((historyCompleteness + fundingCompleteness) / 2) * 100);
  const confidence = confidenceScore >= 75 ? 'high' : confidenceScore >= 45 ? 'medium' : 'low';
  return { confidence, confidenceScore };
}

function buildForecastAnalytics(programs: readonly SupportProgram[], temporal: TemporalAnalytics): ForecastAnalytics {
  const years = temporal.byYear.map((item) => item.year);
  const latestYear = years.at(-1) ?? 2026;
  const method =
    'Демо-прогноз по историческим seed-данным: группировка по годам, расчет темпа роста, сглаживание резких скачков и тренд по тематикам. Это не настоящая ML-система.';

  if (programs.length === 0 || temporal.byYear.length === 0) {
    return {
      nextYear: latestYear + 1,
      expectedFundingRub: null,
      expectedProgramCount: null,
      expectedProgramCountChange: null,
      growingTopics: [],
      confidence: 'low',
      confidenceScore: 0,
      method
    };
  }

  const fundingRates = temporal.byYear
    .slice(1)
    .map((item, index) => growthRate(temporal.byYear[index].totalFundingRub, item.totalFundingRub))
    .filter((rate): rate is number => rate !== null);
  const programRates = temporal.byYear
    .slice(1)
    .map((item, index) => growthRate(temporal.byYear[index].activePrograms, item.activePrograms))
    .filter((rate): rate is number => rate !== null);

  const latest = temporal.byYear.at(-1);
  const smoothedFundingGrowth = smoothGrowthRate(fundingRates);
  const smoothedProgramGrowth = smoothGrowthRate(programRates);
  const confidence = forecastConfidence(programs, temporal.byYear.length);

  const topics = Array.from(new Set(programs.flatMap((program) => program.topics)));
  const growingTopics = topics
    .map((topic) => {
      const totals = temporal.byYear.map((yearItem) => {
        const related = programs.filter((program) => program.topics.includes(topic));
        return sum(
          related.flatMap((program) =>
            program.history
              .filter((point) => point.year === yearItem.year)
              .map((point) => point.fundingAmountRub)
              .filter((value): value is number => value !== null)
          )
        );
      });
      const rates = totals
        .slice(1)
        .map((value, index) => growthRate(totals[index], value))
        .filter((rate): rate is number => rate !== null);
      return {
        topic,
        growthRate: smoothGrowthRate(rates),
        confidence: confidence.confidence
      };
    })
    .filter((item) => item.growthRate > 0)
    .sort((a, b) => b.growthRate - a.growthRate)
    .slice(0, 5);

  return {
    nextYear: latestYear + 1,
    expectedFundingRub: latest ? Math.round(latest.totalFundingRub * (1 + smoothedFundingGrowth)) : null,
    expectedProgramCount: latest ? Math.round(latest.activePrograms * (1 + smoothedProgramGrowth)) : null,
    expectedProgramCountChange: latest ? Math.round(latest.activePrograms * smoothedProgramGrowth) : null,
    growingTopics,
    confidence: confidence.confidence,
    confidenceScore: confidence.confidenceScore,
    method
  };
}

export function buildAnalytics(
  sources: readonly SupportSource[],
  programs: readonly SupportProgram[],
  filters: Partial<AnalyticsFilters> = {}
): AnalyticsSummary {
  const normalizedFilters = normalizeAnalyticsFilters(filters);
  const filteredPrograms = applyAnalyticsFilters(programs, normalizedFilters);
  const finance = buildFinancialAnalytics(sources, filteredPrograms);
  const regional = buildRegionalAnalytics(filteredPrograms);
  const sourceAnalytics = buildSourceAnalytics(sources, filteredPrograms);
  const topicAnalytics = buildTopicAnalytics(filteredPrograms);
  const supportGaps = buildSupportGapsAnalytics(regional, topicAnalytics);
  const temporal = buildTemporalAnalytics(filteredPrograms);
  const forecast = buildForecastAnalytics(filteredPrograms, temporal);
  const dataQuality = buildDataQualityAnalytics(sources, filteredPrograms);

  return {
    totalPrograms: filteredPrograms.length,
    totalSources: sources.length,
    filteredPrograms: filteredPrograms.length,
    activePrograms: filteredPrograms.filter((program) => isActiveStatus(program.status)).length,
    maxFundingRub: finance.maxFundingRub,
    fundedShare: filteredPrograms.length === 0 ? 0 : finance.fundedPrograms / filteredPrograms.length,
    totalFundingRub: finance.totalFundingRub,
    averageFundingRub: finance.averageFundingRub ?? 0,
    medianFundingRub: finance.medianFundingRub ?? 0,
    filters: normalizedFilters,
    nearestDeadline: temporal.nearestDeadline
      ? {
          programId: temporal.nearestDeadline.programId,
          title: temporal.nearestDeadline.title,
          deadline: temporal.nearestDeadline.deadline
        }
      : null,
    nearestDeadlines: temporal.nearestDeadlines.map((item) => ({
      programId: item.programId,
      title: item.title,
      deadline: item.deadline
    })),
    bySource: sources.map((source) => ({
      id: source.id,
      label: source.name,
      count: filteredPrograms.filter((program) => program.sourceId === source.id).length
    })),
    bySupportType: Array.from(new Set(filteredPrograms.map((program) => program.supportType)))
      .sort((a, b) => a.localeCompare(b, 'ru'))
      .map((supportType) => ({
        id: supportType,
        label: supportType,
        count: filteredPrograms.filter((program) => program.supportType === supportType).length
      })),
    byRegion: buildDistribution(filteredPrograms.flatMap((program) => program.regions)),
    byCoverageLevel: buildDistribution(filteredPrograms.map((program) => program.coverageLevel)),
    finance,
    regional,
    sources: sourceAnalytics,
    topics: topicAnalytics,
    supportGaps,
    temporal,
    forecast,
    dataQuality
  };
}
