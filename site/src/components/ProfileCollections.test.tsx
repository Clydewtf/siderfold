import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { programs, sources } from '../data/seed';
import { ProfileCollections } from './ProfileCollections';

describe('ProfileCollections', () => {
  it('anchors collection actions to the bottom of equal-height cards', () => {
    render(<ProfileCollections
      favoritePrograms={[programs[0]]}
      favoriteSources={[sources[0]]}
      recentPrograms={[programs[1]]}
      sourceById={new Map(sources.map((source) => [source.id, source]))}
      onOpenProgram={vi.fn()}
      onToggleFavoriteProgram={vi.fn()}
      onToggleFavoriteSource={vi.fn()}
      onOpenPrograms={vi.fn()}
      onOpenSources={vi.fn()}
    />);

    const openFavorite = screen.getByRole('button', { name: `Открыть программу ${programs[0].title}` });
    expect(openFavorite.closest('li')).toHaveClass('flex', 'h-full', 'flex-col');
    expect(openFavorite.parentElement).toHaveClass('mt-auto', 'pt-5');
    expect(screen.getByRole('button', { name: `Открыть программу ${programs[1].title}` }).parentElement).toHaveClass('mt-auto', 'pt-5');
    expect(screen.getByRole('button', { name: `Удалить ${sources[0].name} из избранного` }).parentElement).toHaveClass('mt-auto', 'pt-5');
  });

  it('renders useful program and source cards and delegates every local action', async () => {
    const user = userEvent.setup();
    const onOpenProgram = vi.fn();
    const onToggleFavoriteProgram = vi.fn();
    const onToggleFavoriteSource = vi.fn();
    render(<ProfileCollections
      favoritePrograms={[programs[0]]}
      favoriteSources={[sources[0]]}
      recentPrograms={[programs[1]]}
      sourceById={new Map(sources.map((source) => [source.id, source]))}
      onOpenProgram={onOpenProgram}
      onToggleFavoriteProgram={onToggleFavoriteProgram}
      onToggleFavoriteSource={onToggleFavoriteSource}
      onOpenPrograms={vi.fn()}
      onOpenSources={vi.fn()}
    />);

    expect(screen.getByRole('heading', { name: 'Избранные программы' })).toBeInTheDocument();
    expect(screen.getAllByText(`Источник: ${sources.find((source) => source.id === programs[0].sourceId)!.name}`).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: `Открыть программу ${programs[0].title}` }));
    await user.click(screen.getByRole('button', { name: `Убрать программу ${programs[0].title} из избранного` }));
    await user.click(screen.getByRole('button', { name: `Удалить ${sources[0].name} из избранного` }));
    expect(onOpenProgram).toHaveBeenCalledWith(programs[0]);
    expect(onToggleFavoriteProgram).toHaveBeenCalledWith(programs[0].id);
    expect(onToggleFavoriteSource).toHaveBeenCalledWith(sources[0].id);
  });

  it('offers catalog and source navigation from empty collections', async () => {
    const user = userEvent.setup();
    const onOpenPrograms = vi.fn();
    const onOpenSources = vi.fn();
    render(<ProfileCollections
      favoritePrograms={[]}
      favoriteSources={[]}
      recentPrograms={[]}
      sourceById={new Map()}
      onOpenProgram={vi.fn()}
      onToggleFavoriteProgram={vi.fn()}
      onToggleFavoriteSource={vi.fn()}
      onOpenPrograms={onOpenPrograms}
      onOpenSources={onOpenSources}
    />);
    await user.click(screen.getAllByRole('button', { name: 'Найти программы' })[0]);
    await user.click(screen.getByRole('button', { name: 'Смотреть источники' }));
    expect(onOpenPrograms).toHaveBeenCalledOnce();
    expect(onOpenSources).toHaveBeenCalledOnce();
  });
});
