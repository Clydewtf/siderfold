import { describe, expect, it } from 'vitest';
import { programs } from '../data/seed';
import {
  formatActivePeriod,
  formatCoverageLevel,
  formatDeadline,
  formatMoneyRub,
  formatProgramFundingLabel,
  isValidExternalUrl
} from './format';

describe('format helpers', () => {
  it('formats ruble amounts compactly', () => {
    expect(formatMoneyRub(12000000)).toBe('12 млн ₽');
    expect(formatMoneyRub(700000)).toBe('700 тыс. ₽');
    expect(formatMoneyRub(null)).toBe('Сумма не указана');
  });

  it('formats program funding from the seed label when range data is richer than exact amount', () => {
    const program = programs.find((item) => item.id === 'fasie-development');

    expect(program ? formatProgramFundingLabel(program) : '').toBe('до 20 млн ₽');
  });

  it('formats every coverage level with user-facing Russian copy', () => {
    expect(formatCoverageLevel('federal')).toBe('Федеральная');
    expect(formatCoverageLevel('regional')).toBe('Региональная');
    expect(formatCoverageLevel('municipal')).toBe('Муниципальная');
    expect(formatCoverageLevel('private')).toBe('Частная');
  });

  it('formats bounded and open-ended active periods', () => {
    const bounded = programs.find((item) => item.id === 'fasie-start-ai');
    const openEnded = programs.find((item) => item.id === 'skolkovo-resident-fast-track');

    expect(bounded ? formatActivePeriod(bounded) : '').toBe('1 июня 2026 — 28 февраля 2027');
    expect(openEnded ? formatActivePeriod(openEnded) : '').toBe('с 2 февраля 2026, без даты окончания');
  });

  it('formats deadlines and missing deadlines', () => {
    expect(formatDeadline('2026-07-20')).toBe('20 июля 2026');
    expect(formatDeadline(null)).toBe('Срок не указан');
  });

  it('accepts only http and https external URLs', () => {
    expect(isValidExternalUrl('https://example.org')).toBe(true);
    expect(isValidExternalUrl('http://example.org')).toBe(true);
    expect(isValidExternalUrl('mailto:test@example.org')).toBe(false);
    expect(isValidExternalUrl('not a url')).toBe(false);
  });
});
