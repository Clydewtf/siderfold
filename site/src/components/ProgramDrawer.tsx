import { ExternalLink, X } from 'lucide-react';
import { useEffect, useRef, type KeyboardEvent } from 'react';
import { isValidExternalUrl, formatDeadline, formatMoneyRub } from '../lib/format';
import type { SupportProgram, SupportSource } from '../types';
import { Tag } from './ui';

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

export function ProgramDrawer({
  program,
  source,
  isFavorite,
  onToggleFavorite,
  onClose
}: {
  program: SupportProgram | null;
  source: SupportSource | null;
  isFavorite: boolean;
  onToggleFavorite: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!program) return;

    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();

    return () => {
      if (openerRef.current && document.contains(openerRef.current)) {
        openerRef.current.focus();
      }
    };
  }, [program]);

  if (!program) return null;

  const validDocumentUrls = program.documentUrls.filter(isValidExternalUrl);

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

    const focusableElements = getFocusableElements();
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (!firstElement || !lastElement) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }

    if (event.shiftKey && document.activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
    } else if (!event.shiftKey && document.activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/45 p-3 backdrop-blur-sm" role="presentation">
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={program.title}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className="h-full w-full max-w-2xl overflow-y-auto rounded-lg bg-paper p-6 shadow-panel"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-cobalt">{source?.name ?? 'Источник не найден'}</p>
            <h2 className="mt-2 text-3xl font-semibold text-ink">{program.title}</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="Закрыть детали"
              className="rounded-full border border-ink/10 bg-white p-2 text-ink"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
            <button
              type="button"
              aria-pressed={isFavorite}
              aria-label={isFavorite ? `Удалить ${program.title} из избранного` : `Добавить ${program.title} в избранное`}
              onClick={onToggleFavorite}
              className="rounded-full border border-ink/10 bg-white px-3 py-2 text-sm font-semibold text-ink"
            >
              {isFavorite ? 'В избранном' : 'В избранное'}
            </button>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <Tag>{program.status}</Tag>
          <Tag>{formatDeadline(program.deadline)}</Tag>
          <Tag>{formatMoneyRub(program.fundingAmountRub)}</Tag>
          <Tag>{program.supportType}</Tag>
        </div>

        <p className="mt-6 text-base leading-7 text-graphite">{program.description}</p>

        <section className="mt-8">
          <h3 className="text-lg font-semibold">Требования</h3>
          <ul className="mt-3 space-y-2">
            {program.requirements.map((requirement) => (
              <li key={requirement} className="rounded-lg border border-ink/10 bg-white/70 p-3 text-sm text-graphite">
                {requirement}
              </li>
            ))}
          </ul>
        </section>

        <section className="mt-8 grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-ink/10 bg-white/70 p-4">
            <h3 className="text-sm font-semibold text-graphite">Аудитория</h3>
            <p className="mt-2 text-sm text-ink">{program.audience.join(', ')}</p>
          </div>
          <div className="rounded-lg border border-ink/10 bg-white/70 p-4">
            <h3 className="text-sm font-semibold text-graphite">Тематики</h3>
            <p className="mt-2 text-sm text-ink">{program.topics.join(', ')}</p>
          </div>
        </section>

        <section className="mt-8 space-y-3">
          <h3 className="text-lg font-semibold">Ссылки</h3>
          {isValidExternalUrl(program.sourceUrl) ? (
            <a
              href={program.sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white"
            >
              Открыть первоисточник <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
            </a>
          ) : (
            <p className="text-sm text-graphite">Ссылка на первоисточник не указана корректно.</p>
          )}
          <div className="flex flex-wrap gap-2">
            {validDocumentUrls.length > 0 ? (
              validDocumentUrls.map((url, index) => (
                <a
                  key={url}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-ink/10 bg-white px-3 py-1 text-sm font-semibold text-ink"
                >
                  Документ {index + 1}
                </a>
              ))
            ) : (
              <p className="text-sm text-graphite">Документы не приложены.</p>
            )}
          </div>
        </section>
      </section>
    </div>
  );
}
