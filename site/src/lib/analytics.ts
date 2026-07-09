import type {
  Audience,
  CoverageLevel,
  DeadlineFilter,
  ProgramStatus,
  SupportProgram,
  SupportSource,
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

type MoneySummary = {
  totalFundingRub: number;
  averageFundingRub: number;
  medianFundingRub: number;
};

type DataQualitySummary = {
  averageScore: number;
  incompletePrograms: { programId: string; title: string; missingFields: readonly string[] }[];
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
  dataQuality: DataQualitySummary;
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

export function buildAnalytics(
  sources: readonly SupportSource[],
  programs: readonly SupportProgram[],
  filters: Partial<AnalyticsFilters> = {}
): AnalyticsSummary {
  const normalizedFilters = normalizeAnalyticsFilters(filters);
  const filteredPrograms = applyAnalyticsFilters(programs, normalizedFilters);
  const finance = buildFinancialAnalytics(sources, filteredPrograms);
  const upcoming = filteredPrograms
    .filter((program) => {
      const days = daysUntilDeadline(program.deadline);
      return days !== null && days >= 0;
    })
    .sort((a, b) => (daysUntilDeadline(a.deadline) ?? 9999) - (daysUntilDeadline(b.deadline) ?? 9999));

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
    nearestDeadline: upcoming[0]
      ? { programId: upcoming[0].id, title: upcoming[0].title, deadline: upcoming[0].deadline as string }
      : null,
    nearestDeadlines: upcoming.slice(0, 5).map((program) => ({
      programId: program.id,
      title: program.title,
      deadline: program.deadline as string
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
    dataQuality: {
      averageScore:
        filteredPrograms.length === 0
          ? 0
          : filteredPrograms.reduce((sum, program) => sum + program.dataQuality.score, 0) / filteredPrograms.length,
      incompletePrograms: filteredPrograms
        .filter((program) => program.dataQuality.missingFields.length > 0)
        .map((program) => ({
          programId: program.id,
          title: program.title,
          missingFields: program.dataQuality.missingFields
        }))
    }
  };
}
