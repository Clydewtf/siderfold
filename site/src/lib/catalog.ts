import type { DeadlineFilter, ProgramFilters, ProgramSort, SupportProgram, SupportSource } from '../types';

const referenceDate = new Date('2026-07-01T00:00:00');

export function isActiveStatus(status: SupportProgram['status']): boolean {
  return status === 'Открыта' || status === 'Скоро дедлайн' || status === 'Постоянный набор';
}

export function daysUntilDeadline(deadline: string | null): number | null {
  if (!deadline) return null;
  const target = new Date(`${deadline}T00:00:00`);
  return Math.ceil((target.getTime() - referenceDate.getTime()) / 86_400_000);
}

function matchesDeadline(program: SupportProgram, filter: DeadlineFilter): boolean {
  const days = daysUntilDeadline(program.deadline);
  if (filter === 'all') return true;
  if (filter === 'withDeadline') return program.deadline !== null;
  if (filter === 'withoutDeadline') return program.deadline === null;
  if (filter === 'next30') return days !== null && days >= 0 && days <= 30;
  if (filter === 'next90') return days !== null && days >= 0 && days <= 90;
  return true;
}

export function getComparableFundingRub(program: SupportProgram): number | null {
  return program.fundingAmountRub ?? program.fundingMaxRub ?? program.fundingMinRub;
}

export function sortPrograms(
  input: readonly SupportProgram[],
  sources: readonly SupportSource[],
  sort: ProgramSort
): SupportProgram[] {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  return [...input].sort((a, b) => {
    if (sort === 'funding') return (getComparableFundingRub(b) ?? -1) - (getComparableFundingRub(a) ?? -1);
    if (sort === 'newest') return b.publishedAt.localeCompare(a.publishedAt);
    if (sort === 'source') {
      return (sourceById.get(a.sourceId)?.name ?? '').localeCompare(sourceById.get(b.sourceId)?.name ?? '', 'ru');
    }

    const aDays = daysUntilDeadline(a.deadline);
    const bDays = daysUntilDeadline(b.deadline);
    const aRank = aDays === null ? Number.POSITIVE_INFINITY : aDays < 0 ? 10_000 + Math.abs(aDays) : aDays;
    const bRank = bDays === null ? Number.POSITIVE_INFINITY : bDays < 0 ? 10_000 + Math.abs(bDays) : bDays;
    return aRank - bRank;
  });
}

export function filterPrograms(programs: readonly SupportProgram[], filters: ProgramFilters): SupportProgram[] {
  const query = filters.query.trim().toLowerCase();
  const filtered = programs.filter((program) => {
    const queryText = `${program.title} ${program.description}`.toLowerCase();
    return (
      (query.length === 0 || queryText.includes(query)) &&
      (filters.topic === 'Все тематики' || program.topics.includes(filters.topic)) &&
      (filters.supportType === 'Все типы' || program.supportType === filters.supportType) &&
      (filters.audience === 'Все аудитории' || program.audience.includes(filters.audience)) &&
      (filters.status === 'Все статусы' || program.status === filters.status) &&
      matchesDeadline(program, filters.deadline)
    );
  });

  return filtered;
}

export function getProgramsBySource(programs: readonly SupportProgram[], sourceId: string): SupportProgram[] {
  return programs.filter((program) => program.sourceId === sourceId);
}

export function getSourceProgramCounts(sources: readonly SupportSource[], programs: readonly SupportProgram[]) {
  return Object.fromEntries(
    sources.map((source) => {
      const related = getProgramsBySource(programs, source.id);
      return [
        source.id,
        {
          total: related.length,
          active: related.filter((program) => isActiveStatus(program.status)).length
        }
      ];
    })
  ) as Record<string, { total: number; active: number }>;
}
