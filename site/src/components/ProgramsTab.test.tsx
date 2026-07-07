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
    render(<ProgramsTab sources={sources} programs={programs} />);

    await user.type(screen.getByLabelText('Поиск'), 'ИИ');
    expect(screen.getByText('Найдено: 4')).toBeInTheDocument();
    expect(getRenderedProgramTitles()).toEqual(expect.arrayContaining(['Индустриальный ИИ акселератор', 'Старт-ИИ']));
    expect(screen.queryByText('УМНИК')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Тип поддержки'), 'Акселерация');
    expect(screen.getByText('Найдено: 1')).toBeInTheDocument();
    expect(getRenderedProgramTitles()).toEqual(['Индустриальный ИИ акселератор']);
    expect(screen.queryByText('Старт-ИИ')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Сортировка'), 'funding');
    expect(screen.getByLabelText('Сортировка')).toHaveValue('funding');
  });

  it('sorts rendered program cards by funding amount', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} />);

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
    render(<ProgramsTab sources={sources} programs={programs} />);

    await user.type(screen.getByLabelText('Поиск'), 'несуществующая программа');
    expect(screen.getByText('Программы не найдены')).toBeInTheDocument();
  });

  it('shows active filter chips and resets filters', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} />);

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
      render(<ProgramsTab sources={sources} programs={programs} />);

      const details = screen.getByText('Фильтры').closest('details');

      await waitFor(() => expect(details).toHaveAttribute('open'));
      expect(screen.getByLabelText('Тип поддержки')).toBeInTheDocument();
      expect(screen.getByLabelText('Сортировка')).toBeInTheDocument();
    } finally {
      restoreMatchMedia();
    }
  });

  it('opens program details with requirements, documents, source, and external link', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} />);

    await user.click(screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i }));

    const dialog = screen.getByRole('dialog', { name: 'Старт-ИИ' });
    expect(within(dialog).getByText('Фонд содействия инновациям')).toBeInTheDocument();
    expect(within(dialog).getByText('Российское юридическое лицо')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Открыть первоисточник' })).toHaveAttribute(
      'href',
      'https://fasie.ru/programs/start-ai'
    );
    expect(within(dialog).getByRole('link', { name: /Документ 1/i })).toBeInTheDocument();
  });

  it('moves focus into program details, traps tab focus, and restores focus on close', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} />);

    const openButton = screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i });
    await user.click(openButton);

    const dialog = screen.getByRole('dialog', { name: 'Старт-ИИ' });
    const closeButton = within(dialog).getByRole('button', { name: 'Закрыть детали' });
    const documentLink = within(dialog).getByRole('link', { name: /Документ 1/i });
    expect(closeButton).toHaveFocus();

    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(documentLink).toHaveFocus();

    await user.click(closeButton);
    expect(screen.queryByRole('dialog', { name: 'Старт-ИИ' })).not.toBeInTheDocument();
    expect(openButton).toHaveFocus();
  });

  it('closes program details with Escape and restores focus to the opener', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} />);

    const openButton = screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i });
    await user.click(openButton);

    expect(screen.getByRole('dialog', { name: 'Старт-ИИ' })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Старт-ИИ' })).not.toBeInTheDocument();
    expect(openButton).toHaveFocus();
  });

  it('shows document fallback when all document URLs are invalid', async () => {
    const user = userEvent.setup();
    const programWithInvalidDocuments = {
      ...programs.find((program) => program.title === 'Старт-ИИ')!,
      documentUrls: ['not-a-url', 'ftp://example.org/rules.pdf']
    };

    render(<ProgramsTab sources={sources} programs={[programWithInvalidDocuments]} />);

    await user.click(screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i }));

    const dialog = screen.getByRole('dialog', { name: 'Старт-ИИ' });
    expect(within(dialog).getByText('Документы не приложены.')).toBeInTheDocument();
    expect(within(dialog).queryByRole('link', { name: /Документ/i })).not.toBeInTheDocument();
  });

  it('exposes deadline filter buttons as a pressed group', async () => {
    const user = userEvent.setup();
    render(<ProgramsTab sources={sources} programs={programs} />);

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
