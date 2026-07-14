import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { APP_STATE_STORAGE_KEY, type StorageLike } from '../lib/storage';
import { AppStateProvider } from '../state/AppStateProvider';
import { ProfilePreferences, ProfileSettings } from './ProfileControls';

function memory(): StorageLike {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key)
  };
}

function renderControls(storage: StorageLike) {
  return render(
    <AppStateProvider storage={storage}>
      <ProfileSettings />
      <ProfilePreferences regionOptions={['Москва']} topicOptions={['ИИ']} />
    </AppStateProvider>
  );
}

describe('ProfileControls', () => {
  it('keeps preference groups within the profile sidebar at wide breakpoints', () => {
    renderControls(memory());

    const regions = screen.getByRole('group', { name: 'Предпочтительные регионы' });
    const topics = screen.getByRole('group', { name: 'Предпочтительные тематики' });
    const groups = [regions, topics];

    expect(regions).toBeInTheDocument();
    expect(topics).toBeInTheDocument();
    expect(groups[0].parentElement).toHaveClass('xl:grid-cols-1');
    groups.forEach((group) => expect(group).toHaveClass('min-w-0'));
    expect(screen.getByRole('heading', { name: 'Предпочтительные регионы' })).toHaveClass('break-words');
    expect(screen.getByRole('heading', { name: 'Предпочтительные тематики' })).toHaveClass('break-words');
  });

  it('updates theme, density, data quality, motion, regions, and topics', async () => {
    const user = userEvent.setup();
    renderControls(memory());

    await user.selectOptions(screen.getByLabelText('Тема интерфейса'), 'dark');
    await user.selectOptions(screen.getByLabelText('Плотность карточек'), 'compact');
    await user.click(screen.getByLabelText('Показывать качество данных'));
    await user.click(screen.getByLabelText('Уменьшить анимацию'));
    await user.click(screen.getByRole('button', { name: 'Предпочитать регион Москва' }));
    await user.click(screen.getByRole('button', { name: 'Предпочитать тематику ИИ' }));

    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(document.documentElement).toHaveAttribute('data-density', 'compact');
    expect(document.documentElement).toHaveAttribute('data-reduced-motion', 'true');
    expect(screen.getByLabelText('Показывать качество данных')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Предпочитать регион Москва' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Предпочитать тематику ИИ' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('restores changed local controls from the same storage', async () => {
    const user = userEvent.setup();
    const storage = memory();
    const view = renderControls(storage);

    await user.selectOptions(screen.getByLabelText('Тема интерфейса'), 'dark');
    await user.selectOptions(screen.getByLabelText('Плотность карточек'), 'compact');
    await user.click(screen.getByLabelText('Показывать качество данных'));
    await user.click(screen.getByLabelText('Уменьшить анимацию'));
    await user.click(screen.getByRole('button', { name: 'Предпочитать регион Москва' }));
    await user.click(screen.getByRole('button', { name: 'Предпочитать тематику ИИ' }));
    view.unmount();

    renderControls(storage);

    expect(screen.getByLabelText('Тема интерфейса')).toHaveValue('dark');
    expect(screen.getByLabelText('Плотность карточек')).toHaveValue('compact');
    expect(screen.getByLabelText('Показывать качество данных')).not.toBeChecked();
    expect(screen.getByLabelText('Уменьшить анимацию')).toBeChecked();
    expect(screen.getByRole('button', { name: 'Предпочитать регион Москва' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Предпочитать тематику ИИ' })).toHaveAttribute('aria-pressed', 'true');
    expect(storage.getItem(APP_STATE_STORAGE_KEY)).toContain('"version":1');
  });
});
