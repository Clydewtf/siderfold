import { useLayoutEffect, useRef, type RefObject } from 'react';
import { programs, sources } from './data/seed';
import { createCatalogApiClient, type CatalogApiClient } from './data-access/catalogApi';
import { getRuntimeConfig, type DataMode } from './data-access/runtime';
import { usePublicCatalog, usePublicProgram } from './data-access/usePublicCatalog';
import { AnalyticsTab } from './components/AnalyticsTab';
import { ApiHomeTab } from './components/ApiHomeTab';
import { ApiProgramDrawer } from './components/ApiProgramDrawer';
import { ApiProgramsTab } from './components/ApiProgramsTab';
import { ApiSourcesTab } from './components/ApiSourcesTab';
import { ApiUnavailableTab } from './components/ApiUnavailableTab';
import { AppShell } from './components/AppShell';
import { HomeTab } from './components/HomeTab';
import { ProfileTab } from './components/ProfileTab';
import { ProgramDrawer } from './components/ProgramDrawer';
import { ProgramsTab } from './components/ProgramsTab';
import { SourcesTab } from './components/SourcesTab';
import { useGsapEntrance } from './motion/useGsapEntrance';
import { AppStateProvider, useAppState } from './state/AppStateProvider';
import type { TabId } from './types';

function useContentEffects(rootRef: RefObject<HTMLElement | null>, activeTab: TabId, reduceMotion: boolean) {
  const scrollPositionsRef = useRef<Partial<Record<TabId, number>>>({});
  const previousTabRef = useRef(activeTab);

  useLayoutEffect(() => {
    scrollPositionsRef.current[previousTabRef.current] = window.scrollY;
    window.scrollTo({ top: scrollPositionsRef.current[activeTab] ?? 0, behavior: 'auto' });
    previousTabRef.current = activeTab;
  }, [activeTab]);

  useGsapEntrance(rootRef, activeTab, reduceMotion);
}

function SeedAppContent() {
  const rootRef = useRef<HTMLElement>(null);
  const { state, actions } = useAppState();
  useContentEffects(rootRef, state.activeTab, state.display.reduceMotion);

  const selectedProgram = programs.find((program) => program.id === state.selectedProgramId) ?? null;
  const selectedSource = selectedProgram
    ? sources.find((source) => source.id === selectedProgram.sourceId) ?? null
    : null;

  return (
    <AppShell activeTab={state.activeTab} onTabChange={actions.navigate} dataMode="seed">
      <section ref={rootRef}>
        {state.activeTab === 'home' ? (
          <HomeTab
            sources={sources}
            programs={programs}
            onOpenPrograms={() => actions.navigate('programs')}
            onOpenAnalytics={() => actions.navigate('analytics')}
            onOpenSources={() => actions.navigate('sources')}
            onOpenProgram={(program) => actions.openProgram(program.id)}
          />
        ) : null}
        {state.activeTab === 'programs' ? (
          <ProgramsTab
            sources={sources}
            programs={programs}
            favoriteProgramIds={state.favoriteProgramIds}
            showDataQuality={state.display.showDataQuality}
            onToggleFavoriteProgram={actions.toggleFavoriteProgram}
            onOpenProgram={(program) => actions.openProgram(program.id)}
          />
        ) : null}
        {state.activeTab === 'analytics' ? (
          <AnalyticsTab
            sources={sources}
            programs={programs}
            exportNotice={state.backendNotice?.feature === 'reportExport' ? state.backendNotice.message : null}
            onRequestExport={() => actions.requestBackendFeature('reportExport')}
          />
        ) : null}
        {state.activeTab === 'sources' ? (
          <SourcesTab
            sources={sources}
            programs={programs}
            favoriteSourceIds={state.favoriteSourceIds}
            showDataQuality={state.display.showDataQuality}
            onToggleFavoriteSource={actions.toggleFavoriteSource}
            onOpenProgram={(program) => actions.openProgram(program.id)}
          />
        ) : null}
        {state.activeTab === 'profile' ? <ProfileTab programs={programs} sources={sources} /> : null}
      </section>
      {selectedProgram ? (
        <ProgramDrawer
          program={selectedProgram}
          source={selectedSource}
          isFavorite={state.favoriteProgramIds.includes(selectedProgram.id)}
          onToggleFavorite={() => actions.toggleFavoriteProgram(selectedProgram.id)}
          onClose={actions.closeProgram}
        />
      ) : null}
    </AppShell>
  );
}

