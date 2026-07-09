import type { SupportProgram } from '../types';

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric'
});

export function formatDeadline(value: string | null): string {
  if (!value) return 'Без дедлайна';
  return dateFormatter.format(new Date(`${value}T00:00:00`)).replace(' г.', '');
}

export function formatMoneyRub(value: number | null): string {
  if (value === null) return 'Сумма не указана';
  if (value >= 1_000_000) {
    const millions = value / 1_000_000;
    return `${Number.isInteger(millions) ? millions : millions.toLocaleString('ru-RU')} млн ₽`;
  }
  if (value >= 1_000) return `${Math.round(value / 1_000)} тыс. ₽`;
  return `${value.toLocaleString('ru-RU')} ₽`;
}

export function formatProgramFundingLabel(program: SupportProgram): string {
  return program.fundingLabel || formatMoneyRub(program.fundingAmountRub ?? program.fundingMaxRub ?? program.fundingMinRub);
}

export function isValidExternalUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}
