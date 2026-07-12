import { ExternalLink } from 'lucide-react';
import { formatActivePeriod, formatCoverageLevel, formatDeadline, formatProgramFundingLabel, isValidExternalUrl } from '../lib/format';
import type { SupportProgram, SupportSource } from '../types';
import { Tag } from './ui';

export type ProgramCardProps = {
  program: SupportProgram;
  source: SupportSource | null;
  isFavorite: boolean;
  showDataQuality: boolean;
  onToggleFavorite: () => void;
  onOpen: () => void;
};

export function ProgramCard({ program, source, isFavorite, showDataQuality, onToggleFavorite, onOpen }: ProgramCardProps) {
  const shownTopics = program.topics.slice(0, 3);
  const shownRegions = program.regions.slice(0, 2);
  const remainingTopics = program.topics.length - shownTopics.length;
  const remainingRegions = program.regions.length - shownRegions.length;

  return (
    <article aria-label={program.title} data-motion-card data-density-card className="group min-w-0 overflow-hidden rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm transition hover:-translate-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <Tag>{program.status}</Tag>
        <Tag>{formatDeadline(program.deadline)}</Tag>
        <Tag>{program.supportType}</Tag>
        <Tag>{formatCoverageLevel(program.coverageLevel)}</Tag>
      </div>
      <h2 className="mt-5 text-xl font-semibold">{program.title}</h2>
      <p className="mt-1 text-sm font-medium text-cobalt">{source?.name ?? 'Источник не найден'}</p>
      <p className="mt-3 line-clamp-3 text-sm leading-6 text-graphite">{program.description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {shownTopics.map((topic) => <Tag key={topic}>{topic}</Tag>)}
        {remainingTopics > 0 ? <Tag>+{remainingTopics}</Tag> : null}
      </div>
      <dl className="mt-5 grid gap-3 text-sm text-graphite sm:grid-cols-2">
        <div><dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Регионы</dt><dd className="mt-1 font-semibold text-ink">{shownRegions.join(', ')}{remainingRegions > 0 ? ` +${remainingRegions}` : ''}</dd></div>
        <div><dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Финансирование</dt><dd className="mt-1 font-semibold text-ink">{formatProgramFundingLabel(program)}</dd></div>
        <div><dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Период</dt><dd className="mt-1 font-semibold text-ink">{formatActivePeriod(program)}</dd></div>
        <div><dt className="text-xs font-medium uppercase tracking-[0.08em] text-graphite/65">Актуальность</dt><dd className="mt-1 font-semibold text-ink">Обновлено {formatDeadline(program.updatedAt)}</dd></div>
      </dl>
      {showDataQuality ? <p className="mt-4 text-xs text-graphite/75">Полнота данных: {program.dataQuality.score}%. Не заполнено полей: {program.dataQuality.missingFields.length}.</p> : null}
      <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <button type="button" aria-pressed={isFavorite} aria-label={isFavorite ? `Удалить ${program.title} из избранного` : `Добавить ${program.title} в избранное`} onClick={onToggleFavorite} className="inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/10 px-4 py-2 text-sm font-semibold text-graphite transition hover:bg-white">
          {isFavorite ? 'В избранном' : 'В избранное'}
        </button>
        <button type="button" onClick={onOpen} aria-label={`Подробнее о программе ${program.title}`} className="inline-flex min-h-11 items-center justify-center rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-ink/85 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2">
          Подробнее
        </button>
        {isValidExternalUrl(program.sourceUrl) ? <a href={program.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/10 px-4 py-2 text-sm font-semibold text-graphite transition hover:bg-white">Первоисточник <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" /></a> : null}
      </div>
    </article>
  );
}