function ApiAppContent({ client, configurationError }: { client: CatalogApiClient; configurationError: string | null }) {
  const rootRef = useRef<HTMLElement>(null);
  const { state, actions } = useAppState();
  const catalog = usePublicCatalog(client);
  const detail = usePublicProgram(client, state.selectedProgramId);
  useContentEffects(rootRef, state.activeTab, state.display.reduceMotion);

  const selectedListProgram = state.selectedProgramId
    ? catalog.programs?.items.find((program) => program.id === state.selectedProgramId) ?? null
    : null;
  const selectedProgram = detail.program ?? selectedListProgram;
  const unavailableDescription = configurationError
    ? 'Проверьте настройки режима данных и перезапустите приложение.'
    : 'Публичные данные временно недоступны.';

  return (
    <AppShell activeTab={state.activeTab} onTabChange={actions.navigate} dataMode="api">
      <section ref={rootRef}>
        {configurationError ? (
          <ApiUnavailableTab title="Публичный режим недоступен" description={unavailableDescription} />
        ) : null}
        {!configurationError && state.activeTab === 'home' ? (
          <ApiHomeTab
            programs={catalog.programs?.items ?? []}
            programTotal={catalog.programs?.total ?? 0}
            sourceTotal={catalog.sources?.total ?? 0}
            loading={catalog.programsLoading}
            error={catalog.programsError}
            metadataError={catalog.metadataError}
            onOpenPrograms={() => actions.navigate('programs')}
            onOpenSources={() => actions.navigate('sources')}
            onOpenProgram={(program) => actions.openProgram(program.id)}
            onRetry={catalog.retry}
          />
        ) : null}
        {!configurationError && state.activeTab === 'programs' ? (
          <ApiProgramsTab
            page={catalog.programs}
            filters={catalog.filters}
            loading={catalog.programsLoading}
            metadataLoading={catalog.metadataLoading}
            error={catalog.programsError}
            metadataError={catalog.metadataError}
            favoriteProgramIds={state.favoriteProgramIds}
            onQueryChange={catalog.setQuery}
            onOpenProgram={(program) => actions.openProgram(program.id)}
            onToggleFavoriteProgram={actions.toggleFavoriteProgram}
            onRetry={catalog.retry}
          />
        ) : null}
        {!configurationError && state.activeTab === 'sources' ? (
          <ApiSourcesTab
            page={catalog.sources}
            loading={catalog.metadataLoading}
            error={catalog.metadataError}
            onRetry={catalog.retry}
          />
        ) : null}
        {!configurationError && state.activeTab === 'analytics' ? (
          <ApiUnavailableTab title="Аналитика" description="Публичный API пока предоставляет каталог и источники программ." />
        ) : null}
        {!configurationError && state.activeTab === 'profile' ? (
          <ApiUnavailableTab title="Профиль" description="Личные функции не входят в публичный режим каталога." />
        ) : null}
      </section>
      {state.selectedProgramId ? (
        <ApiProgramDrawer
          program={selectedProgram}
          loading={detail.loading}
          error={detail.error}
          isFavorite={Boolean(selectedProgram && state.favoriteProgramIds.includes(selectedProgram.id))}
          onToggleFavorite={() => {
            if (selectedProgram) actions.toggleFavoriteProgram(selectedProgram.id);
          }}
          onRetry={detail.retry}
          onClose={actions.closeProgram}
        />
      ) : null}
    </AppShell>
  );
}

export type AppProps = {
  dataMode?: DataMode;
  apiClient?: CatalogApiClient;
};

export default function App({ dataMode, apiClient }: AppProps = {}) {
  const runtime = getRuntimeConfig();
  const mode = dataMode ?? runtime.mode;
  const client = apiClient ?? createCatalogApiClient({ baseUrl: runtime.apiBaseUrl });

  return (
    <AppStateProvider>
      {mode === 'seed' ? <SeedAppContent /> : <ApiAppContent client={client} configurationError={dataMode ? null : runtime.configurationError} />}
    </AppStateProvider>
  );
}
