import type { CoverageLevel, SourceFilters as SourceFiltersType, SupportSource } from '../types';

const coverageLevels: readonly CoverageLevel[] = ['federal', 'regional', 'municipal', 'private'];

export type SourceFiltersProps = {
  filters: SourceFiltersType;
  sources: readonly SupportSource[];
  onChange: (patch: Partial<SourceFiltersType>) => void;
  onReset: () => void;
};

function uniqueSorted<T extends string>(items: readonly T[]): T[] {
  return Array.from(new Set(items)).sort((a, b) => a.localeCompare(b, 'ru'));
}

export function SourceFilters({ filters, sources, onChange, onReset }: SourceFiltersProps) {
  const sourceTypes = uniqueSorted(sources.map((source) => source.type));
  const regions = uniqueSorted(sources.map((source) => source.region));
  const topics = uniqueSorted(sources.flatMap((source) => source.topics));
  const hasActiveFilters =
    filters.type !== 'Все типы' ||
    filters.region !== 'Все регионы' ||
    filters.coverageLevel !== 'Все уровни' ||
    filters.topic !== 'Все тематики';

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <label className="grid gap-1 text-sm font-medium text-graphite">
        Тип источника
        <select
          value={filters.type}
          onChange={(event) => onChange({ type: event.target.value as SourceFiltersType['type'] })}
          className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
        >
          <option value="Все типы">Все типы</option>
          {sourceTypes.map((type) => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>
      </label>
      <label className="grid gap-1 text-sm font-medium text-graphite">
        Регион источника
        <select
          value={filters.region}
          onChange={(event) => onChange({ region: event.target.value })}
          className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
        >
          <option value="Все регионы">Все регионы</option>
          {regions.map((region) => (
            <option key={region} value={region}>{region}</option>
          ))}
        </select>
      </label>
      <label className="grid gap-1 text-sm font-medium text-graphite">
        Уровень источника
        <select
          value={filters.coverageLevel}
          onChange={(event) => onChange({ coverageLevel: event.target.value as SourceFiltersType['coverageLevel'] })}
          className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
        >
          <option value="Все уровни">Все уровни</option>
          {coverageLevels.map((level) => (
            <option key={level} value={level}>{level}</option>
          ))}
        </select>
      </label>
      <label className="grid gap-1 text-sm font-medium text-graphite">
        Тематика источника
        <select
          value={filters.topic}
          onChange={(event) => onChange({ topic: event.target.value as SourceFiltersType['topic'] })}
          className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
        >
          <option value="Все тематики">Все тематики</option>
          {topics.map((topic) => (
            <option key={topic} value={topic}>{topic}</option>
          ))}
        </select>
      </label>
      {hasActiveFilters ? (
        <button
          type="button"
          onClick={onReset}
          className="w-fit rounded-lg border border-ink/10 bg-white px-4 py-2 text-sm font-semibold text-graphite transition hover:bg-ink/5 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
        >
          Сбросить фильтры источников
        </button>
      ) : null}
    </div>
  );
}
