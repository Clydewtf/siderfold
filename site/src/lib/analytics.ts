import type { SupportProgram, SupportSource } from '../types';
import { daysUntilDeadline, isActiveStatus } from './catalog';

type DistributionItem = {
  id: string;
  label: string;
  count: number;
};

export type AnalyticsSummary = {
  totalPrograms: number;
  totalSources: number;
  activePrograms: number;
  maxFundingRub: number | null;
  fundedShare: number;
  nearestDeadline: { programId: string; title: string; deadline: string } | null;
  nearestDeadlines: { programId: string; title: string; deadline: string }[];
  bySource: DistributionItem[];
  bySupportType: DistributionItem[];
};

export function buildAnalytics(sources: readonly SupportSource[], programs: readonly SupportProgram[]): AnalyticsSummary {
  const funded = programs.filter((program) => typeof program.fundingAmountRub === 'number');
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
    maxFundingRub: funded.length > 0 ? Math.max(...funded.map((program) => program.fundingAmountRub ?? 0)) : null,
    fundedShare: programs.length === 0 ? 0 : funded.length / programs.length,
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
      }))
  };
}
