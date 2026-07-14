import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { FavoriteToggle } from './FavoriteToggle';

describe('FavoriteToggle', () => {
  it('uses a 44px star control with clear selected state and label', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const { rerender } = render(<FavoriteToggle itemName="Старт-ИИ" isFavorite={false} onToggle={onToggle} />);
    const button = screen.getByRole('button', { name: 'Добавить Старт-ИИ в избранное' });

    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(button).toHaveClass('h-11', 'w-11');
    expect(button.querySelector('svg')).not.toHaveClass('fill-amber-400');
    await user.click(button);
    expect(onToggle).toHaveBeenCalledOnce();

    rerender(<FavoriteToggle itemName="Старт-ИИ" isFavorite onToggle={onToggle} />);
    const selectedButton = screen.getByRole('button', { name: 'Удалить Старт-ИИ из избранного' });
    expect(selectedButton).toHaveAttribute('aria-pressed', 'true');
    expect(selectedButton.querySelector('svg')).toHaveClass('fill-amber-400');
  });
});
