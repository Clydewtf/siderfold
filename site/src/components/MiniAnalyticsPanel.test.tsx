import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
import { formatDeadline } from '../lib/format';
import { MiniAnalyticsPanel } from './MiniAnalyticsPanel';

describe('MiniAnalyticsPanel', () => {
  it('renders required analytics distributions and deadline list', () => {
    const analytics = buildAnalytics(sources, programs);
    const nearestDeadline = analytics.nearestDeadlines[0];

    expect(nearestDeadline).toBeDefined();
    if (!nearestDeadline) {
      throw new Error('Expected at least one nearest deadline in analytics.');
    }

    render(<MiniAnalyticsPanel analytics={analytics} />);

    expect(screen.getByText('Распределение по источникам')).toBeInTheDocument();
    expect(screen.getByText('Распределение по типам поддержки')).toBeInTheDocument();
    expect(screen.getByText('Ближайшие дедлайны')).toBeInTheDocument();
    expect(screen.getByText('Фонд Потанина')).toBeInTheDocument();
    expect(screen.getByText('Грант')).toBeInTheDocument();
    expect(screen.getByText(nearestDeadline.title)).toBeInTheDocument();
    expect(screen.getByText(formatDeadline(nearestDeadline.deadline))).toBeInTheDocument();
  });
});
