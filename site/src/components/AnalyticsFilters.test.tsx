import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { defaultAnalyticsFilters } from '../lib/analytics';
import type { AnalyticsFilterOptions } from './AnalyticsFilters';
import { AnalyticsFiltersPanel } from './AnalyticsFilters';

const options: AnalyticsFilterOptions = {
  regions: Array.from(new Set(programs.flatMap((program) => program.regions))),
  years: Array.from(new Set(programs.map((program) => program.launchYear))),
  coverageLevels: Array.from(new Set(programs.map((program) => program.coverageLevel))),
  sources,
  supportTypes: Array.from(new Set(programs.map((program) => program.supportType))),
  topics: Array.from(new Set(programs.flatMap((program) => program.topics))),
  audiences: Array.from(new Set(programs.flatMap((program) => program.audience))),
  statuses: Array.from(new Set(programs.map((program) => program.status)))
};

describe('AnalyticsFiltersPanel', () => {
  it('renders the controlled BI filter disclosure with exact labels', () => {
    render(
      <AnalyticsFiltersPanel
        filters={defaultAnalyticsFilters}
        options={options}
        onChange={() => undefined}
        onReset={() => undefined}
      />
    );

    const labels = [
      'Регион аналитики', 'Год аналитики', 'Уровень программы аналитики',
      'Источник аналитики', 'Тип поддержки аналитики', 'Тематика аналитики',
      'Аудитория аналитики', 'Статус аналитики', 'Наличие суммы аналитики',
      'Наличие дедлайна аналитики'
    ];

    labels.forEach((label) => expect(screen.getByLabelText(label)).toBeInTheDocument());

    const summary = screen.getByText('Фильтры аналитики');
    expect(summary.tagName).toBe('SUMMARY');
    expect(summary.closest('details')).toBeInTheDocument();
  });

  it('updates every engine filter and resets the complete contract', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [filters, setFilters] = useState(defaultAnalyticsFilters);
      return <><AnalyticsFiltersPanel filters={filters} options={options} onChange={(patch) => setFilters((current) => ({ ...current, ...patch }))} onReset={() => setFilters(defaultAnalyticsFilters)} /><output aria-label="filters-json">{JSON.stringify(filters)}</output></>;
    }
    render(<Harness />);
    await user.click(screen.getByText('Фильтры аналитики'));
    await user.selectOptions(screen.getByLabelText('Регион аналитики'), 'Москва');
    await user.selectOptions(screen.getByLabelText('Год аналитики'), '2021');
    await user.selectOptions(screen.getByLabelText('Уровень программы аналитики'), 'regional');
    await user.selectOptions(screen.getByLabelText('Источник аналитики'), 'impact-hub');
    await user.selectOptions(screen.getByLabelText('Тип поддержки аналитики'), 'Акселерация');
    await user.selectOptions(screen.getByLabelText('Тематика аналитики'), 'Экология');
    await user.selectOptions(screen.getByLabelText('Аудитория аналитики'), 'Стартапы');
    await user.selectOptions(screen.getByLabelText('Статус аналитики'), 'Открыта');
    await user.selectOptions(screen.getByLabelText('Наличие суммы аналитики'), 'withFunding');
    await user.selectOptions(screen.getByLabelText('Наличие дедлайна аналитики'), 'next90');
    expect(JSON.parse(screen.getByLabelText('filters-json').textContent ?? '{}')).toEqual({
      region: 'Москва', year: 2021, coverageLevel: 'regional', sourceId: 'impact-hub',
      supportType: 'Акселерация', topic: 'Экология', audience: 'Стартапы', status: 'Открыта',
      funding: 'withFunding', deadline: 'next90'
    });
    expect(screen.getByText('Регион: Москва')).toBeInTheDocument();
    expect(screen.getByText('Есть сумма')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сбросить BI-фильтры' }));
    expect(JSON.parse(screen.getByLabelText('filters-json').textContent ?? '{}')).toEqual(defaultAnalyticsFilters);
  });
});
