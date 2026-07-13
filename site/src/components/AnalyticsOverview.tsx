import type { AnalyticsSummary } from '../lib/analytics';
import { buildAnalyticsInsights } from '../lib/analyticsPresentation';
import { formatDeadline, formatMoneyRub } from '../lib/format';
import { AnalyticsBarList, AnalyticsMetric } from './AnalyticsPrimitives';

const cardClassName = 'rounded-xl border border-ink/10 bg-white/80 p-5';

export function AnalyticsOverview({ analytics }: { analytics: AnalyticsSummary }) {
  const insights = buildAnalyticsInsights(analytics);
  const regions = analytics.regional.regions.slice(0, 5).map((region) => ({
    id: region.region,
    label: region.region,
    value: region.programCount,
    displayValue: String(region.programCount)
  }));
  const sources = analytics.sources.byProgramCount.slice(0, 5).map((source) => ({
    id: source.sourceId,
    label: source.sourceName,
    value: source.programCount,
    displayValue: String(source.programCount)
  }));

  return (
    <section aria-labelledby="analytics-overview-title" className="mt-10">
      <h2 id="analytics-overview-title" className="text-3xl font-semibold">Обзор базы</h2>

      <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <AnalyticsMetric label="Всего программ" value={analytics.totalPrograms} />
        <AnalyticsMetric label="Активных программ" value={analytics.activePrograms} />
        <AnalyticsMetric label="Источников" value={analytics.totalSources} />
        <AnalyticsMetric label="Общий объем поддержки" value={formatMoneyRub(analytics.totalFundingRub)} />
        <AnalyticsMetric label="Средняя сумма" value={formatMoneyRub(analytics.averageFundingRub)} />
        <AnalyticsMetric label="Медианная сумма" value={formatMoneyRub(analytics.medianFundingRub)} />
      </div>

      <div data-density-grid className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article data-density-card className={cardClassName}>
          <h3 className="text-xl font-semibold">Федеральные и региональные меры</h3>
          <div data-density-grid className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <AnalyticsMetric label="Федеральные программы" value={analytics.regional.federalPrograms} />
            <AnalyticsMetric label="Региональные программы" value={analytics.regional.regionalPrograms} />
          </div>
        </article>

        <article data-density-card className={cardClassName}>
          <h3 className="text-xl font-semibold">Топ регионов</h3>
          <div className="mt-4">
            <AnalyticsBarList label="Топ регионов" items={regions} emptyText="Региональные данные отсутствуют." />
          </div>
        </article>

        <article data-density-card className={cardClassName}>
          <h3 className="text-xl font-semibold">Топ источников</h3>
          <div className="mt-4">
            <AnalyticsBarList label="Топ источников" items={sources} emptyText="Источники в выбранном срезе отсутствуют." />
          </div>
        </article>

        <article data-density-card className={cardClassName}>
          <h3 className="text-xl font-semibold">Ближайшие дедлайны</h3>
          {analytics.temporal.nearestDeadlines.length > 0 ? (
            <ul className="mt-4 grid grid-cols-1 gap-3">
              {analytics.temporal.nearestDeadlines.map((deadline) => (
                <li key={deadline.programId} className="min-w-0">
                  <p className="break-words text-sm font-semibold">{deadline.title}</p>
                  <p className="mt-1 text-sm text-graphite">{formatDeadline(deadline.deadline)}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-graphite">Ближайших дедлайнов нет.</p>
          )}
        </article>

        <article data-density-card className={cardClassName}>
          <h3 className="text-xl font-semibold">Короткие аналитические выводы</h3>
          <ul aria-label="Короткие аналитические выводы" className="mt-4 grid grid-cols-1 gap-3 list-disc pl-5 text-sm leading-6">
            {insights.map((insight) => <li key={insight}>{insight}</li>)}
          </ul>
        </article>
      </div>
    </section>
  );
}
