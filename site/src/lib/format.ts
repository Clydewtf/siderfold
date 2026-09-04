import type { CoverageLevel, SupportProgram } from '../types';

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric'
});

const coverageLabels: Record<CoverageLevel, string> = {
  federal: 'Федеральная',
  regional: 'Региональная',
  municipal: 'Муниципальная',
  private: 'Частная'
};

function formatDate(value: string): string {
  return dateFormatter.format(new Date(`${value}T00:00:00`)).replace(' г.', '');
}

export function formatCoverageLevel(level: CoverageLevel): string {
  return coverageLabels[level];
}

export function formatActivePeriod(program: Pick<SupportProgram, 'activeFrom' | 'activeTo'>): string {
  const start = formatDate(program.activeFrom);
  return program.activeTo ? `${start} — ${formatDate(program.activeTo)}` : `с ${start}, без даты окончания`;
}

export function formatDeadline(value: string | null): string {
  if (!value) return 'Срок не указан';
  return formatDate(value);
}

export function formatOptionalDate(value: string | null, fallback = 'Не указано'): string {
  return value ? formatDate(value) : fallback;
}

export function formatDateRange(start: string | null, end: string | null): string {
  if (start && end) return `${formatDate(start)} — ${formatDate(end)}`;
  if (start) return `с ${formatDate(start)}`;
  if (end) return `до ${formatDate(end)}`;
  return 'Срок не указан';
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
