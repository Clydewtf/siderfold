import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { programs, sources } from '../data/seed';
import { HomeTab } from './HomeTab';

function renderHome() {
  return render(
    <HomeTab
      sources={sources}
      programs={programs}
      onOpenPrograms={vi.fn()}
      onOpenAnalytics={vi.fn()}
      onOpenSources={vi.fn()}
      onOpenProgram={vi.fn()}
    />
  );
}

describe('HomeTab', () => {
  it('positions Siderfold as a mature demo platform without remote hero media', () => {
    const { container } = renderHome();
    expect(screen.getByText('Единая база поддержки стартапов')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Программы поддержки — в одном рабочем пространстве'
    );
    expect(screen.getByText(/каталог, источники и аналитика используют одну базу/i)).toBeInTheDocument();
    expect(screen.getByText(/Демо-режим/i)).toBeInTheDocument();
    expect(container.querySelector('[style*="picsum"], [class*="picsum"]')).toBeNull();
  });

  it('explains the aggregator and shows seed database scale', () => {
    renderHome();

    expect(screen.getByRole('heading', { name: 'Программы поддержки — в одном рабочем пространстве' })).toBeInTheDocument();
    expect(screen.getAllByText('30').length).toBeGreaterThan(0);
    expect(screen.getAllByText('10').length).toBeGreaterThan(0);
    expect(screen.getByText(/Ближайший дедлайн/i)).toBeInTheDocument();
  });

  it('routes quick actions and featured program clicks', async () => {
    const user = userEvent.setup();
    const onOpenPrograms = vi.fn();
    const onOpenAnalytics = vi.fn();
    const onOpenSources = vi.fn();
    const onOpenProgram = vi.fn();
    const firstFeaturedProgram = programs.find((program) => program.featured);

    expect(firstFeaturedProgram).toBeDefined();

    render(
      <HomeTab
        sources={sources}
        programs={programs}
        onOpenPrograms={onOpenPrograms}
        onOpenAnalytics={onOpenAnalytics}
        onOpenSources={onOpenSources}
        onOpenProgram={onOpenProgram}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Открыть каталог' }));
    await user.click(screen.getByRole('button', { name: 'Открыть аналитику' }));
    await user.click(screen.getByRole('button', { name: 'Смотреть источники' }));
    await user.click(screen.getAllByRole('button', { name: /Подробнее о программе/i })[0]);

    expect(onOpenPrograms).toHaveBeenCalledTimes(1);
    expect(onOpenAnalytics).toHaveBeenCalledTimes(1);
    expect(onOpenSources).toHaveBeenCalledTimes(1);
    expect(onOpenProgram).toHaveBeenCalledTimes(1);
    expect(onOpenProgram).toHaveBeenCalledWith(firstFeaturedProgram);
  });
});
