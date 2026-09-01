import { ExternalLink, X } from 'lucide-react';
import { useEffect, useRef, type KeyboardEvent } from 'react';
import { formatDeadline, isValidExternalUrl } from '../lib/format';
import type { PublicProgram } from '../data-access/catalogMapper';
import { FavoriteToggle } from './FavoriteToggle';
import { EmptyState, Tag } from './ui';

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

function PublicDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-ink/10 bg-white/70 p-4">
      <h3 className="text-sm font-semibold text-graphite">{label}</h3>
      <p className="mt-2 break-words text-sm text-ink">{value}</p>
    </div>
  );
}

export function ApiProgramDrawer({
  program,
  loading,
  error,
  isFavorite,
  onToggleFavorite,
  onRetry,
  onClose
}: {
  program: PublicProgram | null;
  loading: boolean;
  error: string | null;
  isFavorite: boolean;
  onToggleFavorite: () => void;
  onRetry: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();

    return () => {
      if (openerRef.current && document.contains(openerRef.current)) openerRef.current.focus();
    };
  }, []);

  function getFocusableElements() {
    return Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;

    const elements = getFocusableElements();
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (!first || !last) {
      event.preventDefault();
      dialogRef.current?.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      data-testid="program-drawer-overlay"
      className="program-drawer-overlay fixed inset-0 z-50 flex justify-end p-3 backdrop-blur-sm"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={program?.title ?? 'Карточка программы'}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className="h-full w-full max-w-2xl overflow-y-auto rounded-lg bg-paper p-6 shadow-panel"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-cobalt">{program?.primarySource.source.name ?? 'Public API'}</p>
            <h2 className="mt-2 break-words text-3xl font-semibold text-ink">
              {program?.title ?? 'Карточка программы'}
            </h2>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {program ? <FavoriteToggle itemName={program.title} isFavorite={isFavorite} onToggle={onToggleFavorite} /> : null}
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="Закрыть детали"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-ink text-white"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
        </div>

        {loading ? <p role="status" className="mt-8 text-sm text-graphite">Загружаем карточку программы…</p> : null}
        {error ? (
          <div className="mt-8">
            <EmptyState title="Карточка временно недоступна" description={error}>
              <button type="button" onClick={onRetry} className="button-secondary">Повторить</button>
            </EmptyState>
          </div>
        ) : null}
        {program && !loading && !error ? (
          <>
            <div className="mt-5 flex flex-wrap gap-2">
              <Tag>Опубликована</Tag>
              <Tag>{formatDeadline(program.deadline)}</Tag>
              <Tag>{program.funding?.label ?? 'Сумма не указана'}</Tag>
            </div>

            <p className="mt-6 text-base leading-7 text-graphite">Описание не опубликовано через этот каталог.</p>

            <section aria-labelledby="public-program-overview" className="mt-8 grid gap-4 sm:grid-cols-2">
              <h3 id="public-program-overview" className="sr-only">Основные параметры</h3>
              <PublicDetail label="Обновлено" value={formatDeadline(program.updatedAt.slice(0, 10))} />
              <PublicDetail label="Дата публикации" value={formatDeadline(program.publishedAt.slice(0, 10))} />
              <PublicDetail label="Регионы" value={program.regions.length > 0 ? program.regions.join(', ') : 'Не указаны'} />
              <PublicDetail label="Тематики" value={program.themes.length > 0 ? program.themes.join(', ') : 'Не указаны'} />
            </section>

            <section className="mt-8">
              <h3 className="text-lg font-semibold">Финансирование</h3>
              <p className="mt-3 text-sm text-graphite">{program.funding?.label ?? 'Сумма не указана'}</p>
            </section>

            <section className="mt-8">
              <h3 className="text-lg font-semibold">Источники</h3>
              <div className="mt-3 space-y-3">
                {program.sources.map((source) => (
                  <div key={`${source.source.id}:${source.sourceUrl}`} className="rounded-lg border border-ink/10 bg-white/70 p-4">
                    <p className="font-semibold text-ink">{source.source.name}</p>
                    <p className="mt-1 text-sm text-graphite">Наблюдалось {formatDeadline(source.observedAt.slice(0, 10))}</p>
                    {isValidExternalUrl(source.sourceUrl) ? (
                      <a
                        href={source.sourceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 inline-flex items-center text-sm font-semibold text-cobalt"
                      >
                        Открыть первоисточник <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
                      </a>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          </>
        ) : null}
      </section>
    </div>
  );
}
