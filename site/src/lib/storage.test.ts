import { describe, expect, it } from 'vitest';
import type { PersistedAppState } from '../types';
import {
  APP_STATE_STORAGE_KEY,
  APP_STATE_STORAGE_VERSION,
  DEFAULT_PERSISTED_APP_STATE,
  clearPersistedAppState,
  loadPersistedAppState,
  savePersistedAppState,
  type StorageLike
} from './storage';

function memory(initial: Record<string, string> = {}): StorageLike {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key)
  };
}

describe('local state storage', () => {
  it('uses the Siderfold local storage namespace', () => {
    expect(APP_STATE_STORAGE_KEY).toBe('siderfold:user-state');
  });

  it('returns fresh defaults for absent storage and broken JSON', () => {
    expect(loadPersistedAppState(null)).toEqual(DEFAULT_PERSISTED_APP_STATE);
    const storage = memory({ [APP_STATE_STORAGE_KEY]: '{broken' });
    expect(loadPersistedAppState(storage)).toEqual(DEFAULT_PERSISTED_APP_STATE);
    expect(loadPersistedAppState(storage)).not.toBe(DEFAULT_PERSISTED_APP_STATE);
  });

  it('round-trips the v1 envelope', () => {
    const storage = memory();
    const state: PersistedAppState = {
      theme: 'dark',
      favoriteProgramIds: ['program-1'],
      favoriteSourceIds: ['source-1'],
      recentProgramIds: ['program-2', 'program-1'],
      preferredRegions: ['Красноярский край'],
      preferredTopics: ['Технологии'],
      display: { density: 'compact', showDataQuality: false, reduceMotion: true }
    };
    expect(savePersistedAppState(storage, state)).toBe(true);
    expect(JSON.parse(storage.getItem(APP_STATE_STORAGE_KEY) ?? '')).toEqual({
      version: APP_STATE_STORAGE_VERSION,
      state
    });
    expect(loadPersistedAppState(storage)).toEqual(state);
  });

  it('migrates unversioned data and removes duplicates', () => {
    const storage = memory({
      [APP_STATE_STORAGE_KEY]: JSON.stringify({
        theme: 'light',
        favoritePrograms: ['p1', 'p1', 8],
        favoriteSources: ['s1'],
        recentPrograms: ['p2', 'p1', 'p2'],
        preferredRegions: ['Татарстан', 'Татарстан'],
        preferredTopics: ['ИИ', 'Несуществующая тематика'],
        display: { density: 'compact', showDataQuality: false, reduceMotion: true }
      })
    });
    expect(loadPersistedAppState(storage)).toEqual({
      theme: 'light',
      favoriteProgramIds: ['p1'],
      favoriteSourceIds: ['s1'],
      recentProgramIds: ['p2', 'p1'],
      preferredRegions: ['Татарстан'],
      preferredTopics: ['ИИ'],
      display: { density: 'compact', showDataQuality: false, reduceMotion: true }
    });
  });

  it('normalizes invalid v1 fields and limits recents to twelve ids', () => {
    const ids = Array.from({ length: 15 }, (_, index) => 'p-' + index);
    const storage = memory({
      [APP_STATE_STORAGE_KEY]: JSON.stringify({
        version: 1,
        state: {
          theme: 'sepia',
          favoriteProgramIds: [null, 'p1'],
          favoriteSourceIds: 's1',
          recentProgramIds: ids,
          preferredRegions: ['', 'Москва'],
          preferredTopics: ['ИИ', 'Unknown'],
          display: { density: 'dense', showDataQuality: 'yes', reduceMotion: false }
        }
      })
    });
    expect(loadPersistedAppState(storage)).toEqual({
      ...DEFAULT_PERSISTED_APP_STATE,
      favoriteProgramIds: ['p1'],
      recentProgramIds: ids.slice(0, 12),
      preferredRegions: ['Москва'],
      preferredTopics: ['ИИ']
    });
  });

  it('falls back safely without rewriting an unknown future version', () => {
    const future = JSON.stringify({ version: 99, state: { theme: 'dark' } });
    const storage = memory({ [APP_STATE_STORAGE_KEY]: future });
    expect(loadPersistedAppState(storage)).toEqual(DEFAULT_PERSISTED_APP_STATE);
    expect(storage.getItem(APP_STATE_STORAGE_KEY)).toBe(future);
  });

  it('swallows unavailable storage reads and writes', () => {
    const unavailable: StorageLike = {
      getItem: () => { throw new DOMException('Blocked', 'SecurityError'); },
      setItem: () => { throw new DOMException('Full', 'QuotaExceededError'); },
      removeItem: () => { throw new DOMException('Blocked', 'SecurityError'); }
    };
    expect(loadPersistedAppState(unavailable)).toEqual(DEFAULT_PERSISTED_APP_STATE);
    expect(savePersistedAppState(unavailable, DEFAULT_PERSISTED_APP_STATE)).toBe(false);
    expect(clearPersistedAppState(unavailable)).toBe(false);
  });
});
