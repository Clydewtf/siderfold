import type { SupportProgram, SupportSource } from '../types';
import { daysUntilDeadline, getComparableFundingRub, isActiveStatus } from './catalog';

type DistributionItem = {
  id: string;
  label: string;
  count: number;
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
  activePrograms: number;
  maxFundingRub: number | null;
  fundedShare: number;
  nearestDeadline: { programId: string; title: string; deadline: string } | null;
  nearestDeadlines: { programId: string; title: string; deadline: string }[];
  bySource: DistributionItem[];
  bySupportType: DistributionItem[];
  byRegion: DistributionItem[];
  byCoverageLevel: DistributionItem[];
  dataQuality: DataQualitySummary;
};

function median(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}

function buildDistribution(labels: readonly string[]): DistributionItem[] {
  return Array.from(new Set(labels))
    .sort((a, b) => a.localeCompare(b, 'ru'))
    .map((label) => ({
      id: label,
      label,
      count: labels.filter((item) => item === label).length
    }));
}

export function buildAnalytics(sources: readonly SupportSource[], programs: readonly SupportProgram[]): AnalyticsSummary {
  const fundingValues = programs
    .map(getComparableFundingRub)
    .filter((value): value is number => typeof value === 'number');
  const funded = programs.filter((program) => getComparableFundingRub(program) !== null);
  const totalFundingRub = fundingValues.reduce((sum, value) => sum + value, 0);
  const upcoming = programs
    .filter((program) => {
      const days = daysUntilDeadline(program.deadline);
      return days !== null && days >= 0;
    })
    .sort((a, b) => (daysUntilDeadline(a.deadline) ?? 9999) - (daysUntilDeadline(b.deadline) ?? 9999));

  return {
    totalPrograms: programs.length,
    totalSources: sources.length,
    activePrograms: programs.filter((program) => isActiveStatus(program.status)).length,
    maxFundingRub: fundingValues.length > 0 ? Math.max(...fundingValues) : null,
    fundedShare: programs.length === 0 ? 0 : funded.length / programs.length,
    totalFundingRub,
    averageFundingRub: fundingValues.length === 0 ? 0 : totalFundingRub / fundingValues.length,
    medianFundingRub: median(fundingValues),
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
      count: programs.filter((program) => program.sourceId === source.id).length
    })),
    bySupportType: Array.from(new Set(programs.map((program) => program.supportType)))
      .sort((a, b) => a.localeCompare(b, 'ru'))
      .map((supportType) => ({
        id: supportType,
        label: supportType,
        count: programs.filter((program) => program.supportType === supportType).length
      })),
    byRegion: buildDistribution(programs.flatMap((program) => program.regions)),
    byCoverageLevel: buildDistribution(programs.map((program) => program.coverageLevel)),
    dataQuality: {
      averageScore:
        programs.length === 0
          ? 0
          : programs.reduce((sum, program) => sum + program.dataQuality.score, 0) / programs.length,
      incompletePrograms: programs
        .filter((program) => program.dataQuality.missingFields.length > 0)
        .map((program) => ({
          programId: program.id,
          title: program.title,
          missingFields: program.dataQuality.missingFields
        }))
    }
  };
}
