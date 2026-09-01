import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import type { ProgramQuery } from '../data-access/catalogApi';
import type { PublicCatalogFilters, PublicProgram } from '../data-access/catalogMapper';
import type { CatalogPage } from '../data-access/usePublicCatalog';
import { ApiProgramCard } from './ApiProgramCard';
import { EmptyState, PageIntro } from './ui';

type ApiFilterState = {
  query: string;
  sourceId: string;
  region: string;
  theme: string;
  fundingKind: string;
  deadlineFrom: string;
  deadlineTo: string;
  sort: ProgramQuery['sort'];
  order: ProgramQuery['order'];
  page: number;
};

const defaultFilters: ApiFilterState = {
  query: '',
  sourceId: '',
  region: '',
  theme: '',
  fundingKind: '',
  deadlineFrom: '',
  deadlineTo: '',
  sort: 'published_at',
  order: 'desc',
  page: 1
};

const fundingLabels: Record<string, string> = {
  exact: 'Точная сумма',
  minimum: 'Минимальная сумма',
  maximum: 'Максимальная сумма',
  range: 'Диапазон',
  unknown: 'Неизвестно',
  not_stated: 'Не указано'
};

function toQuery(filters: ApiFilterState): ProgramQuery {
  return {
    page: filters.page,
    pageSize: 20,
    sort: filters.sort,
    order: filters.order,
    query: filters.query || undefined,
    sourceId: filters.sourceId || undefined,
    theme: filters.theme || undefined,
    geography: filters.region || undefined,
    fundingKind: filters.fundingKind as ProgramQuery['fundingKind'] || undefined,
    deadlineFrom: filters.deadlineFrom || undefined,
    deadlineTo: filters.deadlineTo || undefined
  };
}

function hasActiveFilter(filters: ApiFilterState): boolean {
  return Boolean(
    filters.query || filters.sourceId || filters.region || filters.theme || filters.fundingKind ||
    filters.deadlineFrom || filters.deadlineTo
  );
}

