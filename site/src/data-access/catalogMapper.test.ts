import { describe, expect, it } from 'vitest';
import { fundingLabel, mapProgramDetail } from './catalogMapper';

describe('public catalog mapper', () => {
  it('keeps unknown funding unknown instead of inventing an amount', () => {
    expect(fundingLabel({
      value_kind: 'unknown',
      currency_code: null,
      exact_amount: null,
      min_amount: null,
      max_amount: null
    })).toBe('Сумма неизвестна');
  });

  it('maps exact and range funding without losing their kind', () => {
    const exact = fundingLabel({
      value_kind: 'exact',
      currency_code: 'RUB',
      exact_amount: '125000',
      min_amount: null,
      max_amount: null
    });
    const range = fundingLabel({
      value_kind: 'range',
      currency_code: 'RUB',
      exact_amount: null,
      min_amount: '100000',
      max_amount: '500000'
    });

    expect(exact.replace(/\s/g, ' ')).toContain('125 000');
    expect(range.replace(/\s/g, ' ')).toContain('100 000');
    expect(range.replace(/\s/g, ' ')).toContain('500 000');
  });

  it('maps detail taxonomies and sources to public UI data', () => {
    const program = mapProgramDetail({
      id: 'program-1',
      title: 'Программа',
      publication_status: 'published',
      published_at: '2025-02-10T09:00:00Z',
      updated_at: '2025-02-14T10:30:00Z',
      deadline_on: null,
      funding: null,
      primary_source: {
        source: { id: 'source-1', name: 'Источник', canonical_url: 'https://example.org' },
        source_url: 'https://example.org/programs/one',
        observed_at: '2025-02-14T10:30:00Z'
      },
      sources: [{
        source: { id: 'source-1', name: 'Источник', canonical_url: 'https://example.org' },
        source_url: 'https://example.org/programs/one',
        observed_at: '2025-02-14T10:30:00Z'
      }],
      geographies: [{ slug: 'russia', name: 'Россия' }],
      themes: [{ slug: 'science', name: 'Наука' }]
    });

    expect(program.regions).toEqual(['Россия']);
    expect(program.themes).toEqual(['Наука']);
    expect(program.sources[0]?.sourceUrl).toBe('https://example.org/programs/one');
  });
});
