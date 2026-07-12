import { ExternalLink } from 'lucide-react';
import type { SourceAnalyticsItem } from '../lib/analytics';
import {
  formatCoverageLevel,
  formatDeadline,
  formatMoneyRub,
  formatProgramFundingLabel,
  isValidExternalUrl
} from '../lib/format';
import type { SupportProgram, SupportSource } from '../types';
import { Tag } from './ui';

export type SourceDetailsProps = {
  source: SupportSource;
  metrics: SourceAnalyticsItem;
  totalPrograms: number;
  relatedPrograms: readonly SupportProgram[];
  showDataQuality: boolean;
  onOpenProgram: (program: SupportProgram) => void;
};

export function SourceDetails({
  source,
  metrics,
  totalPrograms,
  relatedPrograms,
  showDataQuality,
  onOpenProgram
}: SourceDetailsProps) {
  const databaseShare = totalPrograms === 0 ? 0 : Math.round((metrics.programCount / totalPrograms) * 100);

  return (
    <div className="rounded-lg border border-ink/10 bg-ink p-6 text-white shadow-panel">
      <h2 className="text-2xl font-semibold">{source.name}</h2>
      <p className="mt-3 text-sm leading-6 text-white/75">{source.trustNote}</p>
      <div className="mt-5 flex flex-wrap gap-2">
        <Tag>{formatCoverageLevel(source.coverageLevel)}</Tag>
        <Tag>{source.region}</Tag>
        {source.topics.map((topic) => (
          <Tag key={topic}>{topic}</Tag>
        ))}
      </div>
      <p className="mt-4 text-sm text-white/70">Проверено {formatDeadline(source.verifiedAt)}</p>
      {isValidExternalUrl(source.websiteUrl) ? (
        <a href={source.websiteUrl} target="_blank" rel="noreferrer" className="mt-5 inline-flex items-center text-sm font-semibold text-white">
          Открыть сайт источника <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
        </a>
      ) : (
        <p className="mt-5 text-sm text-white/70">Ссылка на источник не указана корректно.</p>
      )}
      <dl className="mt-8 grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-white/65">Программ</dt>
          <dd className="mt-1 text-lg font-semibold">{metrics.programCount}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-white/65">Активные</dt>
          <dd className="mt-1 text-lg font-semibold">{metrics.activeProgramCount}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-white/65">Известный объем</dt>
          <dd className="mt-1 text-lg font-semibold">{formatMoneyRub(metrics.totalFundingRub)}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-[0.08em] text-white/65">Вклад в базу</dt>
          <dd className="mt-1 text-lg font-semibold">Вклад в базу: {databaseShare}%</dd>
        </div>
      </dl>
      {showDataQuality ? (
        <p className="mt-4 text-sm text-white/75">
          {metrics.dataCompletenessScore === null
            ? 'Нет программ для оценки'
            : `Полнота данных: ${Math.round(metrics.dataCompletenessScore)}%`}
        </p>
      ) : null}
      <div className="mt-8 space-y-3">
        <p className="text-sm font-semibold text-white/70">Программы источника</p>
        {relatedPrograms.length > 0 ? (
          relatedPrograms.map((program) => (
            <div key={program.id} className="rounded-lg border border-white/10 bg-white/10 p-3">
              <p className="text-sm font-semibold">{program.title}</p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs text-white/65">
                <span>{program.status}</span>
                <span>{formatDeadline(program.deadline)}</span>
                <span>{formatProgramFundingLabel(program)}</span>
              </div>
              <button
                type="button"
                aria-label={`Открыть программу ${program.title}`}
                onClick={() => onOpenProgram(program)}
                className="mt-3 inline-flex min-h-9 items-center rounded-lg border border-white/20 px-3 py-1 text-sm font-semibold text-white transition hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2 focus:ring-offset-ink"
              >
                Подробнее
              </button>
            </div>
          ))
        ) : (
          <p className="text-sm text-white/70">У источника нет связанных программ в текущей базе.</p>
        )}
      </div>
    </div>
  );
}
