import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { APP_STATE_STORAGE_KEY, type StorageLike } from '../lib/storage';
import { AppStateProvider, useAppState } from './AppStateProvider';

function memory(initial?: string): StorageLike {
  const values = new Map<string, string>();
  if (initial) values.set(APP_STATE_STORAGE_KEY, initial);
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key)
  };
}

function Harness() {
  const { state, resolvedTheme, actions } = useAppState();
  return (
    <>
      <output aria-label="tab">{state.activeTab}</output>
      <output aria-label="favorites">{state.favoriteProgramIds.join(',')}</output>
      <output aria-label="recents">{state.recentProgramIds.join(',')}</output>
      <output aria-label="theme">{state.theme}/{resolvedTheme}</output>
      <output aria-label="notice">{state.backendNotice?.message ?? ''}</output>
      <button onClick={() => actions.navigate('profile')}>profile</button>
      <button onClick={() => actions.toggleFavoriteProgram('p1')}>favorite</button>
      <button onClick={() => actions.openProgram('p1')}>open p1</button>
      <button onClick={() => actions.openProgram('p2')}>open p2</button>
      <button onClick={() => actions.setTheme('dark')}>dark</button>
      <button onClick={() => actions.setDensity('compact')}>compact</button>
      <button onClick={() => actions.setReduceMotion(true)}>less motion</button>
      <button onClick={() => actions.requestBackendFeature('profileSync')}>sync</button>
    </>
  );
}

describe('AppStateProvider', () => {
  it('hydrates persisted state and keeps navigation transient', () => {
    const storage = memory(JSON.stringify({
      version: 1,
      state: {
        theme: 'dark',
        favoriteProgramIds: ['p1'],
        favoriteSourceIds: [],
        recentProgramIds: ['p2'],
        preferredRegions: [],
        preferredTopics: [],
        display: { density: 'comfortable', showDataQuality: true, reduceMotion: false }
      }
    }));
    render(<AppStateProvider storage={storage}><Harness /></AppStateProvider>);
    expect(screen.getByLabelText('tab')).toHaveTextContent('home');
    expect(screen.getByLabelText('favorites')).toHaveTextContent('p1');
    expect(screen.getByLabelText('theme')).toHaveTextContent('dark/dark');
  });

  it('does not write on mount or navigation, then persists user data changes', async () => {
    const user = userEvent.setup();
    const storage = memory();
    render(<AppStateProvider storage={storage}><Harness /></AppStateProvider>);
    expect(storage.getItem(APP_STATE_STORAGE_KEY)).toBeNull();
    await user.click(screen.getByText('profile'));
    expect(storage.getItem(APP_STATE_STORAGE_KEY)).toBeNull();
    await user.click(screen.getByText('favorite'));
    await waitFor(() => expect(storage.getItem(APP_STATE_STORAGE_KEY)).toContain('"p1"'));
  });

  it('deduplicates recents and keeps newest first', async () => {
    const user = userEvent.setup();
    render(<AppStateProvider storage={memory()}><Harness /></AppStateProvider>);
    await user.click(screen.getByText('open p1'));
    await user.click(screen.getByText('open p2'));
    await user.click(screen.getByText('open p1'));
    expect(screen.getByLabelText('recents')).toHaveTextContent('p1,p2');
  });

  it('applies theme and display settings to the document root', async () => {
    const user = userEvent.setup();
    render(<AppStateProvider storage={memory()}><Harness /></AppStateProvider>);
    await user.click(screen.getByText('dark'));
    await user.click(screen.getByText('compact'));
    await user.click(screen.getByText('less motion'));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(document.documentElement).toHaveAttribute('data-density', 'compact');
    expect(document.documentElement).toHaveAttribute('data-reduced-motion', 'true');
  });

  it('exposes honest backend status as state', async () => {
    const user = userEvent.setup();
    render(<AppStateProvider storage={memory()}><Harness /></AppStateProvider>);
    await user.click(screen.getByText('sync'));
    expect(screen.getByLabelText('notice')).toHaveTextContent(
      'Синхронизация появится после подключения backend.'
    );
  });
});
