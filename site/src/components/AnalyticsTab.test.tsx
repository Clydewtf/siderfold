import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { programs, sources } from '../data/seed';
import { buildAnalytics } from '../lib/analytics';
import { buildAnalyticsInsights } from '../lib/analyticsPresentation';
import { formatMoneyRub } from '../lib/format';
import type { SupportProgram, SupportSource } from '../types';
import { AnalyticsTab } from './AnalyticsTab';

type AnalyticsTabOverrides = {
  sources?: readonly SupportSource[];
  programs?: readonly SupportProgram[];
  exportNotice?: string | null;
  onRequestExport?: () => void;
};

function renderAnalyticsTab(overrides: AnalyticsTabOverrides = {}) {
  const onRequestExport = overrides.onRequestExport ?? vi.fn();
  render(
    <AnalyticsTab
      sources={overrides.sources ?? sources}
      programs={overrides.programs ?? programs}
      exportNotice={overrides.exportNotice ?? null}
      onRequestExport={onRequestExport}
    />
  );
  return { onRequestExport };
}

describe('AnalyticsTab', () => {
  it('presents the analytics hierarchy, demo context, and live result count', () => {
    renderAnalyticsTab();

    expect(screen.getAllByRole('heading', { level: 1, name: 'Аналитика мер поддержки' })).toHaveLength(1);
    expect(screen.getByText('Мониторинг мер поддержки')).toBeInTheDocument();
    expect(screen.getByText('Презентационный обзор и фильтруемая BI-зона используют те же программы и источники, что каталог Stargate.')).toBeInTheDocument();
    expect(screen.getByText('Демо-режим: выводы рассчитаны по текущей seed-базе.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(`Найдено программ: ${programs.length}`);
  });

  it('renders the overview and every monitoring domain', () => {
    renderAnalyticsTab();

    expect(screen.getAllByRole('heading', { level: 1, name: 'Аналитика мер поддержки' })).toHaveLength(1);
    [
      'Обзор базы',
      'BI-мониторинг',
      'Финансы',
      'Регионы',
      'Источники',
      'Тематики',
      'Время и дедлайны',
      'Качество данных',
      'Пробелы поддержки',
      'Демо-прогноз по историческим seed-данным'
    ].forEach((name) => expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument());
  });

  it('rebuilds every monitoring section from one filter state and resets it', async () => {
    const user = userEvent.setup();
    renderAnalyticsTab();
    expect(screen.getByText(`Найдено программ: ${programs.length}`, { selector: 'p:not(.sr-only)' })).toBeInTheDocument();
    await user.click(screen.getByText('Фильтры аналитики'));
    await user.selectOptions(screen.getByLabelText('Регион аналитики'), 'Москва');
    const filtered = buildAnalytics(sources, programs, { region: 'Москва' });
    expect(screen.getByText(`Найдено программ: ${filtered.filteredPrograms}`, { selector: 'p:not(.sr-only)' })).toBeInTheDocument();
    expect(screen.getAllByText(filtered.regional.regions[0].region).length).toBeGreaterThan(0);
    expect(screen.getAllByText(filtered.sources.byProgramCount[0].sourceName).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Сбросить BI-фильтры' }));
    expect(screen.getByText(`Найдено программ: ${programs.length}`, { selector: 'p:not(.sr-only)' })).toBeInTheDocument();
  });

  it('uses the selected slice for overview metrics, insights, and monitoring details', async () => {
    const user = userEvent.setup();
    renderAnalyticsTab();
    await user.click(screen.getByText('Фильтры аналитики'));
    await user.selectOptions(screen.getByLabelText('Регион аналитики'), 'Москва');
    const filtered = buildAnalytics(sources, programs, { region: 'Москва' });
    const filteredInsights = buildAnalyticsInsights(filtered);
    expect(filtered.totalPrograms).not.toBe(programs.length);
    expect(filteredInsights).not.toEqual(buildAnalyticsInsights(buildAnalytics(sources, programs)));

    const overviewMetric = screen.getByText('Всего программ', { exact: true }).closest('article');
    expect(overviewMetric).not.toBeNull();
    expect(within(overviewMetric!).getByText(String(filtered.totalPrograms), { exact: true })).toBeInTheDocument();
    const insights = screen.getByRole('list', { name: 'Короткие аналитические выводы' });
    expect(within(insights).getByText(filteredInsights[0], { exact: true })).toBeInTheDocument();
    const regionTable = screen.getByRole('region', { name: 'Региональная аналитика' });
    expect(
      within(regionTable).getByRole('rowheader', { name: filtered.regional.regions[0].region })
    ).toBeInTheDocument();
    const sourceRanking = screen.getByRole('list', { name: 'По числу программ' });
    expect(
      within(sourceRanking).getByText(filtered.sources.byProgramCount[0].sourceName, { exact: true })
    ).toBeInTheDocument();
    const financeMetric = screen.getByText('Общий объем', { exact: true }).closest('article');
    expect(financeMetric).not.toBeNull();
    expect(
      within(financeMetric!).getByText(formatMoneyRub(filtered.finance.totalFundingRub), { exact: true })
    ).toBeInTheDocument();
  });

  it('shows the base empty state when no programs are available', () => {
    renderAnalyticsTab({ programs: [] });
    expect(screen.getByText('Аналитическая база пока пуста')).toBeInTheDocument();
  });

  it('keeps filter controls available when a slice has no programs', async () => {
    const user = userEvent.setup();
    renderAnalyticsTab();
    const zeroSource = sources.find(
      (source) => buildAnalytics(sources, programs, { region: 'Москва', sourceId: source.id }).filteredPrograms === 0
    );

    expect(zeroSource).toBeDefined();
    if (!zeroSource) throw new Error('Expected a source with no programs in Moscow.');

    await user.click(screen.getByText('Фильтры аналитики'));
    await user.selectOptions(screen.getByLabelText('Регион аналитики'), 'Москва');
    await user.selectOptions(screen.getByLabelText('Источник аналитики'), zeroSource.id);

    expect(screen.getByText('В выбранном срезе нет программ')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сбросить BI-фильтры' })).toBeInTheDocument();
  });

  it('delegates both export requests to the controlled callback', async () => {
    const user = userEvent.setup();
    const { onRequestExport } = renderAnalyticsTab();

    await user.click(screen.getByRole('button', { name: 'Экспорт отчета' }));
    await user.click(screen.getByRole('button', { name: 'Экспорт CSV' }));

    expect(onRequestExport).toHaveBeenCalledTimes(2);
  });
});
