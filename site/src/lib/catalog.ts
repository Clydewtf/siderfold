import type {
  ActivePeriodFilter,
  DeadlineFilter,
  ProgramFilters,
  ProgramSort,
  SourceFilters,
  SupportProgram,
  SupportSource
} from '../types';

const referenceDate = new Date('2026-07-01T00:00:00');
const referenceDay = '2026-07-01';

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

function normalize(value: string): string {
  return value.trim().toLocaleLowerCase('ru-RU');
}

function tokenize(value: string): string[] {
  return normalize(value).match(/[\p{L}\p{N}]+/gu) ?? [];
}

function matchesQuery(value: string, query: string): boolean {
  const queryTokens = tokenize(query);
  if (queryTokens.length === 0) return true;
  const valueTokens = new Set(tokenize(value));
  return queryTokens.every((token) => valueTokens.has(token));
}

function matchesTokenSet(value: string, queryTokens: readonly string[]): boolean {
  if (queryTokens.length === 0) return true;
  const valueTokens = new Set(tokenize(value));
  return queryTokens.every((token) => valueTokens.has(token));
}

function getSource(program: SupportProgram, sources: readonly SupportSource[]): SupportSource | undefined {
  return sources.find((source) => source.id === program.sourceId);
}

function getSearchSections(program: SupportProgram, source: SupportSource | undefined) {
  return {
    title: normalize(program.title),
    description: normalize(program.description),
    source: normalize(source?.name ?? ''),
    requirements: normalize(program.requirements.join(' ')),
    metadata: normalize([
      program.fundingLabel,
      program.supportType,
      ...program.topics,
      ...program.audience,
      ...program.regions
    ].join(' '))
  };
}

function matchesActivePeriod(program: SupportProgram, filter: ActivePeriodFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'activeNow') {
    return program.activeFrom <= referenceDay && (program.activeTo === null || program.activeTo >= referenceDay);
  }
  if (filter === 'upcoming') return program.activeFrom > referenceDay;
  return program.activeTo !== null && program.activeTo < referenceDay;
}

function getFundingBounds(program: SupportProgram): { min: number; max: number } | null {
  if (program.fundingMinRub !== null || program.fundingMaxRub !== null) {
    return {
      min: program.fundingMinRub ?? program.fundingMaxRub ?? 0,
      max: program.fundingMaxRub ?? program.fundingMinRub ?? 0
    };
  }

  const exact = program.fundingAmountRub;
  if (exact !== null) return { min: exact, max: exact };
  return null;
}

function matchesFunding(program: SupportProgram, filters: ProgramFilters): boolean {
  if (filters.fundingMinRub !== null && filters.fundingMaxRub !== null && filters.fundingMinRub > filters.fundingMaxRub) {
    return false;
  }

  const bounds = getFundingBounds(program);
  if (filters.funding === 'withFunding' && bounds === null) return false;
  if (filters.funding === 'withoutFunding' && bounds !== null) return false;
  if (filters.fundingMinRub === null && filters.fundingMaxRub === null) return true;
  if (bounds === null) return false;

  return (
    (filters.fundingMaxRub === null || bounds.min <= filters.fundingMaxRub) &&
    (filters.fundingMinRub === null || bounds.max >= filters.fundingMinRub)
  );
}

function relevanceScore(program: SupportProgram, source: SupportSource | undefined, query: string): number {
  const normalizedQuery = normalize(query);
  if (!normalizedQuery) return 0;
  const sections = getSearchSections(program, source);
  const words = tokenize(query);
  let score = 0;

  if (sections.title === normalizedQuery) score += 100;
  if (matchesTokenSet(sections.title, words)) score += 50;
  if (matchesTokenSet(sections.source, words)) score += 24;
  if (matchesTokenSet(sections.description, words)) score += 16;
  if (matchesTokenSet(sections.requirements, words)) score += 12;
  if (matchesTokenSet(sections.metadata, words)) score += 8;

  for (const word of words) {
    if (matchesTokenSet(sections.title, [word])) score += 10;
    if (matchesTokenSet(sections.source, [word])) score += 6;
    if (matchesTokenSet(sections.description, [word])) score += 4;
    if (matchesTokenSet(sections.requirements, [word])) score += 3;
    if (matchesTokenSet(sections.metadata, [word])) score += 2;
  }

  return score;
}

