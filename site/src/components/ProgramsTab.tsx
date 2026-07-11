import { ExternalLink, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { filterPrograms, sortPrograms } from '../lib/catalog';
import { formatDeadline, formatMoneyRub, isValidExternalUrl } from '../lib/format';
import type {
  Audience,
  DeadlineFilter,
  ProgramFilters,
  ProgramSort,
  ProgramStatus,
  SupportProgram,
  SupportSource,
  SupportType,
  Topic
} from '../types';
import { EmptyState, Tag } from './ui';

const defaultFilters: ProgramFilters = {
  query: '',
  topic: 'Все тематики',
  supportType: 'Все типы',
  audience: 'Все аудитории',
  status: 'Все статусы',
  deadline: 'all',
  sort: 'deadline'
};

function getActiveFilterLabels(filters: ProgramFilters) {
  const labels: string[] = [];
  if (filters.query.trim()) labels.push(`Поиск: ${filters.query.trim()}`);
  if (filters.topic !== 'Все тематики') labels.push(`Тематика: ${filters.topic}`);
  if (filters.supportType !== 'Все типы') labels.push(`Тип: ${filters.supportType}`);
  if (filters.audience !== 'Все аудитории') labels.push(`Аудитория: ${filters.audience}`);
  if (filters.status !== 'Все статусы') labels.push(`Статус: ${filters.status}`);
  if (filters.deadline !== 'all') {
    const labelsByDeadline: Record<DeadlineFilter, string> = {
      all: 'Все дедлайны',
      withDeadline: 'С дедлайном',
      withoutDeadline: 'Без дедлайна',
      next30: '30 дней',
      next90: '90 дней'
    };
    labels.push(`Дедлайн: ${labelsByDeadline[filters.deadline]}`);
  }
  return labels;
}

function hasActiveFilters(filters: ProgramFilters) {
  return getActiveFilterLabels(filters).length > 0;
}

export function ProgramsTab({
  sources,
  programs,
  onOpenProgram
}: {
  sources: readonly SupportSource[];
  programs: readonly SupportProgram[];
  onOpenProgram: (program: SupportProgram) => void;
}) {
  const [filters, setFilters] = useState<ProgramFilters>(defaultFilters);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [isDesktopFiltersOpen, setIsDesktopFiltersOpen] = useState(false);

  const sourceById = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const topics = useMemo(
    () => Array.from(new Set(programs.flatMap((program) => program.topics))).sort((a, b) => a.localeCompare(b, 'ru')),
    [programs]
  );
  const supportTypes = useMemo(
    () => Array.from(new Set(programs.map((program) => program.supportType))).sort((a, b) => a.localeCompare(b, 'ru')),
    [programs]
  );
  const audiences = useMemo(
    () => Array.from(new Set(programs.flatMap((program) => program.audience))).sort((a, b) => a.localeCompare(b, 'ru')),
    [programs]
  );
  const statuses = useMemo(
    () => Array.from(new Set(programs.map((program) => program.status))).sort((a, b) => a.localeCompare(b, 'ru')),
    [programs]
  );

  const visible = useMemo(() => sortPrograms(filterPrograms(programs, filters), sources, filters.sort), [filters, programs, sources]);
  const activeFilterLabels = getActiveFilterLabels(filters);
  const filtersAreActive = hasActiveFilters(filters);
  const resetFilters = () => setFilters((current) => ({ ...defaultFilters, sort: current.sort }));

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => ScrollTrigger.refresh());

    return () => window.cancelAnimationFrame(frame);
  }, [filters, visible.length]);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;

    const mediaQuery = window.matchMedia('(min-width: 1024px)');
    const updateDesktopState = () => setIsDesktopFiltersOpen(mediaQuery.matches);

    updateDesktopState();
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', updateDesktopState);
    } else {
      mediaQuery.addListener?.(updateDesktopState);
    }

    return () => {
      if (mediaQuery.removeEventListener) {
        mediaQuery.removeEventListener('change', updateDesktopState);
      } else {
        mediaQuery.removeListener?.(updateDesktopState);
      }
    };
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-4xl font-semibold">Каталог программ</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-graphite">
            Поиск, фильтры и сортировка работают в браузере по локальным seed-данным.
          </p>
        </div>
        <p className="rounded-full border border-ink/10 bg-white/70 px-4 py-2 text-sm font-semibold text-graphite">
          Найдено: {visible.length}
        </p>
        <p role="status" aria-live="polite" className="sr-only">
          Найдено программ: {visible.length}
        </p>
      </div>

      <section className="mt-8">
        <label className="grid gap-1 text-sm font-medium text-graphite">
          Поиск
          <span className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite/55"
              aria-hidden="true"
            />
            <input
              value={filters.query}
              onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
              className="w-full rounded-lg border border-ink/10 bg-white py-2 pl-9 pr-20 text-ink"
              placeholder="Название или описание"
            />
            {filters.query ? (
              <button
                type="button"
                onClick={() => setFilters((current) => ({ ...current, query: '' }))}
                aria-label="Очистить поиск"
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 text-xs font-semibold text-graphite hover:bg-ink/5"
              >
                Очистить
              </button>
            ) : null}
          </span>
        </label>

        <details
          open={isDesktopFiltersOpen || filtersOpen}
          onToggle={(event) => {
            if (!isDesktopFiltersOpen) setFiltersOpen(event.currentTarget.open);
          }}
          className="mt-3 rounded-lg border border-ink/10 bg-white/70 p-4 shadow-sm"
        >
          <summary className="cursor-pointer text-sm font-semibold text-ink lg:hidden">Фильтры</summary>
          <div className="mt-4 grid gap-3 lg:mt-0 lg:grid-cols-[repeat(5,1fr)]">
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Тематика
              <select
                value={filters.topic}
                onChange={(event) => setFilters((current) => ({ ...current, topic: event.target.value as Topic | 'Все тематики' }))}
                className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
              >
                <option>Все тематики</option>
                {topics.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Тип поддержки
              <select
                value={filters.supportType}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, supportType: event.target.value as SupportType | 'Все типы' }))
                }
                className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
              >
                <option>Все типы</option>
                {supportTypes.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Аудитория
              <select
                value={filters.audience}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, audience: event.target.value as Audience | 'Все аудитории' }))
                }
                className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
              >
                <option>Все аудитории</option>
                {audiences.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Статус
              <select
                value={filters.status}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, status: event.target.value as ProgramStatus | 'Все статусы' }))
                }
                className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
              >
                <option>Все статусы</option>
                {statuses.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-graphite">
              Сортировка
              <select
                value={filters.sort}
                onChange={(event) => setFilters((current) => ({ ...current, sort: event.target.value as ProgramSort }))}
                className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
              >
                <option value="deadline">Ближайший дедлайн</option>
                <option value="funding">Максимальная сумма</option>
                <option value="newest">Новизна</option>
                <option value="source">Источник</option>
              </select>
            </label>
          </div>
          <section role="group" aria-label="Дедлайн" className="mt-3 flex flex-wrap gap-3">
            {[
              ['all', 'Все дедлайны'],
              ['withDeadline', 'С дедлайном'],
              ['withoutDeadline', 'Без дедлайна'],
              ['next30', '30 дней'],
              ['next90', '90 дней']
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={filters.deadline === value}
                onClick={() => setFilters((current) => ({ ...current, deadline: value as DeadlineFilter }))}
                className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
                  filters.deadline === value ? 'border-ink bg-ink text-white' : 'border-ink/10 bg-white/70 text-graphite hover:bg-white'
                }`}
              >
                {label}
              </button>
            ))}
          </section>
        </details>

        <div role="group" aria-label="Активные фильтры" className="mt-4 flex flex-wrap items-center gap-2">
          {activeFilterLabels.map((label) => (
            <span key={label} className="rounded-full border border-cobalt/20 bg-cobalt/10 px-3 py-1 text-xs font-semibold text-cobalt">
              {label}
            </span>
          ))}
          {filtersAreActive ? (
            <button type="button" onClick={resetFilters} className="text-sm font-semibold text-cobalt">
              Сбросить фильтры
            </button>
          ) : null}
        </div>
      </section>

      <section data-density-grid className="mt-8 grid gap-4 lg:grid-cols-2">
        {visible.map((program) => {
          const source = sourceById.get(program.sourceId);
          return (
            <article
              key={program.id}
              data-motion-card
              data-density-card
              className="group overflow-hidden rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm transition hover:-translate-y-1"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Tag>{program.status}</Tag>
                <Tag>{formatDeadline(program.deadline)}</Tag>
                <Tag>{program.supportType}</Tag>
              </div>
              <h2 className="mt-5 text-xl font-semibold">{program.title}</h2>
              <p className="mt-1 text-sm font-medium text-cobalt">{source?.name ?? 'Источник не найден'}</p>
              <p className="mt-3 text-sm leading-6 text-graphite">{program.description}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {program.topics.map((topic) => (
                  <Tag key={topic}>{topic}</Tag>
                ))}
              </div>
              <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-sm font-semibold">{formatMoneyRub(program.fundingAmountRub)}</span>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <button
                    type="button"
                    onClick={() => onOpenProgram(program)}
                    aria-label={`Подробнее о программе ${program.title}`}
                    className="inline-flex min-h-11 items-center justify-center rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-ink/85 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
                  >
                    Подробнее
                  </button>
                  {isValidExternalUrl(program.sourceUrl) ? (
                    <a
                      href={program.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/10 px-4 py-2 text-sm font-semibold text-graphite transition hover:bg-white"
                    >
                      Первоисточник <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
                    </a>
                  ) : null}
                </div>
              </div>
            </article>
          );
        })}
      </section>

      {visible.length === 0 ? (
        <div className="mt-8">
          <EmptyState title="Программы не найдены" description="Измените поиск или фильтры, чтобы вернуть результаты из seed-базы.">
            {filtersAreActive ? (
              <button type="button" onClick={resetFilters} className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white">
                Сбросить фильтры
              </button>
            ) : null}
            {filters.query ? (
              <button
                type="button"
                onClick={() => setFilters((current) => ({ ...current, query: '' }))}
                className="rounded-lg border border-ink/10 px-4 py-2 text-sm font-semibold text-ink"
              >
                Очистить поиск
              </button>
            ) : null}
          </EmptyState>
        </div>
      ) : null}

    </div>
  );
}
