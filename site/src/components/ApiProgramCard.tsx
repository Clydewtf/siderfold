import { ExternalLink } from 'lucide-react';
import { formatDeadline, formatOptionalDate, isValidExternalUrl } from '../lib/format';
import type { PublicProgram } from '../data-access/catalogMapper';
import { FavoriteToggle } from './FavoriteToggle';
import { Tag } from './ui';

export type ApiProgramCardProps = {
  program: PublicProgram;
  isFavorite: boolean;
  onToggleFavorite: () => void;
  onOpen: () => void;
};

export function ApiProgramCard({ program, isFavorite, onToggleFavorite, onOpen }: ApiProgramCardProps) {
  return (
    <article
      aria-label={program.title}
      data-motion-card
      data-density-card
      className="group min-w-0 overflow-hidden rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm transition hover:-translate-y-1"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Tag>Проверено в Siderfold</Tag>
        <Tag>{formatDeadline(program.deadline)}</Tag>
        {program.funding ? <Tag>На программу: {program.funding.label}</Tag> : <Tag>Сумма не указана</Tag>}
      </div>
      <div className="mt-5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words text-xl font-semibold">{program.title}</h2>
          <p className="mt-1 text-sm font-medium text-cobalt">{program.primarySource.source.name}</p>
        </div>
        <FavoriteToggle itemName={program.title} isFavorite={isFavorite} onToggle={onToggleFavorite} />
      </div>
      <p className="mt-3 text-sm leading-6 text-graphite">
        {program.summary ?? 'Краткое описание не извлечено; подробные условия доступны на первоисточнике.'}
      </p>
      <dl className="mt-5 grid gap-3 text-sm text-graphite sm:grid-cols-2">
        <div className="sm:col-span-2">
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Параметры</dt>
          <dd className="mt-1 font-semibold text-ink">
            {program.regions.length > 0 || program.themes.length > 0
              ? [...program.regions, ...program.themes].join(', ')
              : 'Подробные условия — в карточке и на первоисточнике'}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Дата на источнике</dt>
          <dd className="mt-1 font-semibold text-ink">{formatOptionalDate(program.sourcePublishedOn)}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Добавлено в Siderfold</dt>
          <dd className="mt-1 font-semibold text-ink">{formatOptionalDate(program.publishedAt.slice(0, 10))}</dd>
        </div>
      </dl>
      <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <button
          type="button"
          onClick={onOpen}
          aria-label={`Подробнее о программе ${program.title}`}
          className="inline-flex min-h-11 items-center justify-center rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-ink/85 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
        >
          Подробнее
        </button>
        {isValidExternalUrl(program.primarySource.sourceUrl) ? (
          <a
            href={program.primarySource.sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/10 px-4 py-2 text-sm font-semibold text-graphite transition hover:bg-white"
          >
            Первоисточник <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
          </a>
        ) : null}
      </div>
    </article>
  );
}
