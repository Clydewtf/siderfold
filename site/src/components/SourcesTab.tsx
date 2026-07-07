import { ExternalLink } from 'lucide-react';
import { Fragment, useEffect, useMemo, useState } from 'react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { getProgramsBySource, getSourceProgramCounts } from '../lib/catalog';
import { isValidExternalUrl } from '../lib/format';
import type { SourceType, SupportProgram, SupportSource, Topic } from '../types';
import { EmptyState, Tag } from './ui';

export function SourcesTab({
  sources,
  programs
}: {
  sources: readonly SupportSource[];
  programs: readonly SupportProgram[];
}) {
  const [type, setType] = useState<SourceType | 'Все типы'>('Все типы');
  const [topic, setTopic] = useState<Topic | 'Все тематики'>('Все тематики');
  const [selectedSourceId, setSelectedSourceId] = useState(sources[0]?.id ?? '');

  const sourceTypes = useMemo(
    () => Array.from(new Set(sources.map((source) => source.type))).sort((a, b) => a.localeCompare(b, 'ru')),
    [sources]
  );
  const topics = useMemo(
    () => Array.from(new Set(sources.flatMap((source) => source.topics))).sort((a, b) => a.localeCompare(b, 'ru')),
    [sources]
  );
  const counts = useMemo(() => getSourceProgramCounts(sources, programs), [sources, programs]);
  const filtered = sources.filter((source) => {
    return (type === 'Все типы' || source.type === type) && (topic === 'Все тематики' || source.topics.includes(topic));
  });
  const selected = filtered.find((source) => source.id === selectedSourceId) ?? filtered[0];
  const related = selected ? getProgramsBySource(programs, selected.id) : [];
  const selectedAnnouncement = selected ? `Выбран источник: ${selected.name}` : 'Источник не выбран';

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => ScrollTrigger.refresh());

    return () => window.cancelAnimationFrame(frame);
  }, [type, topic, filtered.length]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <p role="status" aria-live="polite" className="sr-only">
        {selectedAnnouncement}
      </p>
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-4xl font-semibold">Источники программ</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-graphite">
            Фонды, платформы, университеты и акселераторы, из которых формируется тестовая база возможностей.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm font-medium text-graphite">
            Тип источника
            <select
              value={type}
              onChange={(event) => setType(event.target.value as SourceType | 'Все типы')}
              className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
            >
              <option>Все типы</option>
              {sourceTypes.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium text-graphite">
            Тематика источника
            <select
              value={topic}
              onChange={(event) => setTopic(event.target.value as Topic | 'Все тематики')}
              className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
            >
              <option>Все тематики</option>
              {topics.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="mt-10 grid gap-6 lg:grid-cols-[1fr_420px] lg:items-start">
        <div className="grid gap-4 md:grid-cols-2">
          {filtered.map((source) => (
            <Fragment key={source.id}>
              <article
                aria-label={source.name}
                data-testid={`source-card-${source.id}`}
                data-motion-card
                className={`group flex h-full flex-col overflow-hidden rounded-lg border p-5 shadow-sm transition ${
                  selected?.id === source.id ? 'border-cobalt bg-cobalt/5 ring-2 ring-cobalt/20' : 'border-ink/10 bg-white/80 hover:border-cobalt/40'
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-ink text-sm font-semibold text-white">{source.logoLabel}</div>
                  <div className="text-right text-sm text-graphite">
                    <p>{counts[source.id].total} программы</p>
                    <p>{counts[source.id].active} актуальные</p>
                  </div>
                </div>
                <p className="mt-5 text-xl font-semibold text-ink">{source.name}</p>
                <p className="mt-3 text-sm leading-6 text-graphite">{source.description}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Tag>{source.type}</Tag>
                  {source.topics.map((item) => (
                    <Tag key={item}>{item}</Tag>
                  ))}
                </div>
                {selected?.id === source.id ? (
                  <p className="mt-3 w-fit rounded-full bg-cobalt/10 px-3 py-1 text-xs font-semibold text-cobalt">Выбран</p>
                ) : null}
                <div data-testid={`source-card-actions-${source.id}`} className="mt-auto flex flex-col gap-3 pt-5">
                  <button
                    type="button"
                    onClick={() => setSelectedSourceId(source.id)}
                    className="inline-flex min-h-11 w-full min-w-0 items-center justify-center rounded-lg bg-ink px-4 py-2 text-center text-sm font-semibold leading-5 text-white transition hover:bg-ink/85 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
                  >
                    <span className="min-w-0 break-words">
                      {selected?.id === source.id ? `Смотреть программы ${source.name}` : `Выбрать источник ${source.name}`}
                    </span>
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
              {selected?.id === source.id ? (
                <div className="md:col-span-2 lg:hidden">
                  <SourceDetails source={selected} related={related} />
                </div>
              ) : null}
            </Fragment>
          ))}
          {filtered.length === 0 ? (
            <EmptyState title="Источники не найдены" description="Измените тип источника или тематику, чтобы увидеть карточки." />
          ) : null}
        </div>

        {selected ? (
          <aside data-testid="desktop-source-details-column" className="hidden lg:block lg:w-[420px] lg:self-stretch">
            <div
              data-testid="desktop-source-details"
              className="lg:sticky lg:top-28 lg:max-h-[calc(100vh-8rem)] lg:w-[420px] lg:overflow-y-auto lg:rounded-lg"
            >
              <SourceDetails source={selected} related={related} />
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}

function SourceDetails({ source, related }: { source: SupportSource; related: readonly SupportProgram[] }) {
  return (
    <div className="rounded-lg border border-ink/10 bg-ink p-6 text-white shadow-panel">
      <h2 className="text-2xl font-semibold">{source.name}</h2>
      <p className="mt-3 text-sm leading-6 text-white/75">{source.trustNote}</p>
      {isValidExternalUrl(source.websiteUrl) ? (
        <a href={source.websiteUrl} target="_blank" rel="noreferrer" className="mt-5 inline-flex items-center text-sm font-semibold text-white">
          Открыть сайт источника <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
        </a>
      ) : (
        <p className="mt-5 text-sm text-white/70">Ссылка на источник не указана корректно.</p>
      )}
      <div className="mt-8 space-y-3">
        <p className="text-sm font-semibold text-white/70">Программы источника</p>
        {related.length > 0 ? (
          related.map((program) => (
            <div key={program.id} className="rounded-lg border border-white/10 bg-white/10 p-3">
              <p className="text-sm font-semibold">{program.title}</p>
              <p className="mt-1 text-xs text-white/65">{program.status}</p>
            </div>
          ))
        ) : (
          <p className="text-sm text-white/70">У источника нет программ в seed-данных.</p>
        )}
      </div>
    </div>
  );
}
