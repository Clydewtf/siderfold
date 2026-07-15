import { useMemo, useState } from 'react';
import {
  buildAnalytics,
  defaultAnalyticsFilters,
  type AnalyticsFilters
} from '../lib/analytics';
import type { SupportProgram, SupportSource } from '../types';
import { AnalyticsFiltersPanel, type AnalyticsFilterOptions } from './AnalyticsFilters';
import { AnalyticsFinanceRegions } from './AnalyticsFinanceRegions';
import { AnalyticsGapsForecast } from './AnalyticsGapsForecast';
import { AnalyticsOverview } from './AnalyticsOverview';
import { AnalyticsSourcesTopics } from './AnalyticsSourcesTopics';
import { AnalyticsTimeQuality } from './AnalyticsTimeQuality';
import { DemoNotice, EmptyState, PageIntro } from './ui';

export type AnalyticsTabProps = {
  sources: readonly SupportSource[];
  programs: readonly SupportProgram[];
  exportNotice: string | null;
  onRequestExport: () => void;
};

function unique<T extends string>(values: readonly T[]): T[] {
  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, 'ru'));
}

export function AnalyticsTab({ sources, programs, exportNotice, onRequestExport }: AnalyticsTabProps) {
  const [filters, setFilters] = useState<AnalyticsFilters>(defaultAnalyticsFilters);
  const analytics = useMemo(() => buildAnalytics(sources, programs, filters), [sources, programs, filters]);
  const options = useMemo<AnalyticsFilterOptions>(() => ({
    regions: unique(programs.flatMap((program) => program.regions)),
    years: Array.from(new Set(programs.flatMap((program) => [program.launchYear, ...program.history.map((point) => point.year)]))).sort((a, b) => b - a),
    coverageLevels: ['federal', 'regional', 'municipal', 'private'],
    sources,
    supportTypes: unique(programs.map((program) => program.supportType)),
    topics: unique(programs.flatMap((program) => program.topics)),
    audiences: unique(programs.flatMap((program) => program.audience)),
    statuses: unique(programs.map((program) => program.status))
  }), [programs, sources]);
  const updateFilters = (patch: Partial<AnalyticsFilters>) => setFilters((current) => ({ ...current, ...patch }));
  const resetFilters = () => setFilters(defaultAnalyticsFilters);

  return (
    <div className="page-container" data-page="analytics">
      <PageIntro
        eyebrow="Мониторинг мер поддержки"
        title="Аналитика мер поддержки"
        description="Презентационный обзор и фильтруемая BI-зона используют те же программы и источники, что каталог Siderfold."
        aside={<DemoNotice>Демо-режим: выводы рассчитаны по текущей seed-базе.</DemoNotice>}
      />
      {programs.length === 0 ? <EmptyState title="Аналитическая база пока пуста" description="Добавьте программы в seed-данные, чтобы построить мониторинг." /> : <AnalyticsOverview analytics={analytics} />}
      <section aria-labelledby="bi-monitoring-title" className="mt-16">
        <h2 id="bi-monitoring-title" className="text-3xl font-semibold">BI-мониторинг</h2>
        <p className="mt-2 text-sm text-graphite">Все блоки ниже перестраиваются по выбранному срезу.</p>
        <div className="mt-5"><AnalyticsFiltersPanel filters={filters} options={options} onChange={updateFilters} onReset={resetFilters} /></div>
        <p className="mt-4 text-sm font-semibold">Найдено программ: {analytics.filteredPrograms}</p>
        <p role="status" aria-live="polite" className="sr-only">Найдено программ: {analytics.filteredPrograms}</p>
      </section>
      {programs.length > 0 && analytics.filteredPrograms === 0 ? <div className="mt-8"><EmptyState title="В выбранном срезе нет программ" description="Измените или сбросьте BI-фильтры; controls остаются доступными выше." /></div> : null}
      <AnalyticsFinanceRegions finance={analytics.finance} regional={analytics.regional} />
      <AnalyticsSourcesTopics sources={analytics.sources} topics={analytics.topics} totalPrograms={analytics.filteredPrograms} />
      <AnalyticsTimeQuality temporal={analytics.temporal} dataQuality={analytics.dataQuality} filteredPrograms={analytics.filteredPrograms} />
      <AnalyticsGapsForecast supportGaps={analytics.supportGaps} forecast={analytics.forecast} exportNotice={exportNotice} onRequestExport={onRequestExport} />
    </div>
  );
}
