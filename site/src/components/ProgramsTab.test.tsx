import type { ComponentProps } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { programs, sources } from '../data/seed';
import { ProgramsTab } from './ProgramsTab';

function renderProgramsTab(overrides: Partial<ComponentProps<typeof ProgramsTab>> = {}) {
  const props: ComponentProps<typeof ProgramsTab> = {
    sources,
    programs,
    favoriteProgramIds: [],
    showDataQuality: true,
    onToggleFavoriteProgram: vi.fn(),
    onOpenProgram: vi.fn(),
    ...overrides
  };

  return { ...render(<ProgramsTab {...props} />), props };
}

function getRenderedProgramTitles() {
  return screen.getAllByRole('article').map((article) => within(article).getByRole('heading', { level: 2 }).textContent);
}

function mockMatchMedia(matches: boolean) {
  const originalMatchMedia = window.matchMedia;
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  });

  return () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: originalMatchMedia
    });
  };
}

describe('ProgramsTab', () => {
  it('presents the catalog hierarchy and live result count', () => {
    renderProgramsTab();

    expect(screen.getAllByRole('heading', { level: 1, name: 'Каталог программ' })).toHaveLength(1);
    expect(screen.getByText('Рабочий каталог')).toBeInTheDocument();
    expect(screen.getByText('Ищите программы по условиям, регионам, срокам и финансированию. Избранное и история просмотра сохраняются локально.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(`Найдено программ: ${programs.length}`);
  });

  it('searches, filters, and sorts programs', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    await user.type(screen.getByLabelText('Поиск'), 'ИИ');
    expect(screen.getByText('Найдено: 5')).toBeInTheDocument();
    expect(getRenderedProgramTitles()).toEqual(expect.arrayContaining(['Индустриальный ИИ акселератор', 'Старт-ИИ']));
    expect(screen.queryByText('УМНИК')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Тип поддержки'), 'Акселерация');
    expect(screen.getByText('Найдено: 2')).toBeInTheDocument();
    expect(getRenderedProgramTitles()).toEqual(['Индустриальный ИИ акселератор', 'AI Pilot Challenge']);
    expect(screen.queryByText('Старт-ИИ')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Сортировка'), 'funding');
    expect(screen.getByLabelText('Сортировка')).toHaveValue('funding');
  });

  it('sorts rendered program cards by funding amount', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    await user.selectOptions(screen.getByLabelText('Сортировка'), 'funding');

    expect(getRenderedProgramTitles().slice(0, 4)).toEqual([
      'Развитие технологической компании',
      'Первый конкурс президентских грантов',
      'Старт-ИИ',
      'Цифровая культура'
    ]);
  });

  it('shows empty state after filters with no results', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    await user.type(screen.getByLabelText('Поиск'), 'несуществующая программа');
    expect(screen.getByText('По вашему запросу ничего не найдено')).toBeInTheDocument();
  });

  it('shows active filter chips and resets filters', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    await user.selectOptions(screen.getByLabelText('Сортировка'), 'funding');
    await user.type(screen.getByLabelText('Поиск'), 'ИИ');
    await user.selectOptions(screen.getByLabelText('Тип поддержки'), 'Акселерация');

    expect(screen.getByText('Поиск: ИИ')).toBeInTheDocument();
    expect(screen.getByText('Тип: Акселерация')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Очистить поиск' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Активные фильтры' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сбросить фильтры' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));

    expect(screen.getByText(`Найдено: ${programs.length}`)).toBeInTheDocument();
    expect(screen.getByLabelText('Сортировка')).toHaveValue('funding');
    expect(screen.queryByText('Поиск: ИИ')).not.toBeInTheDocument();
  });

  it('opens the filter disclosure on desktop so controls stay available', async () => {
    const restoreMatchMedia = mockMatchMedia(true);

    try {
      renderProgramsTab();

      const details = screen.getByText('Фильтры').closest('details');

      await waitFor(() => expect(details).toHaveAttribute('open'));
      expect(screen.getByLabelText('Тип поддержки')).toBeInTheDocument();
      expect(screen.getByLabelText('Сортировка')).toBeInTheDocument();
    } finally {
      restoreMatchMedia();
    }
  });

  it('delegates opening program details to the app shell', async () => {
    const user = userEvent.setup();
    const onOpenProgram = vi.fn();
    renderProgramsTab({ onOpenProgram });

    await user.click(screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i }));
    expect(onOpenProgram).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'fasie-start-ai', title: 'Старт-ИИ' })
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('exposes deadline filter buttons as a pressed group', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    const deadlineGroup = screen.getByRole('group', { name: 'Дедлайн' });
    const allDeadlines = within(deadlineGroup).getByRole('button', { name: 'Все дедлайны' });
    const next30 = within(deadlineGroup).getByRole('button', { name: '30 дней' });

    expect(allDeadlines).toHaveAttribute('aria-pressed', 'true');
    expect(next30).toHaveAttribute('aria-pressed', 'false');

    await user.click(next30);
    expect(allDeadlines).toHaveAttribute('aria-pressed', 'false');
    expect(next30).toHaveAttribute('aria-pressed', 'true');
  });

  it('filters by region, level, launch year, active period, and source', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    await user.selectOptions(screen.getByLabelText('Регион программы'), 'Москва');
    await user.selectOptions(screen.getByLabelText('Уровень программы'), 'regional');
    await user.selectOptions(screen.getByLabelText('Год запуска'), '2021');
    await user.selectOptions(screen.getByLabelText('Период действия'), 'activeNow');
    await user.selectOptions(screen.getByLabelText('Источник программы'), 'impact-hub');

    expect(getRenderedProgramTitles()).toEqual(['Eco Impact Lab']);
  });

  it('filters by funding availability and amount interval', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    await user.selectOptions(screen.getByLabelText('Наличие суммы'), 'withFunding');
    await user.clear(screen.getByLabelText('Сумма от, ₽'));
    await user.type(screen.getByLabelText('Сумма от, ₽'), '3500000');
    await user.clear(screen.getByLabelText('Сумма до, ₽'));
    await user.type(screen.getByLabelText('Сумма до, ₽'), '4500000');

    expect(screen.getByRole('heading', { name: 'Старт-ИИ' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Eco Impact Lab' })).not.toBeInTheDocument();
  });

  it('offers relevance only for a non-empty query and restores deadline sorting when cleared', async () => {
    const user = userEvent.setup();
    renderProgramsTab();

    expect(screen.queryByRole('option', { name: 'Релевантность' })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Поиск'), 'ИИ');
    expect(screen.getByRole('option', { name: 'Релевантность' })).toBeInTheDocument();
    expect(screen.getByLabelText('Сортировка')).toHaveValue('relevance');
    await user.click(screen.getByRole('button', { name: 'Очистить поиск' }));
    expect(screen.getByLabelText('Сортировка')).toHaveValue('deadline');
  });

  it('resets every filter while preserving an explicit non-relevance sort', async () => {
    const user = userEvent.setup();
    renderProgramsTab();
    await user.selectOptions(screen.getByLabelText('Сортировка'), 'funding');
    await user.selectOptions(screen.getByLabelText('Регион программы'), 'Москва');
    await user.selectOptions(screen.getByLabelText('Наличие суммы'), 'withFunding');
    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));

    expect(screen.getByLabelText('Регион программы')).toHaveValue('Все регионы');
    expect(screen.getByLabelText('Наличие суммы')).toHaveValue('all');
    expect(screen.getByLabelText('Сортировка')).toHaveValue('funding');
  });

  it('shows mature program metadata without rendering every field', () => {
    renderProgramsTab();
    const card = screen.getByRole('article', { name: 'Старт-ИИ' });

    expect(within(card).getByText('Федеральная')).toBeInTheDocument();
    expect(within(card).getByText('Россия')).toBeInTheDocument();
    expect(within(card).getByText('до 4 млн ₽')).toBeInTheDocument();
    expect(within(card).getByText(/1 июня 2026/)).toBeInTheDocument();
    expect(within(card).getByText('Обновлено 24 июня 2026')).toBeInTheDocument();
  });

  it('toggles a program favorite without opening the drawer', async () => {
    const user = userEvent.setup();
    const onToggleFavoriteProgram = vi.fn();
    const onOpenProgram = vi.fn();
    renderProgramsTab({
      favoriteProgramIds: ['fasie-start-ai'],
      onToggleFavoriteProgram,
      onOpenProgram
    });

    const favorite = screen.getByRole('button', { name: 'Удалить Старт-ИИ из избранного' });
    expect(favorite).toHaveAttribute('aria-pressed', 'true');
    await user.click(favorite);
    expect(onToggleFavoriteProgram).toHaveBeenCalledWith('fasie-start-ai');
    expect(onOpenProgram).not.toHaveBeenCalled();
  });

  it('distinguishes an empty dataset from empty filtered results', async () => {
    const user = userEvent.setup();
    const view = renderProgramsTab({ programs: [] });
    expect(screen.getByText('Каталог пока пуст')).toBeInTheDocument();

    view.unmount();
    renderProgramsTab();
    await user.type(screen.getByLabelText('Поиск'), 'несуществующая программа');
    expect(screen.getByText('По вашему запросу ничего не найдено')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сбросить фильтры' })).toBeInTheDocument();
  });
});
