import { readFileSync } from 'node:fs';
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

    expect(home).toHaveAttribute('tabindex', '0');

    home.focus();
    await user.keyboard('{ArrowRight}');
    expect(catalog).toHaveFocus();
    expect(onTabChange).toHaveBeenLastCalledWith('programs');

    await user.keyboard('{ArrowLeft}');
    expect(home).toHaveFocus();
    expect(onTabChange).toHaveBeenLastCalledWith('home');

    await user.keyboard('{End}');
    expect(profile).toHaveFocus();
    expect(onTabChange).toHaveBeenLastCalledWith('profile');

    await user.keyboard('{Home}');
    expect(home).toHaveFocus();
    expect(onTabChange).toHaveBeenLastCalledWith('home');
  });

  it('defines visible keyboard focus and safe native control defaults globally', () => {
    const styles = readFileSync('src/styles.css', 'utf8');

    expect(styles).toContain(':where(a, button, input, select, summary, [tabindex]):focus-visible');
    expect(styles).toContain('outline: 3px solid rgb(var(--color-cobalt));');
    expect(styles).toContain('button, input, select, summary { touch-action: manipulation; }');
    expect(styles).toContain("input[type='checkbox'] { accent-color: rgb(var(--color-cobalt)); min-height: 1.25rem; min-width: 1.25rem; }");
    expect(styles).toContain("button:disabled, [aria-disabled='true'] { cursor: not-allowed; opacity: .58; }");
    expect(styles).not.toContain('overflow-x: hidden');
  });
});
