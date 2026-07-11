import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from './App';
import { programs, sources } from './data/seed';
import { APP_VERSION } from './version';

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
    expect(screen.getByRole('heading', { name: /Единая база программ поддержки/i })).toBeInTheDocument();

    expect(screen.getByRole('tab', { name: 'Главная' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Каталог' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Аналитика' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Источники' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Профиль' })).toBeInTheDocument();
    expect(screen.queryByText('Frontend-only MVP на seed-данных')).not.toBeInTheDocument();
    expect(screen.getByText('MVP seed')).toBeInTheDocument();
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
});
