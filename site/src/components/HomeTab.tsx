import { ArrowRight, Database, ExternalLink } from 'lucide-react';
import type { SupportProgram, SupportSource } from '../types';
import { buildAnalytics } from '../lib/analytics';
import { formatDeadline, formatMoneyRub } from '../lib/format';
import { AnalyticsWidgets } from './AnalyticsWidgets';
import { MiniAnalyticsPanel } from './MiniAnalyticsPanel';
import { IconButton, secondaryButtonClassName, Tag } from './ui';

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
    <div className="page-container">
      <section className="grid items-center gap-8 py-8 sm:py-10 lg:min-h-[62vh] lg:grid-cols-[1.12fr_0.88fr] lg:gap-10 lg:py-20">
        <div className="max-w-6xl">
          <p className="eyebrow">Единая база поддержки стартапов</p>
          <h1 className="home-title">
            Программы поддержки — в одном рабочем пространстве
          </h1>
          <p className="home-lead">
            Каталог, источники и аналитика используют одну базу, чтобы искать возможности и видеть рынок поддержки системно.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <IconButton onClick={onOpenPrograms}>
              Открыть каталог <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" />
            </IconButton>
            <button type="button" onClick={onOpenAnalytics} className={`${secondaryButtonClassName} transition hover:bg-surface/75 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2`}>
              Открыть аналитику
            </button>
            <button
              type="button"
              onClick={onOpenSources}
              className={`${secondaryButtonClassName} transition hover:bg-surface/75 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2`}
            >
              Смотреть источники
            </button>
          </div>
        </div>
        <aside aria-label="Состояние базы" data-motion-media className="demo-status grain-overlay overflow-hidden shadow-panel">
          <p className="eyebrow">Состояние базы</p>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            <div>
              <p className="text-sm text-graphite">Программ</p>
              <p className="mt-2 text-3xl font-semibold text-ink">{analytics.totalPrograms}</p>
            </div>
            <div>
              <p className="text-sm text-graphite">Источников</p>
              <p className="mt-2 text-3xl font-semibold text-ink">{analytics.totalSources}</p>
            </div>
            <div>
              <p className="text-sm text-graphite">Активны</p>
              <p className="mt-2 text-3xl font-semibold text-ink">{analytics.activePrograms}</p>
            </div>
          </div>
          <p className="mt-8 border-t border-cobalt/20 pt-4 text-sm font-semibold text-graphite">Демо-режим · frontend-only</p>
        </aside>
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
