import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
import { formatMoneyRub } from '../lib/format';
import { AnalyticsFinanceRegions } from './AnalyticsFinanceRegions';

describe('AnalyticsFinanceRegions', () => {
  it('renders financial/regional monitoring and explicit empty states', () => {
    const analytics = buildAnalytics(sources, programs, { region: 'Москва' });
    const view = render(
      <AnalyticsFinanceRegions finance={analytics.finance} regional={analytics.regional} />
    );

    [
      'Финансы',
      'Финансирование по типам поддержки',
      'Финансирование по источникам',
      'Финансирование по регионам',
      'Федеральные и региональные объемы',
      'Регионы',
      'Высокая концентрация',
      'Низкое покрытие'
    ].forEach((name) => expect(screen.getByRole('heading', { name })).toBeInTheDocument());
    ['Общий объем', 'Средняя сумма', 'Медианная сумма', 'Максимальная сумма'].forEach((label) =>
      expect(screen.getByText(label, { exact: true })).toBeInTheDocument()
    );
    ['Регион', 'Программ', 'Активных', 'Объем', 'Средняя', 'Индекс покрытия'].forEach((name) =>
      expect(screen.getByRole('columnheader', { name })).toBeInTheDocument()
    );

    [
      { label: 'Общий объем', value: analytics.finance.totalFundingRub },
      { label: 'Средняя сумма', value: analytics.finance.averageFundingRub },
      { label: 'Медианная сумма', value: analytics.finance.medianFundingRub },
      { label: 'Максимальная сумма', value: analytics.finance.maxFundingRub }
    ].forEach(({ label, value }) => {
      const metricCard = screen.getByText(label, { exact: true }).closest('article');
      expect(metricCard).not.toBeNull();
      expect(within(metricCard!).getByText(formatMoneyRub(value), { exact: true })).toBeInTheDocument();
    });

    [
      { label: 'Финансирование по типам поддержки', item: analytics.finance.bySupportType[0] },
      { label: 'Финансирование по источникам', item: analytics.finance.bySource[0] },
      { label: 'Финансирование по регионам', item: analytics.finance.byRegion[0] },
      { label: 'Федеральные и региональные объемы', item: analytics.finance.byCoverageLevel[0] }
    ].forEach(({ label, item }) => {
      expect(item).toBeDefined();
      const distribution = screen.getByRole('list', { name: label });
      expect(within(distribution).getByText(item!.label, { exact: true })).toBeInTheDocument();
      expect(
        within(distribution).getAllByText(formatMoneyRub(item!.totalFundingRub), { exact: true }).length
      ).toBeGreaterThan(0);
    });

    [
      { heading: 'Высокая концентрация', item: analytics.regional.highCoverageRegions[0] },
      { heading: 'Низкое покрытие', item: analytics.regional.lowCoverageRegions[0] }
    ].forEach(({ heading, item }) => {
      expect(item).toBeDefined();
      const callout = screen.getByRole('heading', { name: heading }).closest('article');
      expect(callout).not.toBeNull();
      expect(
        within(callout!).getByText(`${item!.region} — индекс покрытия ${item!.coverageScore}`, { exact: true })
      ).toBeInTheDocument();
    });

    const region = analytics.regional.regions[0];
    const row = screen.getByRole('rowheader', { name: region.region }).closest('tr');
    expect(row).not.toBeNull();
    expect(within(row!).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      String(region.programCount),
      String(region.activeProgramCount),
      formatMoneyRub(region.totalFundingRub),
      formatMoneyRub(region.averageFundingRub),
      String(region.coverageScore)
    ]);

    const empty = buildAnalytics([], []);
    view.rerender(<AnalyticsFinanceRegions finance={empty.finance} regional={empty.regional} />);
    expect(screen.getByText('В выбранном срезе нет финансовых данных')).toBeInTheDocument();
    expect(screen.getByText('Региональные данные отсутствуют')).toBeInTheDocument();
  });
});
