import { describe, expect, it } from 'vitest';
import { calculateProgramDataQuality } from './dataQuality';
import type { DataQuality, SupportProgram } from '../types';

const baseProgram: Omit<SupportProgram, 'dataQuality'> = {
  id: 'quality-test',
  sourceId: 'quality-source',
  title: 'Quality Test',
  description: 'Program used to test completeness scoring.',
  status: 'Открыта',
  supportType: 'Грант',
  topics: ['Технологии'],
  audience: ['Стартапы'],
  regions: ['Россия'],
  coverageLevel: 'federal',
  launchYear: 2024,
  activeFrom: '2026-01-01',
  activeTo: '2026-12-31',
  deadline: '2026-08-01',
  fundingAmountRub: 1000000,
  fundingMinRub: 500000,
  fundingMaxRub: 1000000,
  fundingLabel: 'до 1 млн ₽',
  currency: 'RUB',
  requirements: ['Заявка'],
  sourceUrl: 'https://example.org/program',
  documentUrls: [],
  publishedAt: '2026-01-01',
  updatedAt: '2026-06-01',
  featured: false,
  history: [
    { year: 2024, fundingAmountRub: 700000, applicationsCount: 100, winnersCount: 10 },
    { year: 2025, fundingAmountRub: 900000, applicationsCount: 110, winnersCount: 11 },
    { year: 2026, fundingAmountRub: 1000000, applicationsCount: 120, winnersCount: 12 }
  ]
};

describe('calculateProgramDataQuality', () => {
  it('marks complete records as high quality', () => {
    const quality = calculateProgramDataQuality(baseProgram);

    expect(quality).toEqual<DataQuality>({
      score: 100,
      level: 'high',
      missingFields: [],
      checkedAt: '2026-06-01'
    });
  });

  it('reports missing completeness signals', () => {
    const quality = calculateProgramDataQuality({
      ...baseProgram,
      deadline: null,
      fundingAmountRub: null,
      fundingMinRub: null,
      fundingMaxRub: null,
      regions: [],
      sourceUrl: '',
      updatedAt: ''
    });

    expect(quality.score).toBe(17);
    expect(quality.level).toBe('low');
    expect(quality.missingFields).toEqual(['funding', 'deadline', 'regions', 'updatedAt', 'sourceUrl']);
    expect(quality.checkedAt).toBe('unknown');
  });

  it('uses unknown checkedAt when updatedAt is whitespace only', () => {
    const quality = calculateProgramDataQuality({
      ...baseProgram,
      updatedAt: '   '
    });

    expect(quality.missingFields).toContain('updatedAt');
    expect(quality.checkedAt).toBe('unknown');
  });
});
