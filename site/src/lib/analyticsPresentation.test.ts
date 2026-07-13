import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from './analytics';
import {
  buildAnalyticsInsights,
  confidenceLabel,
  formatPercent,
  severityLabel
} from './analyticsPresentation';

describe('analytics presentation helpers', () => {
  it('formats bounded shares and user-facing labels', () => {
    expect(formatPercent(0.376)).toBe('38%');
    expect(formatPercent(Number.NaN)).toBe('0%');
    expect(confidenceLabel('medium')).toBe('Средняя');
    expect(severityLabel('high')).toBe('Высокий пробел');
  });

  it('builds short explainable insights from ranked engine output', () => {
    const analytics = buildAnalytics(sources, programs);
    const insights = buildAnalyticsInsights(analytics);

    expect(insights).toHaveLength(4);
    expect(insights[0]).toContain(analytics.regional.regions[0].region);
    expect(insights.join(' ')).toContain(analytics.sources.byProgramCount[0].sourceName);
    expect(insights.join(' ')).toContain('полноты');
  });

  it('returns honest copy for an empty analytics result', () => {
    expect(buildAnalyticsInsights(buildAnalytics([], []))).toEqual([
      'В выбранном срезе нет программ для аналитического вывода.'
    ]);
  });
});
