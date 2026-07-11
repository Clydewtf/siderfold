import {
  createContext, useContext, useEffect, useMemo, useReducer, useRef, useState,
  type ReactNode
} from 'react';
import {
  getBrowserStorage, loadPersistedAppState, savePersistedAppState, type StorageLike
} from '../lib/storage';
import type {
  AppState, BackendFeature, CardDensity, PersistedAppState, ResolvedTheme,
  TabId, ThemePreference, Topic
} from '../types';

const RECENT_LIMIT = 12;
const backendMessages: Record<BackendFeature, string> = {
  signIn: 'Вход будет доступен после подключения аккаунтов.',
  registration: 'Регистрация будет доступна после подключения аккаунтов.',
  notifications: 'Серверные уведомления появятся после подключения backend.',
  documents: 'Документы будут доступны после подключения аккаунта.',
  applications: 'Заявки будут доступны после подключения аккаунта.',
  reportExport: 'Экспорт отчета появится после подключения backend.',
  profileSync: 'Синхронизация появится после подключения backend.'
};

type Action =
  | { type: 'navigate'; tab: TabId }
  | { type: 'openProgram'; programId: string }
  | { type: 'closeProgram' }
  | { type: 'toggleFavoriteProgram'; programId: string }
  | { type: 'toggleFavoriteSource'; sourceId: string }
  | { type: 'setTheme'; theme: ThemePreference }
  | { type: 'togglePreferredRegion'; region: string }
  | { type: 'togglePreferredTopic'; topic: Topic }
  | { type: 'setDensity'; density: CardDensity }
  | { type: 'setShowDataQuality'; value: boolean }
  | { type: 'setReduceMotion'; value: boolean }
  | { type: 'requestBackendFeature'; feature: BackendFeature }
  | { type: 'clearBackendNotice' };

export type AppStateActions = {
  navigate: (tab: TabId) => void;
  openProgram: (programId: string) => void;
  closeProgram: () => void;
  toggleFavoriteProgram: (programId: string) => void;
  toggleFavoriteSource: (sourceId: string) => void;
  setTheme: (theme: ThemePreference) => void;
  togglePreferredRegion: (region: string) => void;
  togglePreferredTopic: (topic: Topic) => void;
  setDensity: (density: CardDensity) => void;
  setShowDataQuality: (value: boolean) => void;
  setReduceMotion: (value: boolean) => void;
  requestBackendFeature: (feature: BackendFeature) => void;
  clearBackendNotice: () => void;
};

export type AppStateContextValue = {
  state: AppState;
  resolvedTheme: ResolvedTheme;
  actions: AppStateActions;
};

const Context = createContext<AppStateContextValue | null>(null);

function toggle(values: readonly string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function appState(persisted: PersistedAppState): AppState {
  return {
    ...persisted,
    display: { ...persisted.display },
    activeTab: 'home',
    selectedProgramId: null,
    backendNotice: null
  };
}

function persisted(state: AppState): PersistedAppState {
  return {
    theme: state.theme,
    favoriteProgramIds: state.favoriteProgramIds,
    favoriteSourceIds: state.favoriteSourceIds,
    recentProgramIds: state.recentProgramIds,
    preferredRegions: state.preferredRegions,
    preferredTopics: state.preferredTopics,
    display: state.display
  };
}

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'navigate':
      return { ...state, activeTab: action.tab, backendNotice: null };
    case 'openProgram':
      return {
        ...state,
        selectedProgramId: action.programId,
        recentProgramIds: [
          action.programId,
          ...state.recentProgramIds.filter((id) => id !== action.programId)
        ].slice(0, RECENT_LIMIT)
      };
    case 'closeProgram':
      return { ...state, selectedProgramId: null };
    case 'toggleFavoriteProgram':
      return { ...state, favoriteProgramIds: toggle(state.favoriteProgramIds, action.programId) };
    case 'toggleFavoriteSource':
      return { ...state, favoriteSourceIds: toggle(state.favoriteSourceIds, action.sourceId) };
    case 'setTheme':
      return { ...state, theme: action.theme };
    case 'togglePreferredRegion':
      return { ...state, preferredRegions: toggle(state.preferredRegions, action.region) };
    case 'togglePreferredTopic':
      return { ...state, preferredTopics: toggle(state.preferredTopics, action.topic) as Topic[] };
    case 'setDensity':
      return { ...state, display: { ...state.display, density: action.density } };
    case 'setShowDataQuality':
      return { ...state, display: { ...state.display, showDataQuality: action.value } };
    case 'setReduceMotion':
      return { ...state, display: { ...state.display, reduceMotion: action.value } };
    case 'requestBackendFeature':
      return {
        ...state,
        backendNotice: { feature: action.feature, message: backendMessages[action.feature] }
      };
    case 'clearBackendNotice':
      return { ...state, backendNotice: null };
  }
}

function useSystemDark() {
  const [dark, setDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches
  );
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = (event: MediaQueryListEvent) => setDark(event.matches);
    setDark(media.matches);
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);
  return dark;
}

export function AppStateProvider({
  children,
  storage
}: {
  children: ReactNode;
  storage?: StorageLike | null;
}) {
  const storageRef = useRef(storage === undefined ? getBrowserStorage() : storage);
  const [state, dispatch] = useReducer(
    reducer,
    storageRef.current,
    (value) => appState(loadPersistedAppState(value))
  );
  const didMount = useRef(false);
  const systemDark = useSystemDark();
  const resolvedTheme: ResolvedTheme =
    state.theme === 'system' ? (systemDark ? 'dark' : 'light') : state.theme;

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;
    root.dataset.density = state.display.density;
    root.dataset.reducedMotion = String(state.display.reduceMotion);
    root.style.colorScheme = resolvedTheme;
  }, [resolvedTheme, state.display.density, state.display.reduceMotion]);

  useEffect(() => {
    if (!didMount.current) {
      didMount.current = true;
      return;
    }
    savePersistedAppState(storageRef.current, persisted(state));
  }, [
    state.theme, state.favoriteProgramIds, state.favoriteSourceIds, state.recentProgramIds,
    state.preferredRegions, state.preferredTopics, state.display
  ]);

  const actions = useMemo<AppStateActions>(() => ({
    navigate: (tab) => dispatch({ type: 'navigate', tab }),
    openProgram: (programId) => dispatch({ type: 'openProgram', programId }),
    closeProgram: () => dispatch({ type: 'closeProgram' }),
    toggleFavoriteProgram: (programId) => dispatch({ type: 'toggleFavoriteProgram', programId }),
    toggleFavoriteSource: (sourceId) => dispatch({ type: 'toggleFavoriteSource', sourceId }),
    setTheme: (theme) => dispatch({ type: 'setTheme', theme }),
    togglePreferredRegion: (region) => dispatch({ type: 'togglePreferredRegion', region }),
    togglePreferredTopic: (topic) => dispatch({ type: 'togglePreferredTopic', topic }),
    setDensity: (density) => dispatch({ type: 'setDensity', density }),
    setShowDataQuality: (value) => dispatch({ type: 'setShowDataQuality', value }),
    setReduceMotion: (value) => dispatch({ type: 'setReduceMotion', value }),
    requestBackendFeature: (feature) => dispatch({ type: 'requestBackendFeature', feature }),
    clearBackendNotice: () => dispatch({ type: 'clearBackendNotice' })
  }), []);

  const value = useMemo(() => ({ state, resolvedTheme, actions }), [state, resolvedTheme, actions]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): AppStateContextValue {
  const value = useContext(Context);
  if (!value) throw new Error('useAppState must be used inside AppStateProvider');
  return value;
}
