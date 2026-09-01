import { ExternalLink } from 'lucide-react';
import type { SourcePage } from '../data-access/usePublicCatalog';
import { isValidExternalUrl } from '../lib/format';
import { EmptyState, PageIntro, Tag } from './ui';

export function ApiSourcesTab({
  page,
  loading,
  error,
  onRetry
}: {
  page: SourcePage | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <div className="page-container" data-page="sources" data-data-mode="api">
      <PageIntro
        eyebrow="Публичные источники"
        title="Источники программ"
        description="Показываются только источники, связанные с опубликованными программами."
        aside={<p className="count-badge">Найдено: {page?.total ?? 0}</p>}
      />
      {loading && !page ? <p role="status" className="mt-8 text-sm text-graphite">Загружаем источники…</p> : null}
      {error ? (
        <div className="mt-8">
          <EmptyState title="Источники временно недоступны" description={error}>
            <button type="button" onClick={onRetry} className="button-secondary">Повторить</button>
          </EmptyState>
        </div>
      ) : null}
      {!error && page && page.items.length === 0 ? (
        <div className="mt-8"><EmptyState title="Источников пока нет" description="В базе нет источников опубликованных программ." /></div>
      ) : null}
      {!error && page && page.items.length > 0 ? (
        <section data-density-grid className="mt-8 grid min-w-0 gap-4 md:grid-cols-2">
          {page.items.map((source) => (
            <article key={source.id} aria-label={source.name} data-density-card className="flex h-full flex-col rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <h2 className="break-words text-xl font-semibold">{source.name}</h2>
                <Tag>{source.publishedProgramCount ?? 0} программ</Tag>
              </div>
              <p className="mt-4 text-sm leading-6 text-graphite">Дополнительное описание источника не входит в публичный контракт каталога.</p>
              <div className="mt-auto pt-5">
                {isValidExternalUrl(source.canonicalUrl) ? (
                  <a href={source.canonicalUrl} target="_blank" rel="noreferrer" className="inline-flex items-center text-sm font-semibold text-cobalt">
                    Открыть сайт источника <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
                  </a>
                ) : null}
              </div>
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}
