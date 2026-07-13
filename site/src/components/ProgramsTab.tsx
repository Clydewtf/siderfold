import { Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { filterPrograms, sortPrograms } from '../lib/catalog';
import type { CoverageLevel, ProgramFilters as ProgramFiltersState, SupportProgram, SupportSource } from '../types';
import { ProgramCard } from './ProgramCard';
import { ProgramFilters, type FilterOptions } from './ProgramFilters';
import { EmptyState, PageIntro } from './ui';

const coverageLevels: readonly CoverageLevel[] = ['federal', 'regional', 'municipal', 'private'];

const defaultFilters: ProgramFiltersState = {
  query: '',
  region: 'Все регионы',
  coverageLevel: 'Все уровни',
  launchYear: 'Все годы',
  activePeriod: 'all',
  funding: 'all',
  fundingMinRub: null,
  fundingMaxRub: null,
  deadline: 'all',
  status: 'Все статусы',
  topic: 'Все тематики',
  supportType: 'Все типы',
  audience: 'Все аудитории',
  sourceId: 'Все источники',
  sort: 'deadline'
};

export type ProgramsTabProps = {
  sources: readonly SupportSource[];
  programs: readonly SupportProgram[];
  favoriteProgramIds: readonly string[];
  showDataQuality: boolean;
  onToggleFavoriteProgram: (programId: string) => void;
  onOpenProgram: (program: SupportProgram) => void;
};

function values<T>(items: readonly T[], compare: (a: T, b: T) => number): T[] {
  return Array.from(new Set(items)).sort(compare);
}

export function ProgramsTab({
  sources,
  programs,
  favoriteProgramIds,
  showDataQuality,
  onToggleFavoriteProgram,
  onOpenProgram
}: ProgramsTabProps) {
  const [filters, setFilters] = useState<ProgramFiltersState>(defaultFilters);
  const [isDesktopFiltersOpen, setIsDesktopFiltersOpen] = useState(false);
  const sourceById = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const options = useMemo<FilterOptions>(
    () => ({
      regions: values(programs.flatMap((program) => program.regions), (a, b) => a.localeCompare(b, 'ru')),
      coverageLevels,
      launchYears: values(programs.map((program) => program.launchYear), (a, b) => b - a),
      statuses: values(programs.map((program) => program.status), (a, b) => a.localeCompare(b, 'ru')),
      topics: values(programs.flatMap((program) => program.topics), (a, b) => a.localeCompare(b, 'ru')),
      supportTypes: values(programs.map((program) => program.supportType), (a, b) => a.localeCompare(b, 'ru')),
      audiences: values(programs.flatMap((program) => program.audience), (a, b) => a.localeCompare(b, 'ru')),
      sources
    }),
    [programs, sources]
  );
  const visible = useMemo(
    () => sortPrograms(filterPrograms(programs, sources, filters), sources, filters.sort, filters.query),
    [filters, programs, sources]
  );

  const updateFilters = (patch: Partial<ProgramFiltersState>) => {
    setFilters((current) => {
      const next = { ...current, ...patch };
      if ('query' in patch) {
        const hasQuery = patch.query?.trim().length !== 0;
        if (hasQuery && current.query.trim().length === 0 && current.sort === 'deadline') next.sort = 'relevance';
        if (!hasQuery && current.sort === 'relevance') next.sort = 'deadline';
      }
      return next;
    });
  };

  const resetFilters = () => setFilters((current) => ({
    ...defaultFilters,
    sort: current.sort === 'relevance' ? 'deadline' : current.sort
  }));

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => ScrollTrigger.refresh());
    return () => window.cancelAnimationFrame(frame);
  }, [filters, visible.length]);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mediaQuery = window.matchMedia('(min-width: 1024px)');
    const updateDesktopState = () => setIsDesktopFiltersOpen(mediaQuery.matches);

    updateDesktopState();
    mediaQuery.addEventListener?.('change', updateDesktopState) ?? mediaQuery.addListener?.(updateDesktopState);
    return () => mediaQuery.removeEventListener?.('change', updateDesktopState) ?? mediaQuery.removeListener?.(updateDesktopState);
  }, []);

  return (
    <div className="page-container" data-page="programs">
      <PageIntro
        eyebrow="Рабочий каталог"
        title="Каталог программ"
        description="Ищите программы по условиям, регионам, срокам и финансированию. Избранное и история просмотра сохраняются локально."
        aside={<p className="count-badge">Найдено: {visible.length}</p>}
      />
      <p role="status" aria-live="polite" className="sr-only">Найдено программ: {visible.length}</p>

      <section className="mt-10">
        <label className="grid gap-1 text-sm font-medium text-graphite">
          Поиск
          <span className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite/55" aria-hidden="true" />
            <input
              value={filters.query}
              onChange={(event) => updateFilters({ query: event.target.value })}
              className="w-full rounded-lg border border-ink/10 bg-white py-2 pl-9 pr-20 text-ink"
              placeholder="Название или описание"
            />
            {filters.query ? <button type="button" onClick={() => updateFilters({ query: '' })} aria-label="Очистить поиск" className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 text-xs font-semibold text-graphite hover:bg-ink/5">Очистить</button> : null}
          </span>
        </label>
        <ProgramFilters filters={filters} options={options} isDesktopOpen={isDesktopFiltersOpen} onChange={updateFilters} onReset={resetFilters} />
      </section>

      <section data-density-grid className="mt-8 grid min-w-0 gap-4 lg:grid-cols-[repeat(2,minmax(0,1fr))]">
        {visible.map((program) => (
          <ProgramCard
            key={program.id}
            program={program}
            source={sourceById.get(program.sourceId) ?? null}
            isFavorite={favoriteProgramIds.includes(program.id)}
            showDataQuality={showDataQuality}
            onToggleFavorite={() => onToggleFavoriteProgram(program.id)}
            onOpen={() => onOpenProgram(program)}
          />
        ))}
      </section>

      {programs.length === 0 ? <div className="mt-8"><EmptyState title="Каталог пока пуст" description="Добавьте программы в seed-данные, чтобы начать поиск." /></div> : null}
      {programs.length > 0 && visible.length === 0 ? <div className="mt-8"><EmptyState title="По вашему запросу ничего не найдено" description="Измените поиск или фильтры, чтобы вернуть результаты из seed-базы. Используйте действие «Сбросить фильтры» выше, чтобы начать заново." /></div> : null}
    </div>
  );
}
