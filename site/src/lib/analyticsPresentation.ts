import type { AnalyticsSummary, ForecastAnalytics, SupportGap } from './analytics';

export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '0%';
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export function confidenceLabel(value: ForecastAnalytics['confidence']): string {
  return { high: 'Высокая', medium: 'Средняя', low: 'Низкая' }[value];
}

export function severityLabel(value: SupportGap['severity']): string {
  return { high: 'Высокий пробел', medium: 'Средний пробел', low: 'Низкий пробел' }[value];
}

export function buildAnalyticsInsights(analytics: AnalyticsSummary): string[] {
  if (analytics.filteredPrograms === 0) {
    return ['В выбранном срезе нет программ для аналитического вывода.'];
  }

  const topRegion = analytics.regional.regions[0];
  const topSource = analytics.sources.byProgramCount[0];
  const topTopic = analytics.topics.topics[0];
  const insights = [
    topRegion
      ? `${topRegion.region} лидирует в выбранном срезе: ${topRegion.programCount} программ.`
      : 'Региональный охват в выбранном срезе не указан.',
    topSource
      ? `${topSource.sourceName} — крупнейший источник по числу программ: ${topSource.programCount}.`
      : 'Связанные источники в выбранном срезе отсутствуют.',
    topTopic
      ? `${topTopic.topic} — наиболее представленная тематика: ${topTopic.programCount} программ.`
      : 'Тематические метки в выбранном срезе отсутствуют.',
    `Индекс полноты выбранного среза — ${Math.round(analytics.dataQuality.completenessIndex)}%.`
  ];

  return insights;
}
