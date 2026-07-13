import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
import { formatMoneyRub } from '../lib/format';
import { AnalyticsTimeQuality } from './AnalyticsTimeQuality';

describe('AnalyticsTimeQuality', () => {
  it('renders seasonality, yearly dynamics and transparent quality states', () => {
    const analytics = buildAnalytics(sources, programs);
    const view = render(
      <AnalyticsTimeQuality
        temporal={analytics.temporal}
        dataQuality={analytics.dataQuality}
        filteredPrograms={analytics.filteredPrograms}
      />
    );

    [
      'Время и дедлайны',
      'Ближайшие дедлайны',
      'Программы без дедлайна',
      'Сезонность дедлайнов',
      'Окна высокой активности',
      'Динамика по годам',
      'Качество данных',
      'Полнота базы',
      'Пробелы в полях',
      'Качество по источникам'
    ].forEach((name) => expect(screen.getByRole('heading', { name })).toBeInTheDocument());

    const seasonality = screen.getByRole('list', { name: 'Сезонность дедлайнов' });
    expect(within(seasonality).getAllByRole('listitem')).toHaveLength(12);
    analytics.temporal.byDeadlineMonth.forEach((item) =>
      expect(screen.getAllByText(item.label, { exact: true }).length).toBeGreaterThan(0)
    );
    expect(screen.getAllByText(analytics.temporal.peakDeadlineMonths[0].label, { exact: true }).length).toBeGreaterThan(0);

    const firstYear = analytics.temporal.byYear[0];
    const yearlyTable = screen.getByRole('region', { name: 'Динамика по годам' });
    const yearlyRow = within(yearlyTable).getByRole('rowheader', { name: String(firstYear.year) }).closest('tr');
    expect(yearlyRow).not.toBeNull();
    expect(within(yearlyRow!).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      String(firstYear.launchedPrograms),
      String(firstYear.activePrograms),
      formatMoneyRub(firstYear.totalFundingRub)
    ]);

    ['Без суммы', 'Без дедлайна', 'Без региона', 'Без даты обновления'].forEach((label) =>
      expect(screen.getByText(label, { exact: true })).toBeInTheDocument()
    );

    const densityGrids = Array.from(view.container.querySelectorAll('[data-density-grid]'));
    expect(densityGrids).toHaveLength(3);
    densityGrids.forEach((grid) => expect(grid).toHaveClass('grid-cols-1', 'md:grid-cols-2', 'lg:grid-cols-2'));

    const sourceWithoutPrograms = { ...sources[0], id: 'unobserved-source', name: 'Источник без наблюдений' };
    const nullableQuality = buildAnalytics([...sources, sourceWithoutPrograms], programs);
    view.rerender(
      <AnalyticsTimeQuality
        temporal={nullableQuality.temporal}
        dataQuality={nullableQuality.dataQuality}
        filteredPrograms={nullableQuality.filteredPrograms}
      />
    );
    const qualityTable = screen.getByRole('region', { name: 'Качество по источникам' });
    const nullableRow = within(qualityTable).getByRole('rowheader', { name: sourceWithoutPrograms.name }).closest('tr');
    expect(nullableRow).not.toBeNull();
    expect(within(nullableRow!).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      'Нет наблюдений',
      '0'
    ]);

    const empty = buildAnalytics([], []);
    view.rerender(
      <AnalyticsTimeQuality temporal={empty.temporal} dataQuality={empty.dataQuality} filteredPrograms={0} />
    );
    expect(screen.getByText('Нет ближайших дедлайнов')).toBeInTheDocument();
    expect(screen.getByText('Историческая динамика недоступна')).toBeInTheDocument();
    expect(screen.getByText('Нет записей для оценки качества')).toBeInTheDocument();
  });
});
