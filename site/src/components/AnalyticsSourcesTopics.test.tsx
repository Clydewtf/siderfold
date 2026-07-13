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
});
