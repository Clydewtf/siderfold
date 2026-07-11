import { ArrowRight, Database, ExternalLink } from 'lucide-react';
import type { SupportProgram, SupportSource } from '../types';
import { buildAnalytics } from '../lib/analytics';
import { formatDeadline, formatMoneyRub } from '../lib/format';
import { AnalyticsWidgets } from './AnalyticsWidgets';
import { MiniAnalyticsPanel } from './MiniAnalyticsPanel';
import { IconButton, Tag } from './ui';

export function HomeTab({
  sources,
  programs,
  onOpenPrograms,
  onOpenAnalytics,
  onOpenSources,
  onOpenProgram
}: {
  sources: readonly SupportSource[];
  programs: readonly SupportProgram[];
  onOpenPrograms: () => void;
  onOpenAnalytics: () => void;
  onOpenSources: () => void;
  onOpenProgram: (program: SupportProgram) => void;
}) {
  const analytics = buildAnalytics(sources, programs);
  const featured = programs.filter((program) => program.featured).slice(0, 4);

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <section className="grid items-center gap-8 py-8 sm:py-10 lg:min-h-[62vh] lg:grid-cols-[1.12fr_0.88fr] lg:gap-10 lg:py-20">
        <div className="max-w-6xl">
          <h1 className="max-w-6xl text-[clamp(2.35rem,9vw,5.5rem)] font-semibold leading-[0.98] text-ink">
            Единая база программ поддержки для быстрых решений
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-graphite">
            MVP показывает источники, конкурсы, дедлайны, суммы и первичные ссылки в одном рабочем интерфейсе.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <IconButton onClick={onOpenPrograms}>
              Открыть каталог <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" />
            </IconButton>
            <button type="button" onClick={onOpenAnalytics} className="inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/15 bg-white px-4 py-2 text-sm font-semibold text-ink">
              Открыть аналитику
            </button>
            <button
              type="button"
              onClick={onOpenSources}
              className="inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/15 bg-white px-4 py-2 text-sm font-semibold text-ink transition hover:bg-white/75 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
            >
              Смотреть источники
            </button>
          </div>
        </div>
        <div data-motion-media className="grain-overlay overflow-hidden rounded-lg border border-ink/10 bg-ink p-5 text-white shadow-panel">
          <div className="h-72 rounded-md bg-[url('https://picsum.photos/seed/support-data-catalog/1200/900')] bg-cover bg-center opacity-85 mix-blend-luminosity" />
          <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-white/60">Seed-данные</p>
              <p className="text-2xl font-semibold">{analytics.totalPrograms}</p>
            </div>
            <div>
              <p className="text-white/60">Источники</p>
              <p className="text-2xl font-semibold">{analytics.totalSources}</p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-12">
        <AnalyticsWidgets analytics={analytics} />
      </section>

      <section data-density-grid className="grid grid-flow-dense gap-4 py-20 md:grid-cols-6">
        <article data-motion-card data-density-card className="rounded-lg border border-ink/10 bg-white/75 p-6 shadow-sm md:col-span-3 md:row-span-2">
          <Database className="h-6 w-6 text-cobalt" aria-hidden="true" />
          <h2 className="mt-8 text-3xl font-semibold">Что внутри</h2>
          <p className="mt-4 text-sm leading-6 text-graphite">
            Источники, программы, сроки, суммы, тематики и ссылки на первоисточники связаны в одной структуре данных.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            {['источники', 'программы', 'сроки', 'суммы', 'тематики', 'документы'].map((item) => (
              <Tag key={item}>{item}</Tag>
            ))}
          </div>
        </article>
        <article data-motion-card data-density-card className="rounded-lg border border-ink/10 bg-moss p-6 text-white md:col-span-3">
          <h2 className="text-2xl font-semibold">Финансирование видно сразу</h2>
          <p className="mt-3 text-sm leading-6 text-white/80">
            Доля программ с указанной суммой: {Math.round(analytics.fundedShare * 100)}%.
          </p>
        </article>
        <article data-motion-card data-density-card className="rounded-lg border border-ink/10 bg-white/75 p-6 md:col-span-3">
          <h2 className="text-2xl font-semibold">Дедлайны не теряются</h2>
          <p className="mt-3 text-sm leading-6 text-graphite">
            Ближайшие сроки автоматически считаются из тех же данных, что и каталог.
          </p>
        </article>
      </section>

      <MiniAnalyticsPanel analytics={analytics} />

      <section className="py-20">
        <div className="flex items-end justify-between gap-6">
          <div>
            <h2 className="text-3xl font-semibold">Заметные программы</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-graphite">
              Несколько записей из seed-базы для быстрой проверки сценария раскрытия карточки.
            </p>
          </div>
        </div>
        <div data-density-grid className="mt-8 grid gap-4 md:grid-cols-2">
          {featured.map((program) => (
            <article key={program.id} data-motion-card data-density-card className="group overflow-hidden rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm transition hover:-translate-y-1">
              <div className="flex flex-wrap gap-2">
                <Tag>{program.supportType}</Tag>
                <Tag>{formatDeadline(program.deadline)}</Tag>
              </div>
              <h3 className="mt-5 text-xl font-semibold">{program.title}</h3>
              <p className="mt-3 text-sm leading-6 text-graphite">{program.description}</p>
              <div className="mt-5 flex items-center justify-between gap-4">
                <span className="text-sm font-semibold">{formatMoneyRub(program.fundingAmountRub)}</span>
                <button type="button" onClick={() => onOpenProgram(program)} className="inline-flex items-center text-sm font-semibold text-cobalt">
                  Подробнее о программе <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
