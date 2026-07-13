import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
import { AnalyticsOverview } from './AnalyticsOverview';

describe('AnalyticsOverview', () => {
  it('renders the complete presentation overview from the engine result', () => {
    const analytics = buildAnalytics(sources, programs);
    render(<AnalyticsOverview analytics={analytics} />);
    ['Обзор базы', 'Федеральные и региональные меры', 'Топ регионов', 'Топ источников', 'Ближайшие дедлайны', 'Короткие аналитические выводы'].forEach((name) => expect(screen.getByRole('heading', { name })).toBeInTheDocument());
    ['Всего программ', 'Активных программ', 'Источников', 'Общий объем поддержки', 'Средняя сумма', 'Медианная сумма'].forEach((label) => expect(screen.getByText(label, { exact: true })).toBeInTheDocument());
    expect(screen.getByText(analytics.regional.regions[0].region)).toBeInTheDocument();
    expect(screen.getByText(analytics.sources.byProgramCount[0].sourceName)).toBeInTheDocument();
    expect(screen.getByText(analytics.temporal.nearestDeadlines[0].title)).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Короткие аналитические выводы' })).toBeInTheDocument();
  });

  it('marks every overview grid with an explicit base column and density hook', () => {
    const analytics = buildAnalytics(sources, programs);
    const { container } = render(<AnalyticsOverview analytics={analytics} />);
    const grids = Array.from(container.querySelectorAll('[data-density-grid]'));

    expect(grids).toHaveLength(3);
    grids.forEach((grid) => expect(grid).toHaveClass('grid-cols-1'));
  });
});
