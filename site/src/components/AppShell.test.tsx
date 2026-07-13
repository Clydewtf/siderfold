import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from './AppShell';

describe('AppShell', () => {
  it('provides a skip link, one main landmark, product status, and roving tab navigation', async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();

    render(
      <AppShell activeTab="home" onTabChange={onTabChange}>
        <p>Содержимое главной страницы</p>
      </AppShell>
    );

    expect(screen.getByRole('link', { name: 'Перейти к содержимому' })).toHaveAttribute('href', '#main-content');
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content');
    expect(screen.getByText('Демо-режим')).toBeInTheDocument();
    expect(screen.getByText('v0.4.0')).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(5);

    const home = screen.getByRole('tab', { name: 'Главная' });
    const catalog = screen.getByRole('tab', { name: 'Каталог' });
    const profile = screen.getByRole('tab', { name: 'Профиль' });

    home.focus();
    await user.keyboard('{ArrowRight}');
    expect(catalog).toHaveFocus();
    expect(onTabChange).toHaveBeenLastCalledWith('programs');

    await user.keyboard('{End}');
    expect(profile).toHaveFocus();
    expect(onTabChange).toHaveBeenLastCalledWith('profile');

    await user.keyboard('{Home}');
    expect(home).toHaveFocus();
    expect(onTabChange).toHaveBeenLastCalledWith('home');
  });
});
