import { useEffect, useState } from 'react';
import type { AnalyticsFilters } from '../lib/analytics';
import { defaultAnalyticsFilters } from '../lib/analytics';
import { formatCoverageLevel } from '../lib/format';
import type { Audience, CoverageLevel, ProgramStatus, SupportSource, SupportType, Topic } from '../types';

export type AnalyticsFilterOptions = {
  regions: readonly string[];
  years: readonly number[];
  coverageLevels: readonly CoverageLevel[];
  sources: readonly SupportSource[];
  supportTypes: readonly SupportType[];
  topics: readonly Topic[];
  audiences: readonly Audience[];
  statuses: readonly ProgramStatus[];
};

export type AnalyticsFiltersPanelProps = {
  filters: AnalyticsFilters;
  options: AnalyticsFilterOptions;
  onChange: (patch: Partial<AnalyticsFilters>) => void;
  onReset: () => void;
};

const labelClassName = 'grid min-w-0 gap-1 text-sm font-medium text-graphite';
const selectClassName = 'min-w-0 rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink';

const fundingOptions = [
  ['all', 'Любая сумма'], ['withFunding', 'Есть сумма'], ['withoutFunding', 'Сумма не указана']
] as const;
const deadlineOptions = [
  ['all', 'Любой дедлайн'], ['withDeadline', 'Есть дедлайн'],
  ['withoutDeadline', 'Без дедлайна'], ['next30', 'В следующие 30 дней'],
  ['next90', 'В следующие 90 дней']
] as const;

function activeFilterLabels(filters: AnalyticsFilters, sources: readonly SupportSource[]): string[] {
  const labels: string[] = [];
  if (filters.region !== defaultAnalyticsFilters.region) labels.push(`Регион: ${filters.region}`);
  if (filters.year !== defaultAnalyticsFilters.year) labels.push(`Год: ${filters.year}`);
  if (filters.coverageLevel !== defaultAnalyticsFilters.coverageLevel) labels.push(`Уровень: ${formatCoverageLevel(filters.coverageLevel as CoverageLevel)}`);
  if (filters.sourceId !== defaultAnalyticsFilters.sourceId) {
    const sourceName = sources.find((source) => source.id === filters.sourceId)?.name ?? filters.sourceId;
    labels.push(`Источник: ${sourceName}`);
  }
  if (filters.supportType !== defaultAnalyticsFilters.supportType) labels.push(`Тип поддержки: ${filters.supportType}`);
  if (filters.topic !== defaultAnalyticsFilters.topic) labels.push(`Тематика: ${filters.topic}`);
  if (filters.audience !== defaultAnalyticsFilters.audience) labels.push(`Аудитория: ${filters.audience}`);
  if (filters.status !== defaultAnalyticsFilters.status) labels.push(`Статус: ${filters.status}`);
  if (filters.funding !== defaultAnalyticsFilters.funding) {
    labels.push(fundingOptions.find(([value]) => value === filters.funding)?.[1] ?? filters.funding);
  }
  if (filters.deadline !== defaultAnalyticsFilters.deadline) {
    labels.push(deadlineOptions.find(([value]) => value === filters.deadline)?.[1] ?? filters.deadline);
  }
  return labels;
}

export function AnalyticsFiltersPanel({ filters, options, onChange, onReset }: AnalyticsFiltersPanelProps) {
  const [isOpen, setIsOpen] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches
  ));
  const chips = activeFilterLabels(filters, options.sources);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(min-width: 1024px)');
    const syncWithViewport = () => setIsOpen(mediaQuery.matches);
    syncWithViewport();
    mediaQuery.addEventListener('change', syncWithViewport);
    return () => mediaQuery.removeEventListener('change', syncWithViewport);
  }, []);

  return (
    <>
      <details className="group rounded-xl border border-ink/10 bg-white/75 p-4" open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)}>
        <summary className="cursor-pointer text-base font-semibold">Фильтры аналитики</summary>
        <div className="mt-4 grid min-w-0 gap-4 md:grid-cols-2 lg:grid-cols-5">
          <label className={labelClassName}>Регион аналитики<select className={selectClassName} value={filters.region} onChange={(event) => onChange({ region: event.target.value as AnalyticsFilters['region'] })}><option>Все регионы</option>{options.regions.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className={labelClassName}>Год аналитики<select className={selectClassName} value={filters.year} onChange={(event) => onChange({ year: event.target.value === 'Все годы' ? 'Все годы' : Number(event.target.value) })}><option>Все годы</option>{options.years.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className={labelClassName}>Уровень программы аналитики<select className={selectClassName} value={filters.coverageLevel} onChange={(event) => onChange({ coverageLevel: event.target.value as AnalyticsFilters['coverageLevel'] })}><option>Все уровни</option>{options.coverageLevels.map((value) => <option key={value} value={value}>{formatCoverageLevel(value)}</option>)}</select></label>
          <label className={labelClassName}>Источник аналитики<select className={selectClassName} value={filters.sourceId} onChange={(event) => onChange({ sourceId: event.target.value as AnalyticsFilters['sourceId'] })}><option>Все источники</option>{options.sources.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}</select></label>
          <label className={labelClassName}>Тип поддержки аналитики<select className={selectClassName} value={filters.supportType} onChange={(event) => onChange({ supportType: event.target.value as AnalyticsFilters['supportType'] })}><option>Все типы</option>{options.supportTypes.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className={labelClassName}>Тематика аналитики<select className={selectClassName} value={filters.topic} onChange={(event) => onChange({ topic: event.target.value as AnalyticsFilters['topic'] })}><option>Все тематики</option>{options.topics.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className={labelClassName}>Аудитория аналитики<select className={selectClassName} value={filters.audience} onChange={(event) => onChange({ audience: event.target.value as AnalyticsFilters['audience'] })}><option>Все аудитории</option>{options.audiences.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className={labelClassName}>Статус аналитики<select className={selectClassName} value={filters.status} onChange={(event) => onChange({ status: event.target.value as AnalyticsFilters['status'] })}><option>Все статусы</option>{options.statuses.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className={labelClassName}>Наличие суммы аналитики<select className={selectClassName} value={filters.funding} onChange={(event) => onChange({ funding: event.target.value as AnalyticsFilters['funding'] })}>{fundingOptions.map(([value, label]) => <option key={value} value={value} label={label} />)}</select></label>
          <label className={labelClassName}>Наличие дедлайна аналитики<select className={selectClassName} value={filters.deadline} onChange={(event) => onChange({ deadline: event.target.value as AnalyticsFilters['deadline'] })}>{deadlineOptions.map(([value, label]) => <option key={value} value={value} label={label} />)}</select></label>
        </div>
      </details>

      <div role="group" aria-label="Активные BI-фильтры" className="mt-4 flex flex-wrap items-center gap-2">
        {chips.map((label) => <span key={label} className="max-w-full break-words rounded-full border border-cobalt/20 bg-cobalt/10 px-3 py-1 text-xs font-semibold text-cobalt">{label}</span>)}
        {chips.length ? <button type="button" onClick={onReset} className="text-sm font-semibold text-cobalt">Сбросить BI-фильтры</button> : null}
      </div>
    </>
  );
}
