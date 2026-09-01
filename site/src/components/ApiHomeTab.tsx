import { ArrowRight, ExternalLink } from 'lucide-react';
import type { PublicProgram } from '../data-access/catalogMapper';
import { formatDeadline, isValidExternalUrl } from '../lib/format';
import { EmptyState, IconButton, PageIntro, Tag } from './ui';

export function ApiHomeTab({
  programs,
  programTotal,
  sourceTotal,
  loading,
  error,
  metadataError,
  onOpenPrograms,
  onOpenSources,
  onOpenProgram,
  onRetry
}: {
  programs: readonly PublicProgram[];
  programTotal: number;
  sourceTotal: number;
  loading: boolean;
  error: string | null;
  metadataError: string | null;
  onOpenPrograms: () => void;
  onOpenSources: () => void;
  onOpenProgram: (program: PublicProgram) => void;
  onRetry: () => void;
}) {
  return (
    <div className="page-container" data-page="home" data-data-mode="api">
      <section className="grid items-center gap-8 py-8 sm:py-10 lg:min-h-[62vh] lg:grid-cols-[1.12fr_0.88fr] lg:gap-10 lg:py-20">
        <div className="max-w-6xl">
          <p className="eyebrow">Единый публичный каталог</p>
          <h1 className="home-title">Программы поддержки — в одном рабочем пространстве</h1>
          <p className="home-lead">Каталог показывает опубликованные записи из подключённой базы и сохраняет ссылку на первоисточник.</p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <IconButton onClick={onOpenPrograms}>Открыть каталог <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" /></IconButton>
            <button type="button" onClick={onOpenSources} className="button-secondary">Смотреть источники</button>
          </div>
        </div>
        <aside aria-label="Состояние базы" data-motion-media className="demo-status grain-overlay overflow-hidden shadow-panel">
          <p className="eyebrow">Состояние базы</p>
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            <div><p className="text-sm text-graphite">Программ</p><p className="mt-2 text-3xl font-semibold text-ink">{programTotal}</p></div>
            <div><p className="text-sm text-graphite">Источников</p><p className="mt-2 text-3xl font-semibold text-ink">{sourceTotal}</p></div>
          </div>
          <p className="mt-8 border-t border-cobalt/20 pt-4 text-sm font-semibold text-graphite">Данные public API</p>
          {metadataError ? <p role="status" className="mt-3 text-sm text-graphite">Источники и фильтры временно недоступны.</p> : null}
        </aside>
      </section>

      <section className="py-12">
        <div className="flex items-end justify-between gap-6">
          <PageIntro eyebrow="Опубликованные записи" title="Последние программы" description="Показана текущая страница каталога из публичного API." />
        </div>
        <div data-density-grid className="mt-8 grid gap-4 md:grid-cols-2">
          {programs.slice(0, 4).map((program) => (
            <article key={program.id} data-density-card className="rounded-lg border border-ink/10 bg-white/75 p-5 shadow-sm">
              <div className="flex flex-wrap gap-2"><Tag>Опубликована</Tag><Tag>{formatDeadline(program.deadline)}</Tag></div>
              <h2 className="mt-5 text-xl font-semibold">{program.title}</h2>
              <p className="mt-2 text-sm font-medium text-cobalt">{program.primarySource.source.name}</p>
              <div className="mt-5 flex items-center justify-between gap-4">
                <span className="text-sm font-semibold">{program.funding?.label ?? 'Сумма не указана'}</span>
                <button type="button" aria-label={`Подробнее о программе ${program.title}`} onClick={() => onOpenProgram(program)} className="inline-flex items-center text-sm font-semibold text-cobalt">
                  Подробнее <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
                </button>
              </div>
              {isValidExternalUrl(program.primarySource.sourceUrl) ? <span className="sr-only">{program.primarySource.sourceUrl}</span> : null}
            </article>
          ))}
        </div>
      </section>
      {loading && programs.length === 0 ? <p role="status" className="pb-20 text-sm text-graphite">Загружаем каталог…</p> : null}
      {error ? (
        <div className="pb-20">
          <EmptyState title="Каталог временно недоступен" description={error}>
            <button type="button" onClick={onRetry} className="button-secondary">Повторить</button>
          </EmptyState>
        </div>
      ) : null}
      {!loading && !error && programs.length === 0 ? <p className="pb-20 text-sm text-graphite">Опубликованных программ пока нет.</p> : null}
    </div>
  );
}
