import { formatMoneyRub } from '../lib/format';
import type {
  Audience,
  CoverageLevel,
  DeadlineFilter,
  ProgramFilters as ProgramFiltersState,
  ProgramStatus,
  SupportSource,
  SupportType,
  Topic
} from '../types';

export type FilterOptions = {
  regions: readonly string[];
  coverageLevels: readonly CoverageLevel[];
  launchYears: readonly number[];
  statuses: readonly ProgramStatus[];
  topics: readonly Topic[];
  supportTypes: readonly SupportType[];
  audiences: readonly Audience[];
  sources: readonly SupportSource[];
};

export type ProgramFiltersProps = {
  filters: ProgramFiltersState;
  options: FilterOptions;
  isDesktopOpen: boolean;
  onChange: (patch: Partial<ProgramFiltersState>) => void;
  onReset: () => void;
};

const fieldClassName = 'rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink';

function amountFromInput(value: string): number | null {
  if (value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function activeFilterLabels(filters: ProgramFiltersState): string[] {
  const labels: string[] = [];
  if (filters.query.trim()) labels.push(`Поиск: ${filters.query.trim()}`);
  if (filters.region !== 'Все регионы') labels.push(`Регион: ${filters.region}`);
  if (filters.coverageLevel !== 'Все уровни') labels.push(`Уровень: ${filters.coverageLevel}`);
  if (filters.launchYear !== 'Все годы') labels.push(`Год запуска: ${filters.launchYear}`);
  if (filters.activePeriod !== 'all') labels.push(`Период действия: ${filters.activePeriod}`);
  if (filters.funding !== 'all') labels.push(`Наличие суммы: ${filters.funding}`);
  if (filters.fundingMinRub !== null) labels.push(`От ${formatMoneyRub(filters.fundingMinRub)}`);
  if (filters.fundingMaxRub !== null) labels.push(`До ${formatMoneyRub(filters.fundingMaxRub)}`);
  if (filters.deadline !== 'all') labels.push(`Дедлайн: ${filters.deadline}`);
  if (filters.status !== 'Все статусы') labels.push(`Статус: ${filters.status}`);
  if (filters.topic !== 'Все тематики') labels.push(`Тематика: ${filters.topic}`);
  if (filters.supportType !== 'Все типы') labels.push(`Тип: ${filters.supportType}`);
  if (filters.audience !== 'Все аудитории') labels.push(`Аудитория: ${filters.audience}`);
  if (filters.sourceId !== 'Все источники') labels.push(`Источник: ${filters.sourceId}`);
  if (filters.sort !== 'deadline') labels.push(`Сортировка: ${filters.sort}`);
  return labels;
}

export function ProgramFilters({ filters, options, isDesktopOpen, onChange, onReset }: ProgramFiltersProps) {
  const chips = activeFilterLabels(filters);
  const deadlineFilters: readonly [DeadlineFilter, string][] = [
    ['all', 'Все дедлайны'],
    ['withDeadline', 'С дедлайном'],
    ['withoutDeadline', 'Без дедлайна'],
    ['next30', '30 дней'],
    ['next90', '90 дней']
  ];

  return (
    <>
      <details open={isDesktopOpen ? true : undefined} className="mt-3 rounded-lg border border-ink/10 bg-white/70 p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-semibold text-ink lg:hidden">Фильтры</summary>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:mt-0 lg:grid-cols-3 xl:grid-cols-4">
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Регион программы
            <select value={filters.region} onChange={(event) => onChange({ region: event.target.value })} className={fieldClassName}>
              <option>Все регионы</option>
              {options.regions.map((region) => <option key={region}>{region}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Уровень программы
            <select value={filters.coverageLevel} onChange={(event) => onChange({ coverageLevel: event.target.value as ProgramFiltersState['coverageLevel'] })} className={fieldClassName}>
              <option>Все уровни</option>
              {options.coverageLevels.map((level) => <option key={level} value={level}>{level}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Год запуска
            <select value={filters.launchYear} onChange={(event) => onChange({ launchYear: event.target.value === 'Все годы' ? 'Все годы' : Number(event.target.value) })} className={fieldClassName}>
              <option>Все годы</option>
              {options.launchYears.map((year) => <option key={year} value={year}>{year}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Период действия
            <select value={filters.activePeriod} onChange={(event) => onChange({ activePeriod: event.target.value as ProgramFiltersState['activePeriod'] })} className={fieldClassName}>
              <option value="all">Все периоды</option>
              <option value="activeNow">Активна сейчас</option>
              <option value="upcoming">Скоро начнётся</option>
              <option value="ended">Завершена</option>
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Наличие суммы
            <select value={filters.funding} onChange={(event) => onChange({ funding: event.target.value as ProgramFiltersState['funding'] })} className={fieldClassName}>
              <option value="all">Все программы</option>
              <option value="withFunding">С суммой</option>
              <option value="withoutFunding">Без суммы</option>
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Сумма от, ₽
            <input type="number" min="0" step="100000" value={filters.fundingMinRub ?? ''} onChange={(event) => onChange({ fundingMinRub: amountFromInput(event.target.value) })} className={fieldClassName} />
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Сумма до, ₽
            <input type="number" min="0" step="100000" value={filters.fundingMaxRub ?? ''} onChange={(event) => onChange({ fundingMaxRub: amountFromInput(event.target.value) })} className={fieldClassName} />
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Статус
            <select value={filters.status} onChange={(event) => onChange({ status: event.target.value as ProgramFiltersState['status'] })} className={fieldClassName}>
              <option>Все статусы</option>
              {options.statuses.map((status) => <option key={status}>{status}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Тематика
            <select value={filters.topic} onChange={(event) => onChange({ topic: event.target.value as ProgramFiltersState['topic'] })} className={fieldClassName}>
              <option>Все тематики</option>
              {options.topics.map((topic) => <option key={topic}>{topic}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Тип поддержки
            <select value={filters.supportType} onChange={(event) => onChange({ supportType: event.target.value as ProgramFiltersState['supportType'] })} className={fieldClassName}>
              <option>Все типы</option>
              {options.supportTypes.map((type) => <option key={type}>{type}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Аудитория
            <select value={filters.audience} onChange={(event) => onChange({ audience: event.target.value as ProgramFiltersState['audience'] })} className={fieldClassName}>
              <option>Все аудитории</option>
              {options.audiences.map((audience) => <option key={audience}>{audience}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Источник программы
            <select value={filters.sourceId} onChange={(event) => onChange({ sourceId: event.target.value })} className={fieldClassName}>
              <option>Все источники</option>
              {options.sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm font-medium text-graphite">
            Сортировка
            <select value={filters.sort} onChange={(event) => onChange({ sort: event.target.value as ProgramFiltersState['sort'] })} className={fieldClassName}>
              <option value="deadline">Ближайший дедлайн</option>
              <option value="funding">Максимальная сумма</option>
              <option value="newest">Новизна</option>
              <option value="source">Источник</option>
              {filters.query.trim() ? <option value="relevance">Релевантность</option> : null}
            </select>
          </label>
        </div>
        <section role="group" aria-label="Дедлайн" className="mt-4 flex flex-wrap gap-2">
          {deadlineFilters.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={filters.deadline === value} onClick={() => onChange({ deadline: value })} className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${filters.deadline === value ? 'border-ink bg-ink text-white' : 'border-ink/10 bg-white/70 text-graphite hover:bg-white'}`}>
              {label}
            </button>
          ))}
        </section>
      </details>

      <div role="group" aria-label="Активные фильтры" className="mt-4 flex flex-wrap items-center gap-2">
        {chips.map((label) => <span key={label} className="max-w-full break-words rounded-full border border-cobalt/20 bg-cobalt/10 px-3 py-1 text-xs font-semibold text-cobalt">{label}</span>)}
        {chips.length ? <button type="button" onClick={onReset} className="text-sm font-semibold text-cobalt">Сбросить фильтры</button> : null}
      </div>
    </>
  );
}
