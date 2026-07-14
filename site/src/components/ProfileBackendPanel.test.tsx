import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { AppStateProvider } from '../state/AppStateProvider';
import { ProfileBackendPanel } from './ProfileBackendPanel';

function renderBackendPanel() {
  return render(
    <AppStateProvider storage={null}>
      <ProfileBackendPanel />
    </AppStateProvider>
  );
}

describe('ProfileBackendPanel', () => {
  it('shows seven profile capabilities as demo states and announces the selected one', async () => {
    const user = userEvent.setup();
    renderBackendPanel();

    expect(screen.getAllByText('Демо-режим')).toHaveLength(7);
    expect(screen.getByRole('button', { name: 'Открыть данные профиля' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Открыть заявки' }));
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByRole('status')).toHaveTextContent(
      'Заявки будут доступны после подключения аккаунта и backend.'
    );
    expect(screen.queryByText(/ошибка|сбой|не удалось/i)).not.toBeInTheDocument();
  });
});