export function ApiProgramsTab({
  page,
  filters,
  loading,
  metadataLoading,
  error,
  metadataError,
  favoriteProgramIds,
  onQueryChange,
  onOpenProgram,
  onToggleFavoriteProgram,
  onRetry
}: {
  page: CatalogPage | null;
  filters: PublicCatalogFilters | null;
  loading: boolean;
  metadataLoading: boolean;
  error: string | null;
  metadataError: string | null;
  favoriteProgramIds: readonly string[];
  onQueryChange: (query: ProgramQuery) => void;
  onOpenProgram: (program: PublicProgram) => void;
  onToggleFavoriteProgram: (programId: string) => void;
  onRetry: () => void;
}) {
  const [localFilters, setLocalFilters] = useState<ApiFilterState>(defaultFilters);

  useEffect(() => {
    const timer = window.setTimeout(() => onQueryChange(toQuery(localFilters)), 250);
    return () => window.clearTimeout(timer);
  }, [localFilters, onQueryChange]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => ScrollTrigger.refresh());
    return () => window.cancelAnimationFrame(frame);
  }, [localFilters, page?.items.length]);

  const totalPages = Math.max(1, Math.ceil((page?.total ?? 0) / (page?.pageSize ?? 20)));
  const update = (patch: Partial<ApiFilterState>) => {
    setLocalFilters((current) => ({ ...current, ...patch, page: 'page' in patch ? patch.page ?? 1 : 1 }));
  };
  const reset = () => setLocalFilters(defaultFilters);
  const sourceOptions = filters?.sources ?? [];
  const regionOptions = filters?.regions ?? [];
  const themeOptions = filters?.themes ?? [];
  const fundingOptions = filters?.fundingKinds ?? [];
  const items = page?.items ?? [];
  const emptyDescription = hasActiveFilter(localFilters)
    ? 'Измените параметры поиска или сбросьте фильтры.'
    : 'В базе пока нет опубликованных программ.';

  return (
    <div className="page-container" data-page="programs" data-data-mode="api">
      <PageIntro
        eyebrow="Публичный каталог"
        title="Каталог программ"
        description="Здесь отображаются только опубликованные программы из public API. Внутренние данные проверки не показываются."
        aside={<p className="count-badge">Найдено: {page?.total ?? 0}</p>}
      />
      <p role="status" aria-live="polite" className="sr-only">Найдено программ: {page?.total ?? 0}</p>

      <section className="mt-10">
        <label className="grid gap-1 text-sm font-medium text-graphite">
          Поиск
          <span className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite/55" aria-hidden="true" />
            <input
              value={localFilters.query}
              onChange={(event) => update({ query: event.target.value })}
              className="w-full rounded-lg border border-ink/10 bg-white py-2 pl-9 pr-20 text-ink"
              placeholder="Название программы"
            />
            {localFilters.query ? (
              <button type="button" onClick={() => update({ query: '' })} aria-label="Очистить поиск" className="absolute right-2 top-1/2 rounded-md px-2 py-1 text-xs font-semibold text-graphite hover:bg-ink/5">
                Очистить
              </button>
            ) : null}
          </span>
        </label>
        <details open className="mt-3 rounded-lg border border-ink/10 bg-white/70 p-4 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-ink">Фильтры</summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Источник
              <select value={localFilters.sourceId} onChange={(event) => update({ sourceId: event.target.value })} disabled={metadataLoading} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink">
                <option value="">Все источники</option>
                {sourceOptions.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              География
              <select value={localFilters.region} onChange={(event) => update({ region: event.target.value })} disabled={metadataLoading} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink">
                <option value="">Все регионы</option>
                {regionOptions.map((region) => <option key={region.slug} value={region.slug}>{region.name}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Тематика
              <select value={localFilters.theme} onChange={(event) => update({ theme: event.target.value })} disabled={metadataLoading} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink">
                <option value="">Все тематики</option>
                {themeOptions.map((theme) => <option key={theme.slug} value={theme.slug}>{theme.name}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Тип финансирования
              <select value={localFilters.fundingKind} onChange={(event) => update({ fundingKind: event.target.value })} disabled={metadataLoading} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink">
                <option value="">Любой тип</option>
                {fundingOptions.map((kind) => <option key={kind} value={kind}>{fundingLabels[kind] ?? kind}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Дедлайн от
              <input type="date" value={localFilters.deadlineFrom} onChange={(event) => update({ deadlineFrom: event.target.value })} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink" />
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Дедлайн до
              <input type="date" value={localFilters.deadlineTo} onChange={(event) => update({ deadlineTo: event.target.value })} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink" />
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Сортировка
              <select value={localFilters.sort} onChange={(event) => update({ sort: event.target.value as ApiFilterState['sort'] })} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink">
                <option value="published_at">Дата публикации</option>
                <option value="updated_at">Дата обновления</option>
                <option value="deadline">Дедлайн</option>
                <option value="title">Название</option>
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Порядок
              <select value={localFilters.order} onChange={(event) => update({ order: event.target.value as ApiFilterState['order'] })} className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink">
                <option value="desc">По убыванию</option>
                <option value="asc">По возрастанию</option>
              </select>
            </label>
          </div>
          {metadataError ? <p role="status" className="mt-3 text-sm text-graphite">{metadataError}</p> : null}
          {hasActiveFilter(localFilters) ? <button type="button" onClick={reset} className="mt-4 text-sm font-semibold text-cobalt">Сбросить фильтры</button> : null}
        </details>
      </section>

      {loading && !page ? <p role="status" className="mt-8 text-sm text-graphite">Загружаем каталог…</p> : null}
      {error ? (
        <div className="mt-8">
          <EmptyState title="Каталог временно недоступен" description={error}>
            <button type="button" onClick={onRetry} className="button-secondary">Повторить</button>
          </EmptyState>
        </div>
      ) : null}
      {!error && page && items.length === 0 ? (
        <div className="mt-8"><EmptyState title={hasActiveFilter(localFilters) ? 'Ничего не найдено' : 'Каталог пока пуст'} description={emptyDescription} /></div>
      ) : null}
      {!error && items.length > 0 ? (
        <>
          <section data-density-grid className="mt-8 grid min-w-0 gap-4 lg:grid-cols-[repeat(2,minmax(0,1fr))]">
            {items.map((program) => (
              <ApiProgramCard
                key={program.id}
                program={program}
                isFavorite={favoriteProgramIds.includes(program.id)}
                onToggleFavorite={() => onToggleFavoriteProgram(program.id)}
                onOpen={() => onOpenProgram(program)}
              />
            ))}
          </section>
          <nav aria-label="Пагинация каталога" className="mt-8 flex items-center justify-center gap-3">
            <button type="button" disabled={localFilters.page <= 1 || loading} onClick={() => update({ page: localFilters.page - 1 })} className="button-secondary disabled:cursor-not-allowed disabled:opacity-50">Назад</button>
            <span className="text-sm text-graphite">Страница {localFilters.page} из {totalPages}</span>
            <button type="button" disabled={localFilters.page >= totalPages || loading} onClick={() => update({ page: localFilters.page + 1 })} className="button-secondary disabled:cursor-not-allowed disabled:opacity-50">Вперёд</button>
          </nav>
        </>
      ) : null}
    </div>
  );
}
