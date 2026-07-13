import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { APP_STATE_STORAGE_KEY, type StorageLike } from '../lib/storage';
import { AppStateProvider } from '../state/AppStateProvider';
import { ProfileTab } from './ProfileTab';

function seededStorage(): StorageLike {
  const values = new Map([[APP_STATE_STORAGE_KEY, JSON.stringify({
    version: 1,
    state: {
      theme: 'system',
      favoriteProgramIds: ['fasie-start-ai'],
      favoriteSourceIds: ['fasie'],
      recentProgramIds: ['fasie-start-ai'],
      preferredRegions: [],
      preferredTopics: [],
      display: { density: 'comfortable', showDataQuality: true, reduceMotion: false }
    }
  })]]);
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key)
  };
}

function renderProfile() {
  return render(
    <AppStateProvider storage={seededStorage()}>
      <ProfileTab programs={programs} sources={sources} />
    </AppStateProvider>
  );
}

describe('ProfileTab', () => {
  it('presents a complete local personal workspace', () => {
    renderProfile();

    expect(screen.getAllByRole('heading', { level: 1, name: 'Профиль' })).toHaveLength(1);
    expect(screen.getByText('Личный кабинет агрегатора')).toBeInTheDocument();
    expect(screen.getByText('Избранное, история просмотра, предпочтения и настройки сохраняются только в этом браузере. Аккаунт и серверная синхронизация пока не подключены.')).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Демо-режим' })).toHaveTextContent('Демо-режим: локальные функции работают без регистрации.');
    for (const heading of [
      'Избранные программы',
      'Недавно просмотренные программы',
      'Избранные источники',
      'Отображение',
      'Предпочтительные регионы',
      'Предпочтительные тематики',
      'Аккаунт и backend'
    ]) {
      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText('Старт-ИИ').length).toBeGreaterThan(0);
    expect(screen.getByText('Фонд содействия инновациям')).toBeInTheDocument();
    expect(screen.getByText(/сохраняются только в этом браузере/i)).toBeInTheDocument();
  });

  it('uses the shared intro and demo notice contracts', () => {
    renderProfile();

    expect(screen.getByRole('banner')).toHaveClass('page-intro');
    const notice = screen.getByRole('complementary', { name: 'Демо-режим' });
    expect(notice).toHaveClass('demo-notice');
    expect(notice.parentElement).toHaveClass('min-w-0', 'lg:max-w-sm');
  });

  it('changes theme and display settings through app actions', async () => {
    const user = userEvent.setup();
    renderProfile();
    await user.selectOptions(screen.getByLabelText('Тема интерфейса'), 'dark');
    await user.selectOptions(screen.getByLabelText('Плотность карточек'), 'compact');
    await user.click(screen.getByLabelText('Уменьшить анимацию'));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(document.documentElement).toHaveAttribute('data-density', 'compact');
    expect(document.documentElement).toHaveAttribute('data-reduced-motion', 'true');
  });

  it('toggles preferred regions and topics with pressed state', async () => {
    const user = userEvent.setup();
    renderProfile();
    const region = screen.getByRole('button', { name: 'Предпочитать регион Москва' });
    const topic = screen.getByRole('button', { name: 'Предпочитать тематику ИИ' });
    await user.click(region);
    await user.click(topic);
    expect(region).toHaveAttribute('aria-pressed', 'true');
    expect(topic).toHaveAttribute('aria-pressed', 'true');
  });

  it('announces unavailable backend capabilities without error language', async () => {
    const user = userEvent.setup();
    renderProfile();
    await user.click(screen.getByRole('button', { name: 'Синхронизировать профиль' }));
    expect(screen.getByRole('status')).toHaveTextContent(
      'Синхронизация появится после подключения аккаунта и backend.'
    );
  });
});
