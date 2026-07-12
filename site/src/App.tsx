import { useRef } from 'react';
import { programs, sources } from './data/seed';
import { AppShell } from './components/AppShell';
import { AnalyticsTab } from './components/AnalyticsTab';
import { HomeTab } from './components/HomeTab';
import { ProfileTab } from './components/ProfileTab';
import { ProgramDrawer } from './components/ProgramDrawer';
import { ProgramsTab } from './components/ProgramsTab';
import { SourcesTab } from './components/SourcesTab';
import { useGsapEntrance } from './motion/useGsapEntrance';
import { AppStateProvider, useAppState } from './state/AppStateProvider';

function AppContent() {
  const rootRef = useRef<HTMLElement>(null);
  const { state, actions } = useAppState();
  const selectedProgram =
    programs.find((program) => program.id === state.selectedProgramId) ?? null;
  const selectedSource = selectedProgram
    ? sources.find((source) => source.id === selectedProgram.sourceId) ?? null
    : null;

  useGsapEntrance(rootRef, state.activeTab, state.display.reduceMotion);

  return (
    <AppShell activeTab={state.activeTab} onTabChange={actions.navigate}>
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
        {state.activeTab === 'analytics' ? <AnalyticsTab /> : null}
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
      <ProgramDrawer
        program={selectedProgram}
        source={selectedSource}
        isFavorite={selectedProgram ? state.favoriteProgramIds.includes(selectedProgram.id) : false}
        onToggleFavorite={() => {
          if (selectedProgram) actions.toggleFavoriteProgram(selectedProgram.id);
        }}
        onClose={actions.closeProgram}
      />
    </AppShell>
  );
}

export default function App() {
  return <AppStateProvider><AppContent /></AppStateProvider>;
}
