import type { AnalyticsSummary } from '../lib/analytics';
import { formatDeadline } from '../lib/format';

export function MiniAnalyticsPanel({ analytics }: { analytics: AnalyticsSummary }) {
  const maxSourceCount = Math.max(...analytics.bySource.map((item) => item.count), 1);
  const maxSupportCount = Math.max(...analytics.bySupportType.map((item) => item.count), 1);

  return (
    <section data-motion-pin className="grid gap-10 py-24 lg:grid-cols-[0.78fr_1.22fr]">
      <div data-motion-pin-title className="h-fit">
        <h2 className="text-4xl font-semibold">Мини-аналитика базы</h2>
        <p className="mt-4 max-w-md text-sm leading-6 text-graphite">
          Виджеты считаются из тех же seed-данных, что и карточки каталога. Это проверяет целостность MVP без отдельной BI-системы.
        </p>
      </div>
      <div data-density-grid className="grid gap-4">
        <article data-motion-card data-density-card className="rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm">
          <h3 className="text-lg font-semibold">Распределение по источникам</h3>
          <div className="mt-4 space-y-3">
            {analytics.bySource.map((item) => (
              <div key={item.id}>
                <div className="flex justify-between gap-3 text-sm">
                  <span>{item.label}</span>
                  <span className="font-semibold">{item.count}</span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink/10">
                  <div className="h-full rounded-full bg-cobalt" style={{ width: `${(item.count / maxSourceCount) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </article>
        <article data-motion-card data-density-card className="rounded-lg border border-ink/10 bg-white/80 p-5 shadow-sm">
          <h3 className="text-lg font-semibold">Распределение по типам поддержки</h3>
          <div className="mt-4 space-y-3">
            {analytics.bySupportType.map((item) => (
              <div key={item.id}>
                <div className="flex justify-between gap-3 text-sm">
                  <span>{item.label}</span>
                  <span className="font-semibold">{item.count}</span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink/10">
                  <div className="h-full rounded-full bg-clay" style={{ width: `${(item.count / maxSupportCount) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </article>
        <article data-motion-card data-density-card className="rounded-lg border border-ink/10 bg-ink p-5 text-white shadow-sm">
          <h3 className="text-lg font-semibold">Ближайшие дедлайны</h3>
          <div className="mt-4 space-y-3">
            {analytics.nearestDeadlines.map((item) => (
              <div key={item.programId} className="rounded-lg bg-white/10 p-3">
                <p className="text-sm font-semibold">{item.title}</p>
                <p className="mt-1 text-xs text-white/65">{formatDeadline(item.deadline)}</p>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}
