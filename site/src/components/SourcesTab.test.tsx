import { render, screen, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { programs, sources } from '../data/seed';
import { SourcesTab } from './SourcesTab';

function renderSourcesTab(overrides: Partial<ComponentProps<typeof SourcesTab>> = {}) {
  const props: ComponentProps<typeof SourcesTab> = {
    sources,
    programs,
    favoriteSourceIds: [],
    showDataQuality: true,
    onToggleFavoriteSource: vi.fn(),
    onOpenProgram: vi.fn(),
    ...overrides
  };
  return { ...render(<SourcesTab {...props} />), props };
}

describe('SourcesTab', () => {
  it('renders source cards with program counters', () => {
    renderSourcesTab();

    expect(screen.getByRole('heading', { name: 'Источники программ' })).toBeInTheDocument();
    expect(screen.getAllByText('Фонд Потанина').length).toBeGreaterThan(1);
    expect(screen.getAllByText('3 программы').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2 активные').length).toBeGreaterThan(0);
  });

  it('filters by source type and topic', async () => {
    const user = userEvent.setup();
    renderSourcesTab();

    await user.selectOptions(screen.getByLabelText('Тип источника'), 'Акселератор');
    expect(screen.getByRole('article', { name: /Impact Hub Moscow/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Выбрать источник Фонд Потанина/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'Impact Hub Moscow' }).length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText('Тематика источника'), 'Экология');
    expect(screen.getByRole('article', { name: /Impact Hub Moscow/i })).toBeInTheDocument();
  });

  it('opens selected source details with related programs and external link', async () => {
    const user = userEvent.setup();
    renderSourcesTab();

    await user.click(screen.getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));

    expect(screen.getAllByRole('heading', { name: 'Impact Hub Moscow' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Eco Impact Lab').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: 'Открыть сайт источника' })[0]).toHaveAttribute('href', 'https://impacthubmoscow.net');

    await user.click(screen.getByRole('button', { name: /Выбрать источник Фонд Потанина/i }));

    expect(screen.getAllByRole('heading', { name: 'Фонд Потанина' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Стипендиальный конкурс для магистрантов').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: 'Открыть сайт источника' })[0]).toHaveAttribute('href', 'https://fondpotanin.ru');
  });

  it('keeps desktop source details sticky inside the reserved right column', () => {
    renderSourcesTab();

    const desktopColumn = screen.getByTestId('desktop-source-details-column');
    const desktopDetails = screen.getByTestId('desktop-source-details');

    expect(desktopColumn).toHaveClass('hidden', 'lg:block', 'lg:w-[420px]', 'lg:self-stretch');
    expect(desktopDetails).toHaveClass('lg:sticky', 'lg:top-28', 'lg:w-[420px]');
    expect(desktopDetails.className).toContain('lg:max-h-[calc(100vh-8rem)]');
    expect(desktopDetails).toHaveClass('lg:overflow-y-auto');
  });

  it('pins source card actions to the bottom of equal-height cards', () => {
    renderSourcesTab();

    const impactCard = screen.getByTestId('source-card-impact-hub');
    const impactActions = screen.getByTestId('source-card-actions-impact-hub');

    expect(impactCard).toHaveClass('flex', 'h-full', 'flex-col');
    expect(impactActions).toHaveClass('mt-auto');
  });

  it('marks the selected source and separates select from external website actions', async () => {
    const user = userEvent.setup();
    renderSourcesTab();

    const impactCard = screen.getByRole('article', { name: /Impact Hub Moscow/i });
    await user.click(within(impactCard).getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));

    expect(within(impactCard).getByText('Выбран')).toBeInTheDocument();
    expect(within(impactCard).getByRole('link', { name: /Открыть сайт Impact Hub Moscow/i })).toHaveAttribute(
      'href',
      'https://impacthubmoscow.net'
    );
    expect(screen.getByRole('button', { name: /Смотреть программы Impact Hub Moscow/i })).toBeInTheDocument();
  });

  it('announces source detail updates', async () => {
    const user = userEvent.setup();
    renderSourcesTab();

    await user.click(screen.getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));

    expect(screen.getByRole('status')).toHaveTextContent('Выбран источник: Impact Hub Moscow');
  });

  it('announces found source counts as filters change, including zero results', async () => {
    const user = userEvent.setup();
    renderSourcesTab();

    const announcement = screen.getByText('Найдено 10 источников');
    expect(announcement).toHaveAttribute('aria-live', 'polite');

    await user.selectOptions(screen.getByLabelText('Тип источника'), 'Университет');
    expect(screen.getByText('Найдено 1 источников')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Уровень источника'), 'regional');
    expect(screen.getByText('Найдено 0 источников')).toBeInTheDocument();
  });

  it('falls back to a filtered source when filters exclude the selected source', async () => {
    const user = userEvent.setup();
    renderSourcesTab();

    await user.click(screen.getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));
    await user.selectOptions(screen.getByLabelText('Тип источника'), 'Фонд');

    expect(screen.queryByRole('article', { name: /Impact Hub Moscow/i })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Выбран источник: Фонд Потанина');

    const potaninCard = screen.getByRole('article', { name: /Фонд Потанина/i });
    expect(within(potaninCard).getByText('Выбран')).toBeInTheDocument();
    expect(screen.getAllByText('Стипендиальный конкурс для магистрантов').length).toBeGreaterThan(0);
  });

  it('exposes source favorites as pressed buttons and callbacks', async () => {
    const user = userEvent.setup();
    const onToggleFavoriteSource = vi.fn();
    renderSourcesTab({ favoriteSourceIds: ['fond-potanin'], onToggleFavoriteSource });
    expect(screen.getByRole('button', { name: 'Удалить Фонд Потанина из избранного' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Добавить Impact Hub Moscow в избранное' }));
    expect(onToggleFavoriteSource).toHaveBeenCalledWith('impact-hub');
  });

  it('filters sources by type, region, level, and topic', async () => {
    const user = userEvent.setup();
    renderSourcesTab();

    await user.selectOptions(screen.getByLabelText('Тип источника'), 'Акселератор');
    await user.selectOptions(screen.getByLabelText('Регион источника'), 'Москва и онлайн');
    await user.selectOptions(screen.getByLabelText('Уровень источника'), 'regional');
    await user.selectOptions(screen.getByLabelText('Тематика источника'), 'Экология');

    expect(screen.getByRole('article', { name: 'Impact Hub Moscow' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Фонд Потанина' })).not.toBeInTheDocument();
  });

  it('resets source filters from a filtered empty state', async () => {
    const user = userEvent.setup();
    renderSourcesTab();
    await user.selectOptions(screen.getByLabelText('Тип источника'), 'Университет');
    await user.selectOptions(screen.getByLabelText('Уровень источника'), 'regional');

    expect(screen.getByText('Источники по этим фильтрам не найдены')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры источников' }));
    expect(screen.getByRole('article', { name: 'Фонд Потанина' })).toBeInTheDocument();
  });

  it('renders source analytics from the shared analytics engine', () => {
    renderSourcesTab();
    const card = screen.getByRole('article', { name: 'Фонд содействия инновациям' });

    expect(within(card).getByText('3 программы')).toBeInTheDocument();
    expect(within(card).getByText('3 активные')).toBeInTheDocument();
    expect(within(card).getByText('24,5 млн ₽')).toBeInTheDocument();
    expect(within(card).getByText(/Полнота данных:/)).toBeInTheDocument();
    expect(within(card).getByText('10% базы')).toBeInTheDocument();
  });

  it('opens a related program through the shared app callback', async () => {
    const user = userEvent.setup();
    const onOpenProgram = vi.fn();
    renderSourcesTab({ onOpenProgram });

    await user.click(screen.getByRole('button', { name: 'Выбрать источник Impact Hub Moscow' }));
    await user.click(screen.getAllByRole('button', { name: 'Открыть программу Eco Impact Lab' })[0]);
    expect(onOpenProgram).toHaveBeenCalledWith(expect.objectContaining({ id: 'impact-hub-eco-impact' }));
  });

  it('shows source verification, coverage, related-program states, and database contribution', async () => {
    const user = userEvent.setup();
    renderSourcesTab();
    await user.click(screen.getByRole('button', { name: 'Выбрать источник Impact Hub Moscow' }));

    expect(screen.getAllByText('Региональная').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Москва и онлайн').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Проверено 10 июня 2026').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Вклад в базу:/).length).toBeGreaterThan(0);
  });

  it('distinguishes an empty source database from filtered results', () => {
    renderSourcesTab({ sources: [], programs: [] });
    expect(screen.getByText('База источников пока пуста')).toBeInTheDocument();
  });
});
