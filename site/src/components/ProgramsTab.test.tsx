import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { programs, sources } from '../data/seed';
import { ProgramsTab } from './ProgramsTab';

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
  it('searches, filters, and sorts programs', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} onOpenProgram={vi.fn()} />);

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
    render(<ProgramsTab sources={sources} programs={programs} onOpenProgram={vi.fn()} />);

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
    render(<ProgramsTab sources={sources} programs={programs} onOpenProgram={vi.fn()} />);

    await user.type(screen.getByLabelText('Поиск'), 'несуществующая программа');
    expect(screen.getByText('Программы не найдены')).toBeInTheDocument();
  });

  it('shows active filter chips and resets filters', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} onOpenProgram={vi.fn()} />);

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
      render(<ProgramsTab sources={sources} programs={programs} onOpenProgram={vi.fn()} />);

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
    render(<ProgramsTab sources={sources} programs={programs} onOpenProgram={onOpenProgram} />);

    await user.click(screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i }));
    expect(onOpenProgram).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'fasie-start-ai', title: 'Старт-ИИ' })
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('exposes deadline filter buttons as a pressed group', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} onOpenProgram={vi.fn()} />);

    const deadlineGroup = screen.getByRole('group', { name: 'Дедлайн' });
    const allDeadlines = within(deadlineGroup).getByRole('button', { name: 'Все дедлайны' });
    const next30 = within(deadlineGroup).getByRole('button', { name: '30 дней' });

    expect(allDeadlines).toHaveAttribute('aria-pressed', 'true');
    expect(next30).toHaveAttribute('aria-pressed', 'false');

    await user.click(next30);
    expect(allDeadlines).toHaveAttribute('aria-pressed', 'false');
    expect(next30).toHaveAttribute('aria-pressed', 'true');
  });
});
