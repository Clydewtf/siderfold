import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from './App';
import { programs, sources } from './data/seed';

describe('App navigation', () => {
  it('shows the three MVP tabs', () => {
    render(<App />);

    expect(screen.getByRole('tab', { name: 'Главная' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Источники' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Каталог' })).toBeInTheDocument();
  });

  it('switches tabs without reloading the page', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Источники' }));
    expect(screen.getByRole('heading', { name: 'Источники программ' })).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    expect(screen.getByRole('heading', { name: 'Каталог программ' })).toBeInTheDocument();
  });

  it('renders clickable Stargate brand and primary navigation labels', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Каталог' }));
    expect(screen.getByRole('heading', { name: 'Каталог программ' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Stargate - на главную' }));
    expect(screen.getByRole('heading', { name: /Единая база программ поддержки/i })).toBeInTheDocument();

    expect(screen.getByRole('tab', { name: 'Главная' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Источники' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Каталог' })).toBeInTheDocument();
    expect(screen.queryByText('Frontend-only MVP на seed-данных')).not.toBeInTheDocument();
    expect(screen.getByText('MVP seed')).toBeInTheDocument();
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

  it('supports keyboard navigation across tabs', async () => {
    const user = userEvent.setup();
    render(<App />);

    const homeTab = screen.getByRole('tab', { name: 'Главная' });
    const sourcesTab = screen.getByRole('tab', { name: 'Источники' });
    const programsTab = screen.getByRole('tab', { name: 'Каталог' });

    homeTab.focus();
    await user.keyboard('{ArrowRight}');
    expect(sourcesTab).toHaveFocus();
    expect(sourcesTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'Источники программ' })).toBeInTheDocument();

    await user.keyboard('{End}');
    expect(programsTab).toHaveFocus();
    expect(programsTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'Каталог программ' })).toBeInTheDocument();

    await user.keyboard('{Home}');
    expect(homeTab).toHaveFocus();
    expect(homeTab).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{ArrowLeft}');
    expect(programsTab).toHaveFocus();
    expect(programsTab).toHaveAttribute('aria-selected', 'true');
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
