import { ExternalLink } from 'lucide-react';
import type { SourceAnalyticsItem } from '../lib/analytics';
import { formatCoverageLevel, formatMoneyRub, isValidExternalUrl } from '../lib/format';
import type { SupportSource } from '../types';
import { Tag } from './ui';

export type SourceCardProps = {
  source: SupportSource;
  metrics: SourceAnalyticsItem;
  totalPrograms: number;
  selected: boolean;
  isFavorite: boolean;
  showDataQuality: boolean;
  onSelect: () => void;
  onToggleFavorite: () => void;
};

export function SourceCard({
  source,
  metrics,
  totalPrograms,
  selected,
  isFavorite,
  showDataQuality,
  onSelect,
  onToggleFavorite
}: SourceCardProps) {
  const databaseShare = totalPrograms === 0 ? 0 : Math.round((metrics.programCount / totalPrograms) * 100);

  return (
    <article
      aria-label={source.name}
      data-testid={`source-card-${source.id}`}
      data-motion-card
      data-density-card
      className={`group flex h-full flex-col overflow-hidden rounded-lg border p-5 shadow-sm transition ${
        selected ? 'border-cobalt bg-cobalt/5 ring-2 ring-cobalt/20' : 'border-ink/10 bg-white/80 hover:border-cobalt/40'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-ink text-sm font-semibold text-white">{source.logoLabel}</div>
        <div className="text-right text-sm text-graphite">
          <p>{metrics.programCount} программы</p>
          <p>{metrics.activeProgramCount} активные</p>
        </div>
      </div>
      <p className="mt-5 text-xl font-semibold text-ink">{source.name}</p>
      <p className="mt-3 text-sm leading-6 text-graphite">{source.description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Tag>{source.type}</Tag>
        <Tag>{formatCoverageLevel(source.coverageLevel)}</Tag>
        <Tag>{source.region}</Tag>
        {source.topics.map((topic) => (
          <Tag key={topic}>{topic}</Tag>
        ))}
      </div>
      <dl className="mt-5 grid gap-3 text-sm text-graphite sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Известный объем</dt>
          <dd className="mt-1 font-semibold text-ink">{formatMoneyRub(metrics.totalFundingRub)}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Вклад в базу</dt>
          <dd className="mt-1 font-semibold text-ink">{databaseShare}% базы</dd>
        </div>
      </dl>
      {showDataQuality ? (
        <p className="mt-4 text-xs text-graphite/75">
          {metrics.dataCompletenessScore === null
            ? 'Нет программ для оценки'
            : `Полнота данных: ${Math.round(metrics.dataCompletenessScore)}%`}
        </p>
      ) : null}
      {selected ? <p className="mt-3 w-fit rounded-full bg-cobalt/10 px-3 py-1 text-xs font-semibold text-cobalt">Выбран</p> : null}
      <div data-testid={`source-card-actions-${source.id}`} className="mt-auto flex flex-col gap-3 pt-5">
        <button
          type="button"
          aria-pressed={isFavorite}
          aria-label={isFavorite ? `Удалить ${source.name} из избранного` : `Добавить ${source.name} в избранное`}
          onClick={onToggleFavorite}
          className="rounded-full border border-ink/10 bg-white/70 px-3 py-2 text-xs font-semibold text-ink"
        >
          {isFavorite ? 'В избранном' : 'В избранное'}
        </button>
        <button
          type="button"
          aria-pressed={selected}
          onClick={onSelect}
          className="inline-flex min-h-11 w-full min-w-0 items-center justify-center rounded-lg bg-ink px-4 py-2 text-center text-sm font-semibold leading-5 text-white transition hover:bg-ink/85 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
        >
          <span className="min-w-0 break-words">{selected ? `Смотреть программы ${source.name}` : `Выбрать источник ${source.name}`}</span>
        </button>
        {isValidExternalUrl(source.websiteUrl) ? (
          <a
            href={source.websiteUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 w-full min-w-0 items-center justify-center rounded-lg border border-ink/10 px-4 py-2 text-center text-sm font-semibold leading-5 text-graphite transition hover:bg-white"
          >
            <span className="min-w-0 break-words">Открыть сайт {source.name}</span>
            <ExternalLink className="ml-2 h-4 w-4 shrink-0" aria-hidden="true" />
          </a>
        ) : null}
      </div>
    </article>
  );
}
