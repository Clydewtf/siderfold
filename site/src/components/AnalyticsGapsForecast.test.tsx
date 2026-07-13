import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
import { confidenceLabel, formatPercent, severityLabel } from '../lib/analyticsPresentation';
import { formatMoneyRub } from '../lib/format';
import { AnalyticsGapsForecast } from './AnalyticsGapsForecast';

describe('AnalyticsGapsForecast', () => {
  it('labels gaps and forecast honestly and delegates both exports', async () => {
    const user = userEvent.setup();
    const onRequestExport = vi.fn();
    const analytics = buildAnalytics(sources, programs);
    const view = render(
      <AnalyticsGapsForecast
        supportGaps={analytics.supportGaps}
        forecast={analytics.forecast}
        exportNotice={null}
        onRequestExport={onRequestExport}
      />
    );

    [
      'Пробелы поддержки',
      'Регионы с низким покрытием',
      'Тематики с низким покрытием',
      'Слабые сочетания региона и тематики',
      'Демо-прогноз по историческим seed-данным',
      'Растущие тематики',
      'Метод расчета'
    ].forEach((name) => expect(screen.getByRole('heading', { name })).toBeInTheDocument());
    expect(
      screen.getByText('Выводы рассчитаны по текущей seed-базе и не описывают весь рынок.')
    ).toBeInTheDocument();

    [
      { heading: 'Регионы с низким покрытием', gaps: analytics.supportGaps.weakRegions },
      { heading: 'Тематики с низким покрытием', gaps: analytics.supportGaps.weakTopics },
      { heading: 'Слабые сочетания региона и тематики', gaps: analytics.supportGaps.weakRegionTopicPairs }
    ].forEach(({ heading, gaps }) => {
      const card = screen.getByRole('heading', { name: heading }).closest('article');
      expect(card).not.toBeNull();
      gaps.forEach((gap) => {
        const gapItem = within(card!).getByText(gap.label, { exact: true }).closest('li');
        expect(gapItem).not.toBeNull();
        expect(within(gapItem!).getByText(gap.reason, { exact: true })).toBeInTheDocument();
        expect(
          within(gapItem!).getByText(
            `${severityLabel(gap.severity)} · ${gap.programCount} программ · ${formatMoneyRub(gap.totalFundingRub)}`,
            { exact: true }
          )
        ).toBeInTheDocument();
      });
    });

    const fundingMetric = screen.getByText(`Ожидаемое финансирование на ${analytics.forecast.nextYear}`).closest('article');
    expect(fundingMetric).not.toBeNull();
    expect(
      within(fundingMetric!).getByText(formatMoneyRub(analytics.forecast.expectedFundingRub), { exact: true })
    ).toBeInTheDocument();
    const programsMetric = screen.getByText(`Ожидаемое число программ на ${analytics.forecast.nextYear}`).closest('article');
    expect(programsMetric).not.toBeNull();
    expect(within(programsMetric!).getByText(String(analytics.forecast.expectedProgramCount), { exact: true })).toBeInTheDocument();
    const changeMetric = screen.getByText('Изменение числа программ').closest('article');
    expect(changeMetric).not.toBeNull();
    expect(
      within(changeMetric!).getByText(String(analytics.forecast.expectedProgramCountChange), { exact: true })
    ).toBeInTheDocument();
    expect(
      screen.getByText(`Уверенность: ${confidenceLabel(analytics.forecast.confidence)} (${analytics.forecast.confidenceScore}%)`)
    ).toBeInTheDocument();
    expect(screen.getByText(analytics.forecast.method)).toBeInTheDocument();
    analytics.forecast.growingTopics.forEach((topic) =>
      expect(screen.getByText(`${topic.topic} — рост ${formatPercent(topic.growthRate)}`, { exact: true })).toBeInTheDocument()
    );
    expect(
      screen.getByText('Демо-прогноз по историческим seed-данным. После подключения backend модель будет пересчитываться по полной базе.')
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Экспорт отчета' }));
    await user.click(screen.getByRole('button', { name: 'Экспорт CSV' }));
    expect(onRequestExport).toHaveBeenCalledTimes(2);
    ['Экспорт отчета', 'Экспорт CSV'].forEach((name) =>
      expect(screen.getByRole('button', { name })).not.toHaveClass('transition')
    );

    view.rerender(
      <AnalyticsGapsForecast
        supportGaps={analytics.supportGaps}
        forecast={analytics.forecast}
        exportNotice="Экспорт отчета и CSV появится после подключения backend."
        onRequestExport={onRequestExport}
      />
    );
    expect(screen.getByRole('status')).toHaveTextContent('Экспорт отчета и CSV появится после подключения backend.');

    const empty = buildAnalytics([], []);
    view.rerender(
      <AnalyticsGapsForecast
        supportGaps={empty.supportGaps}
        forecast={empty.forecast}
        exportNotice={null}
        onRequestExport={onRequestExport}
      />
    );
    expect(screen.getByText('Недостаточно данных для demo-прогноза')).toBeInTheDocument();
  });
});
