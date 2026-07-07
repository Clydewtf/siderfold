import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from './analytics';

describe('analytics', () => {
  it('computes metrics from seed data', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.totalPrograms).toBe(30);
    expect(analytics.totalSources).toBe(10);
    expect(analytics.activePrograms).toBe(22);
    expect(analytics.maxFundingRub).toBe(20000000);
    expect(analytics.fundedShare).toBeCloseTo(0.5, 1);
    expect(analytics.nearestDeadline?.programId).toBe('impact-hub-eco-impact');
  });

  it('builds distributions and nearest deadlines', () => {
    const analytics = buildAnalytics(sources, programs);

    expect(analytics.bySupportType.find((item) => item.label === 'Грант')?.count).toBe(10);
    expect(analytics.bySource.find((item) => item.label === 'Фонд Потанина')?.count).toBe(3);
    expect(analytics.nearestDeadlines.map((item) => item.programId).slice(0, 3)).toEqual([
      'impact-hub-eco-impact',
      'rsv-volunteer-region',
      'potanin-university-grant-2026'
    ]);
  });
});
