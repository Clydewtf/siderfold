import { ExternalLink, X } from 'lucide-react';
import { useEffect, useRef, type KeyboardEvent } from 'react';
import {
  formatActivePeriod,
  formatCoverageLevel,
  formatDeadline,
  formatMoneyRub,
  formatProgramFundingLabel,
  isValidExternalUrl
} from '../lib/format';
import type { DataQualityField, SupportProgram, SupportSource } from '../types';
import { FavoriteToggle } from './FavoriteToggle';
import { Tag } from './ui';

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

const missingFieldLabels: Record<DataQualityField, string> = {
  funding: 'сумма',
  deadline: 'дедлайн',
  regions: 'регионы',
  source: 'источник',
  updatedAt: 'дата обновления',
  sourceUrl: 'первоисточник'
};

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-ink/10 bg-white/70 p-4">
      <h4 className="text-sm font-semibold text-graphite">{label}</h4>
      <p className="mt-2 break-words text-sm text-ink">{value}</p>
    </div>
  );
}

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
        aria-label={program.title}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className="h-full w-full max-w-2xl overflow-y-auto rounded-lg bg-paper p-6 shadow-panel"
      >
        <div data-testid="program-drawer-header" className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-cobalt">{source?.name ?? 'Источник не найден'}</p>
            <h2 className="mt-2 break-words text-3xl font-semibold text-ink">{program.title}</h2>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="Закрыть детали"
              className="order-2 inline-flex h-11 w-11 items-center justify-center rounded-full bg-ink text-white"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
            <FavoriteToggle itemName={program.title} isFavorite={isFavorite} onToggle={onToggleFavorite} className="order-1" />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <Tag>{program.status}</Tag>
          <Tag>{formatDeadline(program.deadline)}</Tag>
          <Tag>{formatProgramFundingLabel(program)}</Tag>
          <Tag>{program.supportType}</Tag>
          <Tag>{formatCoverageLevel(program.coverageLevel)}</Tag>
        </div>

        <p className="mt-6 text-base leading-7 text-graphite">{program.description}</p>

        <section aria-labelledby="program-overview" className="mt-8 grid gap-4 sm:grid-cols-2">
          <h3 id="program-overview" className="sr-only">Основные параметры</h3>
          <Detail label="Регионы" value={program.regions.length > 0 ? program.regions.join(', ') : 'Регион не указан'} />
          <Detail label="Период действия" value={formatActivePeriod(program)} />
          <Detail label="Год запуска" value={String(program.launchYear)} />
          <Detail label="Обновлено" value={formatDeadline(program.updatedAt)} />
          <Detail label="Аудитория" value={program.audience.length > 0 ? program.audience.join(', ') : 'Аудитория не указана'} />
          <Detail label="Тематики" value={program.topics.length > 0 ? program.topics.join(', ') : 'Тематики не указаны'} />
        </section>

        <section className="mt-8">
          <h3 className="text-lg font-semibold">Финансирование</h3>
          <p className="mt-3 text-sm text-graphite">Указанная сумма: {formatProgramFundingLabel(program)}</p>
          {(program.fundingMinRub !== null || program.fundingMaxRub !== null) && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {program.fundingMinRub !== null && <Detail label="Минимум" value={formatMoneyRub(program.fundingMinRub)} />}
              {program.fundingMaxRub !== null && <Detail label="Максимум" value={formatMoneyRub(program.fundingMaxRub)} />}
            </div>
          )}
        </section>

        <section className="mt-8">
          <h3 className="text-lg font-semibold">Требования</h3>
          {program.requirements.length > 0 ? (
            <ul className="mt-3 space-y-2">
              {program.requirements.map((requirement) => (
                <li key={requirement} className="rounded-lg border border-ink/10 bg-white/70 p-3 text-sm text-graphite">
                  {requirement}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-graphite">Требования не опубликованы.</p>
          )}
        </section>

        <section className="mt-8">
          <h3 className="text-lg font-semibold">Качество данных</h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="min-w-0 rounded-lg border border-ink/10 bg-white/70 p-4 text-sm text-ink">
              Полнота данных: {program.dataQuality.score}%
            </div>
            <Detail label="Уровень" value={program.dataQuality.level} />
            <Detail label="Проверено" value={formatDeadline(program.dataQuality.checkedAt)} />
            <Detail
              label="Не хватает"
              value={program.dataQuality.missingFields.length > 0
                ? program.dataQuality.missingFields.map((field) => missingFieldLabels[field]).join(', ')
                : 'Все ключевые поля заполнены'}
            />
          </div>
        </section>

        <section className="mt-8">
          <h3 className="text-lg font-semibold">Об источнике</h3>
          {source ? (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Detail label="Источник" value={`Источник: ${source.name}`} />
              <Detail label="Тип" value={source.type} />
              <Detail label="Охват" value={`Охват источника: ${formatCoverageLevel(source.coverageLevel)}`} />
              <Detail label="Регион" value={`Регион источника: ${source.region}`} />
              <Detail label="Проверено" value={formatDeadline(source.verifiedAt)} />
              <Detail label="Доверие" value={source.trustNote} />
            </div>
          ) : (
            <p className="mt-3 text-sm text-graphite">Данные источника недоступны в текущей базе.</p>
          )}
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
