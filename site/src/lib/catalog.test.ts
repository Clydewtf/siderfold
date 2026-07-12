import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import type { ProgramFilters, SourceFilters, SupportProgram } from '../types';
import { filterPrograms, filterSources, getProgramsBySource, getSourceProgramCounts, sortPrograms } from './catalog';

const defaultProgramFilters: ProgramFilters = {
  query: '',
  region: 'Все регионы',
  coverageLevel: 'Все уровни',
  launchYear: 'Все годы',
  activePeriod: 'all',
  funding: 'all',
  fundingMinRub: null,
  fundingMaxRub: null,
  deadline: 'all',
  status: 'Все статусы',
  topic: 'Все тематики',
  supportType: 'Все типы',
  audience: 'Все аудитории',
  sourceId: 'Все источники',
  sort: 'deadline'
};

const defaultSourceFilters: SourceFilters = {
  type: 'Все типы',
  region: 'Все регионы',
  coverageLevel: 'Все уровни',
  topic: 'Все тематики'
};

function withFilters(overrides: Partial<ProgramFilters>): ProgramFilters {
  return { ...defaultProgramFilters, ...overrides };
}

describe('catalog selectors', () => {
  it('searches by title and description case-insensitively', () => {
    const result = filterPrograms(programs, sources, withFilters({ query: 'искусственного интеллекта' }));

    expect(result.map((program) => program.id)).toContain('fasie-start-ai');
  });

  it('filters by topic, support type, audience, status, and deadline window', () => {
    const result = filterPrograms(programs, sources, withFilters({
      query: '',
      topic: 'ИИ',
      supportType: 'Акселерация',
      audience: 'Стартапы',
      status: 'Открыта',
      deadline: 'next90'
    }));

    expect(result.map((program) => program.id)).toEqual(['skolkovo-industrial-ai', 'sber-unity-ai-pilot']);
  });

  it('sorts by deadline, funding, newest, and source name', () => {
    expect(sortPrograms(programs, sources, 'deadline')[0].id).toBe('impact-hub-eco-impact');
    expect(sortPrograms(programs, sources, 'funding')[0].id).toBe('fasie-development');
    expect(sortPrograms(programs, sources, 'newest')[0].id).toBe('creative-russia-export');
    expect(sortPrograms(programs, sources, 'source')[0].sourceId).toBe('asi');
  });

  it('sorts funding by exact amount or upper range when exact amount is missing', () => {
    const result = sortPrograms(
      [
        { ...programs[0], id: 'range-only', fundingAmountRub: null, fundingMinRub: 1000000, fundingMaxRub: 9000000 },
        { ...programs[1], id: 'exact-small', fundingAmountRub: 1500000, fundingMinRub: 500000, fundingMaxRub: 1500000 }
      ],
      sources,
      'funding'
    );

    expect(result.map((program) => program.id)).toEqual(['range-only', 'exact-small']);
  });

  it('searches title, description, source, requirements, regions, topics, and audience', () => {
    expect(filterPrograms(programs, sources, withFilters({ query: 'Фонд содействия инновациям' })).map((item) => item.sourceId))
      .toEqual(['fasie', 'fasie', 'fasie']);
    expect(filterPrograms(programs, sources, withFilters({ query: 'Питч-дек' })).map((item) => item.id))
      .toContain('sber-unity-student-founders');
    expect(filterPrograms(programs, sources, withFilters({ query: 'Москва' })).map((item) => item.id))
      .toContain('impact-hub-eco-impact');
  });

  it('matches short queries as whole tokens instead of substrings inside words', () => {
    const input = [
      {
        ...programs[0],
        id: 'exact-ai-topic',
        sourceId: 'fond-potanin',
        title: 'Технологическая программа',
        description: 'Поддержка команд',
        requirements: ['Готовый проект'],
        topics: ['ИИ']
      },
      {
        ...programs[0],
        id: 'word-substring-only',
        sourceId: 'fond-potanin',
        title: 'Организации региона',
        description: 'Социальные инновации',
        requirements: ['Описание инициативы'],
        topics: ['Образование']
      }
    ] satisfies SupportProgram[];

    expect(filterPrograms(input, sources, withFilters({ query: 'ИИ' })).map((item) => item.id))
      .toEqual(['exact-ai-topic']);
  });

  it('filters by region, coverage level, launch year, and source', () => {
    const result = filterPrograms(programs, sources, withFilters({
      region: 'Москва',
      coverageLevel: 'regional',
      launchYear: 2021,
      sourceId: 'impact-hub'
    }));

    expect(result.map((item) => item.id)).toEqual(['impact-hub-eco-impact']);
  });

  it('filters programs active now, upcoming, and ended on the catalog reference date', () => {
    const periodPrograms = [
      { ...programs[0], id: 'active-now', activeFrom: '2026-06-01', activeTo: '2026-08-01' },
      { ...programs[0], id: 'upcoming', activeFrom: '2026-07-02', activeTo: '2026-09-01' },
      { ...programs[0], id: 'ended', activeFrom: '2026-01-01', activeTo: '2026-06-30' }
    ] satisfies SupportProgram[];

    const activeNow = filterPrograms(periodPrograms, sources, withFilters({ activePeriod: 'activeNow' }));
    const upcoming = filterPrograms(periodPrograms, sources, withFilters({ activePeriod: 'upcoming' }));
    const ended = filterPrograms(periodPrograms, sources, withFilters({ activePeriod: 'ended' }));

    expect(activeNow.map((item) => item.id)).toEqual(['active-now']);
    expect(upcoming.map((item) => item.id)).toEqual(['upcoming']);
    expect(ended.map((item) => item.id)).toEqual(['ended']);
  });

  it('filters by funding presence and overlapping amount range', () => {
    const funded = filterPrograms(programs, sources, withFilters({
      funding: 'withFunding',
      fundingMinRub: 3_500_000,
      fundingMaxRub: 4_500_000
    }));
    const unfunded = filterPrograms(programs, sources, withFilters({ funding: 'withoutFunding' }));

    expect(funded.map((item) => item.id)).toContain('fasie-start-ai');
    expect(funded.every((item) => item.fundingAmountRub !== null || item.fundingMinRub !== null || item.fundingMaxRub !== null)).toBe(true);
    expect(unfunded.every((item) => item.fundingAmountRub === null && item.fundingMinRub === null && item.fundingMaxRub === null)).toBe(true);
  });

  it('prefers explicit funding bounds over exact funding fallback when both are present', () => {
    const input = [
      {
        ...programs[0],
        id: 'range-wins-over-exact',
        fundingAmountRub: 4_000_000,
        fundingMinRub: 1_000_000,
        fundingMaxRub: 4_000_000
      }
    ] satisfies SupportProgram[];

    expect(filterPrograms(input, sources, withFilters({ fundingMinRub: 1_500_000, fundingMaxRub: 2_000_000 })).map((item) => item.id))
      .toEqual(['range-wins-over-exact']);
  });

  it('rejects an invalid amount interval instead of silently widening it', () => {
    expect(filterPrograms(programs, sources, withFilters({ fundingMinRub: 5_000_000, fundingMaxRub: 1_000_000 }))).toEqual([]);
  });

  it('ranks exact title matches ahead of description and source matches', () => {
    const input = [
      { ...programs[0], id: 'description-hit', title: 'Другая программа', description: 'Программа Старт-ИИ для команд' },
      { ...programs[0], id: 'title-hit', title: 'Старт-ИИ', description: 'Другая формулировка' }
    ] satisfies SupportProgram[];

    expect(sortPrograms(input, sources, 'relevance', 'Старт-ИИ').map((item) => item.id)).toEqual([
      'title-hit',
      'description-hit'
    ]);
  });

  it('falls back to deadline sorting when relevance has no query', () => {
    expect(sortPrograms(programs, sources, 'relevance', '').map((item) => item.id))
      .toEqual(sortPrograms(programs, sources, 'deadline').map((item) => item.id));
  });

  it('uses publication date and id as stable relevance tie-breakers', () => {
    const input = [
      { ...programs[0], id: 'older-b', title: 'ИИ программа', publishedAt: '2026-01-01' },
      { ...programs[0], id: 'newer-a', title: 'ИИ программа', publishedAt: '2026-02-01' }
    ] satisfies SupportProgram[];

    expect(sortPrograms(input, sources, 'relevance', 'ИИ').map((item) => item.id)).toEqual(['newer-a', 'older-b']);
  });

  it('ranks a whole-token relevance hit ahead of an incidental substring-only title hit', () => {
    const input = [
      { ...programs[0], id: 'substring-only-newer', title: 'Организации региона', publishedAt: '2026-02-01' },
      { ...programs[0], id: 'whole-token-older', title: 'Решения ИИ', publishedAt: '2026-01-01' }
    ] satisfies SupportProgram[];

    expect(sortPrograms(input, sources, 'relevance', 'ИИ').map((item) => item.id)).toEqual([
      'whole-token-older',
      'substring-only-newer'
    ]);
  });

  it('filters sources by type, region, coverage level, and topic', () => {
    const result = filterSources(sources, {
      ...defaultSourceFilters,
      type: 'Акселератор',
      region: 'Москва и онлайн',
      coverageLevel: 'regional',
      topic: 'Экология'
    });

    expect(result.map((source) => source.id)).toEqual(['impact-hub']);
  });

  it('returns an empty source result when filters do not intersect', () => {
    expect(filterSources(sources, {
      ...defaultSourceFilters,
      type: 'Университет',
      coverageLevel: 'regional'
    })).toEqual([]);
  });

  it('counts all and active programs by source', () => {
    const counts = getSourceProgramCounts(sources, programs);
    expect(counts['fond-potanin']).toEqual({ total: 3, active: 2 });
    expect(getProgramsBySource(programs, 'skolkovo')).toHaveLength(3);
  });
});
