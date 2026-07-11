import type { AnalyticsSummary } from '../lib/analytics';
import { formatDeadline, formatMoneyRub } from '../lib/format';
import { MetricTile } from './ui';

export function AnalyticsWidgets({ analytics }: { analytics: AnalyticsSummary }) {
  return (
    <div data-motion-card data-density-grid className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <MetricTile label="Программ" value={analytics.totalPrograms} hint="в тестовой базе" />
      <MetricTile label="Источников" value={analytics.totalSources} hint="фондов и платформ" />
      <MetricTile label="Актуальных" value={analytics.activePrograms} hint="открыты или постоянный набор" />
      <MetricTile
        label="Ближайший дедлайн"
        value={analytics.nearestDeadline ? formatDeadline(analytics.nearestDeadline.deadline) : 'Нет'}
        hint={analytics.nearestDeadline?.title}
      />
      <MetricTile label="Макс. поддержка" value={formatMoneyRub(analytics.maxFundingRub)} hint="по указанным суммам" />
    </div>
  );
}
