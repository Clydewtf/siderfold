import { ExternalLink } from 'lucide-react';
import { formatDeadline, formatOptionalDate, isValidExternalUrl } from '../lib/format';
import type { PublicProgram } from '../data-access/catalogMapper';
import { ApplicationStatusTag } from './ApplicationStatusTag';
import { FavoriteToggle } from './FavoriteToggle';
import { Tag } from './ui';

export type ApiProgramCardProps = {
  program: PublicProgram;
  isFavorite: boolean;
  onToggleFavorite: () => void;
  onOpen: () => void;
};

export function ApiProgramCard({ program, isFavorite, onToggleFavorite, onOpen }: ApiProgramCardProps) {
  const taxonomyFallback = program.taxonomyAvailable === false ? 'Откройте карточку' : 'Не указаны';

  return (
    <article
      aria-label={program.title}
      data-motion-card
      data-density-card
      className="group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm transition hover:-translate-y-1"
    >
      <div className="flex flex-wrap items-center gap-2">
        <ApplicationStatusTag program={program} />
        {program.deadline ? <Tag>Приём до {formatDeadline(program.deadline)}</Tag> : null}
        {program.funding ? <Tag>Финансирование: {program.funding.label}</Tag> : <Tag>Сумма не указана</Tag>}
      </div>
      <div className="mt-5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="line-clamp-2 break-words text-xl font-semibold leading-tight">{program.title}</h2>
          <p className="mt-1 line-clamp-1 text-sm font-medium text-cobalt">{program.primarySource.source.name}</p>
        </div>
        <FavoriteToggle itemName={program.title} isFavorite={isFavorite} onToggle={onToggleFavorite} />
      </div>
      <p title={program.summary ?? undefined} className="mt-3 min-h-[6rem] line-clamp-4 whitespace-pre-line text-sm leading-6 text-graphite">
        {program.summary ?? 'Краткое описание не извлечено; подробные условия доступны на первоисточнике.'}
      </p>
      <dl className="mt-5 grid gap-3 text-sm text-graphite sm:grid-cols-2">
        <div className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Регионы</dt>
          <dd className="mt-1 min-h-[3rem] line-clamp-2 font-semibold text-ink">{program.regions.length > 0 ? program.regions.join(', ') : taxonomyFallback}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Тематики</dt>
          <dd className="mt-1 min-h-[3rem] line-clamp-2 font-semibold text-ink">{program.themes.length > 0 ? program.themes.join(', ') : taxonomyFallback}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Дата на источнике</dt>
          <dd className="mt-1 font-semibold text-ink">{formatOptionalDate(program.sourcePublishedOn)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Добавлено в Siderfold</dt>
          <dd className="mt-1 font-semibold text-ink">{formatOptionalDate(program.publishedAt.slice(0, 10))}</dd>
        </div>
      </dl>
      <div className="mt-auto flex flex-col gap-3 pt-5 sm:flex-row sm:flex-wrap sm:items-center">
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
