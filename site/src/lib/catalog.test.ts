import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { filterPrograms, getProgramsBySource, getSourceProgramCounts, sortPrograms } from './catalog';

describe('catalog selectors', () => {
  it('searches by title and description case-insensitively', () => {
    const result = filterPrograms(programs, {
      query: 'искусственного интеллекта',
      topic: 'Все тематики',
      supportType: 'Все типы',
      audience: 'Все аудитории',
      status: 'Все статусы',
      deadline: 'all',
      sort: 'deadline'
    });

    expect(result.map((program) => program.id)).toContain('fasie-start-ai');
  });

  it('filters by topic, support type, audience, status, and deadline window', () => {
    const result = filterPrograms(programs, {
      query: '',
      topic: 'ИИ',
      supportType: 'Акселерация',
      audience: 'Стартапы',
      status: 'Открыта',
      deadline: 'next90',
      sort: 'deadline'
    });

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

  it('counts all and active programs by source', () => {
    const counts = getSourceProgramCounts(sources, programs);
    expect(counts['fond-potanin']).toEqual({ total: 3, active: 2 });
    expect(getProgramsBySource(programs, 'skolkovo')).toHaveLength(3);
  });
});