export function sortPrograms(
  input: readonly SupportProgram[],
  sources: readonly SupportSource[],
  sort: ProgramSort,
  query = ''
): SupportProgram[] {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  if (sort === 'relevance') {
    if (!normalize(query)) return sortPrograms(input, sources, 'deadline');
    return [...input].sort((a, b) => {
      const scoreDifference = relevanceScore(b, sourceById.get(b.sourceId), query) - relevanceScore(a, sourceById.get(a.sourceId), query);
      return scoreDifference || b.publishedAt.localeCompare(a.publishedAt) || a.id.localeCompare(b.id);
    });
  }

  return [...input].sort((a, b) => {
    if (sort === 'funding') {
      return (getComparableFundingRub(b) ?? -1) - (getComparableFundingRub(a) ?? -1) || a.id.localeCompare(b.id);
    }
    if (sort === 'newest') return b.publishedAt.localeCompare(a.publishedAt) || a.id.localeCompare(b.id);
    if (sort === 'source') {
      return (
        (sourceById.get(a.sourceId)?.name ?? '').localeCompare(sourceById.get(b.sourceId)?.name ?? '', 'ru') ||
        a.id.localeCompare(b.id)
      );
    }

    const aDays = daysUntilDeadline(a.deadline);
    const bDays = daysUntilDeadline(b.deadline);
    const aRank = aDays === null ? Number.POSITIVE_INFINITY : aDays < 0 ? 10_000 + Math.abs(aDays) : aDays;
    const bRank = bDays === null ? Number.POSITIVE_INFINITY : bDays < 0 ? 10_000 + Math.abs(bDays) : bDays;
    return aRank - bRank || a.id.localeCompare(b.id);
  });
}

export function filterPrograms(
  programs: readonly SupportProgram[],
  sources: readonly SupportSource[],
  filters: ProgramFilters
): SupportProgram[] {
  const query = normalize(filters.query);

  return programs.filter((program) => {
    const source = getSource(program, sources);
    const searchable = Object.values(getSearchSections(program, source)).join(' ');

    return (
      matchesQuery(searchable, query) &&
      (filters.region === 'Все регионы' || program.regions.includes(filters.region)) &&
      (filters.coverageLevel === 'Все уровни' || program.coverageLevel === filters.coverageLevel) &&
      (filters.launchYear === 'Все годы' || program.launchYear === filters.launchYear) &&
      matchesActivePeriod(program, filters.activePeriod) &&
      matchesFunding(program, filters) &&
      matchesDeadline(program, filters.deadline) &&
      (filters.status === 'Все статусы' || program.status === filters.status) &&
      (filters.topic === 'Все тематики' || program.topics.includes(filters.topic)) &&
      (filters.supportType === 'Все типы' || program.supportType === filters.supportType) &&
      (filters.audience === 'Все аудитории' || program.audience.includes(filters.audience)) &&
      (filters.sourceId === 'Все источники' || program.sourceId === filters.sourceId)
    );
  });
}

export function filterSources(sources: readonly SupportSource[], filters: SourceFilters): SupportSource[] {
  return sources.filter((source) => (
    (filters.type === 'Все типы' || source.type === filters.type) &&
    (filters.region === 'Все регионы' || source.region === filters.region) &&
    (filters.coverageLevel === 'Все уровни' || source.coverageLevel === filters.coverageLevel) &&
    (filters.topic === 'Все тематики' || source.topics.includes(filters.topic))
  ));
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
