import type { PersistedAppState, ThemePreference, Topic } from '../types';

export const APP_STATE_STORAGE_KEY = 'siderfold:user-state';
export const APP_STATE_STORAGE_VERSION = 1;
const RECENT_PROGRAM_LIMIT = 12;
const topics: readonly Topic[] = [
  'Наука', 'Образование', 'Технологии', 'Социальные проекты', 'Культура',
  'Предпринимательство', 'Экология', 'ИИ', 'Региональное развитие'
];

export type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export const DEFAULT_PERSISTED_APP_STATE: PersistedAppState = {
  theme: 'system',
  favoriteProgramIds: [],
  favoriteSourceIds: [],
  recentProgramIds: [],
  preferredRegions: [],
  preferredTopics: [],
  display: { density: 'comfortable', showDataQuality: true, reduceMotion: false }
};

function defaults(): PersistedAppState {
  return {
    ...DEFAULT_PERSISTED_APP_STATE,
    favoriteProgramIds: [],
    favoriteSourceIds: [],
    recentProgramIds: [],
    preferredRegions: [],
    preferredTopics: [],
    display: { ...DEFAULT_PERSISTED_APP_STATE.display }
  };
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function strings(value: unknown, limit = Infinity): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(new Set(
    value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
  )).slice(0, limit);
}

function theme(value: unknown): value is ThemePreference {
  return value === 'light' || value === 'dark' || value === 'system';
}

function normalize(value: unknown): PersistedAppState {
  if (!record(value)) return defaults();
  const display = record(value.display) ? value.display : {};
  return {
    theme: theme(value.theme) ? value.theme : 'system',
    favoriteProgramIds: strings(value.favoriteProgramIds),
    favoriteSourceIds: strings(value.favoriteSourceIds),
    recentProgramIds: strings(value.recentProgramIds, RECENT_PROGRAM_LIMIT),
    preferredRegions: strings(value.preferredRegions),
    preferredTopics: strings(value.preferredTopics).filter(
      (item): item is Topic => topics.includes(item as Topic)
    ),
    display: {
      density: display.density === 'compact' ? 'compact' : 'comfortable',
      showDataQuality: typeof display.showDataQuality === 'boolean' ? display.showDataQuality : true,
      reduceMotion: typeof display.reduceMotion === 'boolean' ? display.reduceMotion : false
    }
  };
}

function migrate(value: unknown): PersistedAppState {
  if (!record(value)) return defaults();
  if (value.version === APP_STATE_STORAGE_VERSION) return normalize(value.state);
  if (!('version' in value)) {
    return normalize({
      theme: value.theme,
      favoriteProgramIds: value.favoritePrograms,
      favoriteSourceIds: value.favoriteSources,
      recentProgramIds: value.recentPrograms,
      preferredRegions: value.preferredRegions,
      preferredTopics: value.preferredTopics,
      display: value.display
    });
  }
  return defaults();
}

export function getBrowserStorage(): StorageLike | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadPersistedAppState(storage: StorageLike | null): PersistedAppState {
  if (!storage) return defaults();
  try {
    const raw = storage.getItem(APP_STATE_STORAGE_KEY);
    return raw === null ? defaults() : migrate(JSON.parse(raw));
  } catch {
    return defaults();
  }
}

export function savePersistedAppState(storage: StorageLike | null, state: PersistedAppState): boolean {
  if (!storage) return false;
  try {
    storage.setItem(APP_STATE_STORAGE_KEY, JSON.stringify({
      version: APP_STATE_STORAGE_VERSION,
      state: normalize(state)
    }));
    return true;
  } catch {
    return false;
  }
}

export function clearPersistedAppState(storage: StorageLike | null): boolean {
  if (!storage) return false;
  try {
    storage.removeItem(APP_STATE_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}
