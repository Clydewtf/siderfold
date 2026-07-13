import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
import { formatPercent } from '../lib/analyticsPresentation';
import { formatCoverageLevel, formatMoneyRub } from '../lib/format';
import { AnalyticsSourcesTopics } from './AnalyticsSourcesTopics';

describe('AnalyticsSourcesTopics', () => {
  it('renders source/topic rankings, monitoring details, and their empty states', () => {
    const analytics = buildAnalytics(sources, programs);
    const view = render(
      <AnalyticsSourcesTopics
        sources={analytics.sources}
        topics={analytics.topics}
        totalPrograms={analytics.filteredPrograms}
      />
    );

    [
      'Источники',
      'По числу программ',
      'По активным программам',
      'По объему поддержки',
      'Качество данных источников',
      'Тематики',
      'Распределение программ',
      'Объем поддержки по тематикам',
      'Сильные тематики',
      'Слабое покрытие тематик',
      'Пересечения тематики и региона'
    ].forEach((name) => expect(screen.getByRole('heading', { name })).toBeInTheDocument());

    const rankedSource = analytics.sources.byProgramCount[0];
    const rankedTopic = analytics.topics.topics[0];
    expect(screen.getAllByText(rankedSource.sourceName, { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getAllByText(rankedTopic.topic, { exact: true }).length).toBeGreaterThan(0);

    const sourceTable = screen.getByRole('region', { name: 'Качество данных источников' });
    const source = analytics.sources.byDataQuality[0];
    const sourceRow = within(sourceTable).getByRole('rowheader', { name: source.sourceName }).closest('tr');
    expect(sourceRow).not.toBeNull();
    expect(within(sourceRow!).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      source.sourceType,
      formatCoverageLevel(source.coverageLevel),
      String(source.programCount),
      formatPercent(source.programCount / analytics.filteredPrograms),
      String(source.activeProgramCount),
      source.dataCompletenessScore === null ? 'Нет наблюдений' : `${Math.round(source.dataCompletenessScore)}%`,
      String(source.incompleteProgramCount)
    ]);

    ['Источник', 'Тип', 'Уровень', 'Программ', 'Вклад в базу', 'Активных', 'Полнота данных', 'Неполных записей'].forEach(
      (name) => expect(within(sourceTable).getByRole('columnheader', { name })).toBeInTheDocument()
    );
    const intersectionsTable = screen.getByRole('region', { name: 'Пересечения тематики и региона' });
    ['Тематика', 'Регион', 'Программ', 'Объем'].forEach((name) =>
      expect(within(intersectionsTable).getByRole('columnheader', { name })).toBeInTheDocument()
    );

    const intersection = analytics.topics.intersections[0];
    const expectedIntersectionCells = [
      intersection.region,
      String(intersection.programCount),
      formatMoneyRub(intersection.totalFundingRub)
    ];
    const intersectionRow = within(intersectionsTable).getAllByRole('row').find((row) =>
      within(row).queryByRole('rowheader', { name: intersection.topic }) !== null &&
      within(row).getAllByRole('cell').map((cell) => cell.textContent).join('|') === expectedIntersectionCells.join('|')
    );
    expect(intersectionRow).toBeDefined();
    expect(within(intersectionRow!).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(expectedIntersectionCells);

    const empty = buildAnalytics([], []);
    view.rerender(<AnalyticsSourcesTopics sources={empty.sources} topics={empty.topics} totalPrograms={0} />);
    expect(screen.getByText('Источники в выбранном срезе отсутствуют')).toBeInTheDocument();
    expect(screen.getByText('Тематики в выбранном срезе отсутствуют')).toBeInTheDocument();
  });

  it('renders every engine-ranked monitoring list and responsive paired grids', () => {
    const analytics = buildAnalytics(sources, programs);
    const view = render(
      <AnalyticsSourcesTopics
        sources={analytics.sources}
        topics={analytics.topics}
        totalPrograms={analytics.filteredPrograms}
      />
    );
    const { container } = view;

    [
      {
        label: 'По активным программам',
        item: analytics.sources.byActiveProgramCount[0],
        displayValue: String(analytics.sources.byActiveProgramCount[0].activeProgramCount)
      },
      {
        label: 'По объему поддержки',
        item: analytics.sources.byFunding[0],
        displayValue: formatMoneyRub(analytics.sources.byFunding[0].totalFundingRub)
      },
      {
        label: 'Объем поддержки по тематикам',
        item: analytics.topics.topics[0],
        displayValue: formatMoneyRub(analytics.topics.topics[0].totalFundingRub)
      }
    ].forEach(({ label, item, displayValue }) => {
      const ranking = screen.getByRole('list', { name: label });
      const entry = within(ranking).getByText(
        'sourceName' in item ? item.sourceName : item.topic,
        { exact: true }
      ).closest('li');
      expect(entry).not.toBeNull();
      expect(within(entry!).getByText(displayValue, { exact: true })).toBeInTheDocument();
    });

    const strongTopic = analytics.topics.strongTopics[0];
    expect(strongTopic).toBeDefined();
    const strongCallout = screen.getByRole('heading', { name: 'Сильные тематики' }).closest('article');
    expect(strongCallout).not.toBeNull();
    expect(
      within(strongCallout!).getByText(
        `${strongTopic!.topic} — ${strongTopic!.programCount} программ, ${formatMoneyRub(strongTopic!.totalFundingRub)}`,
        { exact: true }
      )
    ).toBeInTheDocument();

    expect(analytics.topics.intersections.length).toBeGreaterThan(12);
    const intersectionsTable = screen.getByRole('region', { name: 'Пересечения тематики и региона' });
    expect(
      within(intersectionsTable).getAllByRole('row').slice(1).map((row) => row.textContent)
    ).toEqual(
      analytics.topics.intersections.slice(0, 12).map((item) =>
        `${item.topic}${item.region}${item.programCount}${formatMoneyRub(item.totalFundingRub)}`
      )
    );

    const densityGrids = Array.from(container.querySelectorAll('[data-density-grid]'));
    expect(densityGrids).toHaveLength(3);
    expect(densityGrids[0]).toHaveClass('grid-cols-1', 'md:grid-cols-2', 'lg:grid-cols-3');
    densityGrids.slice(1).forEach((grid) =>
      expect(grid).toHaveClass('grid-cols-1', 'md:grid-cols-2', 'lg:grid-cols-2')
    );

    const weakAnalytics = buildAnalytics(sources, programs, { sourceId: 'impact-hub', supportType: 'Грант' });
    const weakTopic = weakAnalytics.topics.weakTopics[0];
    expect(weakTopic).toBeDefined();
    view.rerender(
      <AnalyticsSourcesTopics
        sources={weakAnalytics.sources}
        topics={weakAnalytics.topics}
        totalPrograms={weakAnalytics.filteredPrograms}
      />
    );
    const weakCallout = screen.getByRole('heading', { name: 'Слабое покрытие тематик' }).closest('article');
    expect(weakCallout).not.toBeNull();
    expect(
      within(weakCallout!).getByText(
        `${weakTopic!.topic} — ${weakTopic!.programCount} программ, ${formatMoneyRub(weakTopic!.totalFundingRub)}`,
        { exact: true }
      )
    ).toBeInTheDocument();
  });
});
