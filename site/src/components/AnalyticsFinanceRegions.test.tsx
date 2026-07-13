import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
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

    const empty = buildAnalytics([], []);
    view.rerender(<AnalyticsFinanceRegions finance={empty.finance} regional={empty.regional} />);
    expect(screen.getByText('В выбранном срезе нет финансовых данных')).toBeInTheDocument();
    expect(screen.getByText('Региональные данные отсутствуют')).toBeInTheDocument();
  });
});
