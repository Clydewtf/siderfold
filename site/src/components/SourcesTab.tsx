import { Fragment, useEffect, useMemo, useState } from 'react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { buildAnalytics, type SourceAnalyticsItem } from '../lib/analytics';
import { filterSources, getProgramsBySource } from '../lib/catalog';
import type { SourceFilters as SourceFiltersType, SupportProgram, SupportSource } from '../types';
import { SourceCard } from './SourceCard';
import { SourceDetails } from './SourceDetails';
import { SourceFilters } from './SourceFilters';
import { EmptyState } from './ui';

const defaultSourceFilters: SourceFiltersType = {
  type: 'Все типы',
  region: 'Все регионы',
  coverageLevel: 'Все уровни',
  topic: 'Все тематики'
};

export type SourcesTabProps = {
  sources: readonly SupportSource[];
  programs: readonly SupportProgram[];
  favoriteSourceIds: readonly string[];
  showDataQuality: boolean;
  onToggleFavoriteSource: (sourceId: string) => void;
  onOpenProgram: (program: SupportProgram) => void;
};

export function SourcesTab({
  sources,
  programs,
  favoriteSourceIds,
  showDataQuality,
  onToggleFavoriteSource,
  onOpenProgram
}: SourcesTabProps) {
  const [filters, setFilters] = useState<SourceFiltersType>(defaultSourceFilters);
  const [selectedSourceId, setSelectedSourceId] = useState(sources[0]?.id ?? '');
  const analytics = useMemo(() => buildAnalytics(sources, programs), [sources, programs]);
  const metricsBySourceId = useMemo(
    () => new Map(analytics.sources.byProgramCount.map((item) => [item.sourceId, item])),
    [analytics]
  );
  const filtered = useMemo(() => filterSources(sources, filters), [sources, filters]);
  const selected = filtered.find((source) => source.id === selectedSourceId) ?? filtered[0] ?? null;
  const relatedPrograms = useMemo(
    () => (selected ? getProgramsBySource(programs, selected.id) : []),
    [programs, selected]
  );
  const selectedAnnouncement = selected ? `Выбран источник: ${selected.name}` : 'Источник не выбран';

  const updateFilters = (patch: Partial<SourceFiltersType>) => {
    setFilters((current) => ({ ...current, ...patch }));
  };

  const resetFilters = () => setFilters(defaultSourceFilters);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => ScrollTrigger.refresh());

    return () => window.cancelAnimationFrame(frame);
  }, [filters, filtered.length]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <p role="status" aria-live="polite" className="sr-only">
        {selectedAnnouncement}
      </p>
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="text-4xl font-semibold">Источники программ</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-graphite">
            Фонды, платформы, университеты и акселераторы, из которых формируется тестовая база возможностей.
          </p>
        </div>
        <SourceFilters filters={filters} sources={sources} onChange={updateFilters} onReset={resetFilters} />
      </div>

      <div className="mt-10 grid gap-6 lg:grid-cols-[1fr_420px] lg:items-start">
        <div data-density-grid className="grid gap-4 md:grid-cols-2">
          {filtered.map((source) => {
            const metric: SourceAnalyticsItem = metricsBySourceId.get(source.id) ?? {
              sourceId: source.id,
              sourceName: source.name,
              sourceType: source.type,
              coverageLevel: source.coverageLevel,
              programCount: 0,
              activeProgramCount: 0,
              totalFundingRub: 0,
              averageFundingRub: null,
              dataCompletenessScore: null,
              incompleteProgramCount: 0
            };
            const isSelected = selected?.id === source.id;

            return (
              <Fragment key={source.id}>
                <SourceCard
                  source={source}
                  metrics={metric}
                  totalPrograms={analytics.totalPrograms}
                  selected={isSelected}
                  isFavorite={favoriteSourceIds.includes(source.id)}
                  showDataQuality={showDataQuality}
                  onSelect={() => setSelectedSourceId(source.id)}
                  onToggleFavorite={() => onToggleFavoriteSource(source.id)}
                />
                {isSelected && selected ? (
                  <div className="md:col-span-2 lg:hidden">
                    <SourceDetails
                      source={selected}
                      metrics={metric}
                      totalPrograms={analytics.totalPrograms}
                      relatedPrograms={relatedPrograms}
                      showDataQuality={showDataQuality}
                      onOpenProgram={onOpenProgram}
                    />
                  </div>
                ) : null}
              </Fragment>
            );
          })}
          {sources.length === 0 ? (
            <EmptyState
              title="База источников пока пуста"
              description="Добавьте источники в seed-данные, чтобы начать работу с каталогом."
            />
          ) : null}
          {sources.length > 0 && filtered.length === 0 ? (
            <EmptyState
              title="Источники по этим фильтрам не найдены"
              description="Измените фильтры источников или сбросьте их, чтобы вернуть карточки из seed-базы."
            />
          ) : null}
        </div>

        {selected ? (
          <aside data-testid="desktop-source-details-column" className="hidden lg:block lg:w-[420px] lg:self-stretch">
            <div
              data-testid="desktop-source-details"
              className="lg:sticky lg:top-28 lg:max-h-[calc(100vh-8rem)] lg:w-[420px] lg:overflow-y-auto lg:rounded-lg"
            >
              <SourceDetails
                source={selected}
                metrics={metricsBySourceId.get(selected.id) ?? {
                  sourceId: selected.id,
                  sourceName: selected.name,
                  sourceType: selected.type,
                  coverageLevel: selected.coverageLevel,
                  programCount: 0,
                  activeProgramCount: 0,
                  totalFundingRub: 0,
                  averageFundingRub: null,
                  dataCompletenessScore: null,
                  incompleteProgramCount: 0
                }}
                totalPrograms={analytics.totalPrograms}
                relatedPrograms={relatedPrograms}
                showDataQuality={showDataQuality}
                onOpenProgram={onOpenProgram}
              />
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
