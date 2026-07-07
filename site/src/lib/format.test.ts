import { describe, expect, it } from 'vitest';
import { formatDeadline, formatMoneyRub, isValidExternalUrl } from './format';

describe('format helpers', () => {
  it('formats ruble amounts compactly', () => {
    expect(formatMoneyRub(12000000)).toBe('12 млн ₽');
    expect(formatMoneyRub(700000)).toBe('700 тыс. ₽');
    expect(formatMoneyRub(null)).toBe('Сумма не указана');
  });

  it('formats deadlines and missing deadlines', () => {
    expect(formatDeadline('2026-07-20')).toBe('20 июля 2026');
    expect(formatDeadline(null)).toBe('Без дедлайна');
  });

  it('accepts only http and https external URLs', () => {
    expect(isValidExternalUrl('https://example.org')).toBe(true);
    expect(isValidExternalUrl('http://example.org')).toBe(true);
    expect(isValidExternalUrl('mailto:test@example.org')).toBe(false);
    expect(isValidExternalUrl('not a url')).toBe(false);
  });
});
