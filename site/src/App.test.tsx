import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { programs, sources } from './data/seed';
import { APP_VERSION } from './version';

vi.mock('./data/seed', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./data/seed')>();

  return {
    ...actual,
    programs: actual.programs.map((program) =>
      program.title === 'Музейная лаборатория'
        ? { ...program, documentUrls: ['not-a-url', 'ftp://example.org/rules.pdf'] }
        : program
    )
  };
});

describe('App navigation', () => {
  it('shows five primary tabs in product order', () => {
    render(<App />);
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Главная', 'Каталог', 'Аналитика', 'Источники', 'Профиль'
    ]);
  });

  it('switches every new shell section without reload', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Аналитика' }));
    expect(screen.getByRole('heading', { name: 'Аналитика мер поддержки' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Профиль' }));
    expect(screen.getByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
  });

  it('renders clickable Stargate brand and primary navigation labels', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    expect(screen.getByRole('heading', { name: 'Каталог программ' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Stargate - на главную' }));
    expect(screen.getByRole('heading', { name: 'Программы поддержки — в одном рабочем пространстве' })).toBeInTheDocument();

    expect(screen.getByRole('tab', { name: 'Главная' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Каталог' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Аналитика' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Источники' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Профиль' })).toBeInTheDocument();
    expect(screen.queryByText('Frontend-only MVP на seed-данных')).not.toBeInTheDocument();
    expect(screen.getByText('Демо-режим')).toBeInTheDocument();
    expect(screen.getByLabelText(`Версия ${APP_VERSION}`)).toHaveTextContent(`v${APP_VERSION}`);
  });

  it('associates the selected tab with its panel', async () => {
    const user = userEvent.setup();
    render(<App />);

    const homeTab = screen.getByRole('tab', { name: 'Главная' });
    const sourcesTab = screen.getByRole('tab', { name: 'Источники' });
    const homePanel = screen.getByRole('tabpanel', { name: 'Главная' });

    expect(homeTab).toHaveAttribute('aria-selected', 'true');
    expect(homeTab).toHaveAttribute('aria-controls', homePanel.id);
    expect(homePanel).toHaveAttribute('aria-labelledby', homeTab.id);
    expect(homeTab).toHaveAttribute('tabIndex', '0');
    expect(sourcesTab).toHaveAttribute('aria-selected', 'false');
    expect(sourcesTab).toHaveAttribute('tabIndex', '-1');

    await user.click(sourcesTab);

    const sourcesPanel = screen.getByRole('tabpanel', { name: 'Источники' });
    expect(sourcesTab).toHaveAttribute('aria-selected', 'true');
    expect(sourcesTab).toHaveAttribute('aria-controls', sourcesPanel.id);
    expect(sourcesPanel).toHaveAttribute('aria-labelledby', sourcesTab.id);
    expect(sourcesPanel).toHaveTextContent('Источники программ');
  });

  it('points every tab to an existing panel', () => {
    render(<App />);

    for (const tab of screen.getAllByRole('tab')) {
      const panelId = tab.getAttribute('aria-controls');

      expect(panelId).toBeTruthy();
      expect(document.getElementById(panelId ?? '')).toBeInTheDocument();
    }
  });

  it('supports automatic keyboard activation across five tabs', async () => {
    const user = userEvent.setup();
    render(<App />);
    const home = screen.getByRole('tab', { name: 'Главная' });
    const catalog = screen.getByRole('tab', { name: 'Каталог' });
    const profile = screen.getByRole('tab', { name: 'Профиль' });
    home.focus();
    await user.keyboard('{ArrowRight}');
    expect(catalog).toHaveFocus();
    expect(catalog).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{End}');
    expect(profile).toHaveFocus();
    await user.keyboard('{ArrowRight}');
    expect(home).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(profile).toHaveFocus();
  });

  it('opens program details from a featured Home card', async () => {
    const user = userEvent.setup();
    const firstFeaturedProgram = programs.find((program) => program.featured);

    expect(firstFeaturedProgram).toBeDefined();
    if (!firstFeaturedProgram) {
      throw new Error('Expected at least one featured program in seed data.');
    }

    const source = sources.find((item) => item.id === firstFeaturedProgram.sourceId);

    expect(source).toBeDefined();
    if (!source) {
      throw new Error('Expected featured program source in seed data.');
    }

    render(<App />);

    await user.click(screen.getAllByRole('button', { name: /Подробнее о программе/i })[0]);

    const dialog = screen.getByRole('dialog', { name: firstFeaturedProgram.title });
    expect(within(dialog).getByRole('heading', { name: firstFeaturedProgram.title })).toBeInTheDocument();
    expect(within(dialog).getByText(source.name)).toBeInTheDocument();
  });

  it('records a viewed program and toggles its favorite state in the shared drawer', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    await user.click(screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i }));
    const dialog = screen.getByRole('dialog', { name: 'Старт-ИИ' });
    const favorite = within(dialog).getByRole('button', { name: 'Добавить Старт-ИИ в избранное' });
    expect(favorite).toHaveAttribute('aria-pressed', 'false');
    await user.click(favorite);
    expect(favorite).toHaveAttribute('aria-pressed', 'true');
  });

  it('toggles a favorite directly from the catalog card and exposes it in profile', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    await user.click(screen.getByRole('button', { name: 'Добавить Старт-ИИ в избранное' }));
    expect(screen.getByRole('button', { name: 'Удалить Старт-ИИ из избранного' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('tab', { name: 'Профиль' }));
    expect(screen.getByText('Старт-ИИ')).toBeInTheDocument();
  });

  it('opens the shared program drawer from the profile', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    await user.click(screen.getByRole('button', { name: 'Добавить Старт-ИИ в избранное' }));
    await user.click(screen.getByRole('tab', { name: 'Профиль' }));
    await user.click(screen.getByRole('button', { name: 'Открыть программу Старт-ИИ' }));

    expect(screen.getByRole('dialog', { name: 'Старт-ИИ' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Удалить Старт-ИИ из избранного' })).toBeInTheDocument();
  });

  it('opens a source-related program and records it as recently viewed', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Источники' }));
    await user.click(screen.getByRole('button', { name: 'Выбрать источник Impact Hub Moscow' }));
    await user.click(screen.getAllByRole('button', { name: 'Открыть программу Eco Impact Lab' })[0]);
    expect(screen.getByRole('dialog', { name: 'Eco Impact Lab' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Закрыть детали' }));

    await user.click(screen.getByRole('tab', { name: 'Профиль' }));
    expect(screen.getByText('Eco Impact Lab')).toBeInTheDocument();
  });

  it('deduplicates a recently viewed program opened from catalog and source details', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    await user.click(screen.getByRole('button', { name: 'Подробнее о программе Eco Impact Lab' }));
    await user.click(screen.getByRole('button', { name: 'Закрыть детали' }));
    await user.click(screen.getByRole('tab', { name: 'Источники' }));
    await user.click(screen.getByRole('button', { name: 'Выбрать источник Impact Hub Moscow' }));
    await user.click(screen.getAllByRole('button', { name: 'Открыть программу Eco Impact Lab' })[0]);
    await user.click(screen.getByRole('button', { name: 'Закрыть детали' }));
    await user.click(screen.getByRole('tab', { name: 'Профиль' }));

    expect(screen.getAllByText('Eco Impact Lab')).toHaveLength(1);
  });

  it('restores local profile data after app remount', async () => {
    const user = userEvent.setup();
    const first = render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    await user.click(screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i }));
    await user.click(within(screen.getByRole('dialog', { name: 'Старт-ИИ' })).getByRole('button', {
      name: 'Добавить Старт-ИИ в избранное'
    }));
    await user.click(screen.getByRole('button', { name: 'Закрыть детали' }));
    await user.click(screen.getByRole('tab', { name: 'Источники' }));
    await user.click(screen.getByRole('button', {
      name: 'Добавить Фонд содействия инновациям в избранное'
    }));
    await user.click(screen.getByRole('tab', { name: 'Профиль' }));
    await user.selectOptions(screen.getByLabelText('Тема интерфейса'), 'dark');
    first.unmount();

    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Профиль' }));
    const favoriteProgramsSection = screen
      .getByRole('heading', { name: 'Избранные программы' })
      .closest<HTMLElement>('section');
    const recentProgramsSection = screen
      .getByRole('heading', { name: 'Недавно просмотренные программы' })
      .closest<HTMLElement>('section');
    const favoriteSourcesSection = screen
      .getByRole('heading', { name: 'Избранные источники' })
      .closest<HTMLElement>('section');

    expect(favoriteProgramsSection).not.toBeNull();
    expect(recentProgramsSection).not.toBeNull();
    expect(favoriteSourcesSection).not.toBeNull();
    expect(within(favoriteProgramsSection!).getByText('Старт-ИИ')).toBeInTheDocument();
    expect(within(recentProgramsSection!).getByText('Старт-ИИ')).toBeInTheDocument();
    expect(within(favoriteSourcesSection!).getByText('Фонд содействия инновациям')).toBeInTheDocument();
    expect(screen.getByLabelText('Тема интерфейса')).toHaveValue('dark');
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  });

  it('shows requirements, documents, source, and external link in shared program details', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
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

  it('moves focus into shared program details, traps tab focus, and restores focus on close', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Каталог' }));

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

  it('closes shared program details with Escape and restores focus to the opener', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Каталог' }));

    const openButton = screen.getByRole('button', { name: /Подробнее о программе Старт-ИИ/i });
    await user.click(openButton);

    expect(screen.getByRole('dialog', { name: 'Старт-ИИ' })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Старт-ИИ' })).not.toBeInTheDocument();
    expect(openButton).toHaveFocus();
  });

  it('shows document fallback in shared program details when all document URLs are invalid', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    await user.click(screen.getByRole('button', { name: /Подробнее о программе Музейная лаборатория/i }));

    const dialog = screen.getByRole('dialog', { name: 'Музейная лаборатория' });
    expect(within(dialog).getByText('Документы не приложены.')).toBeInTheDocument();
    expect(within(dialog).queryByRole('link', { name: /Документ/i })).not.toBeInTheDocument();
  });
});
