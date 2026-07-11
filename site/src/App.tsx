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

  useGsapEntrance(rootRef, state.activeTab);

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
        {state.activeTab === 'programs' ? <ProgramsTab sources={sources} programs={programs} /> : null}
        {state.activeTab === 'analytics' ? <AnalyticsTab /> : null}
        {state.activeTab === 'sources' ? <SourcesTab sources={sources} programs={programs} /> : null}
        {state.activeTab === 'profile' ? <ProfileTab /> : null}
      </section>
      <ProgramDrawer
        program={selectedProgram}
        source={selectedSource}
        onClose={actions.closeProgram}
      />
    </AppShell>
  );
}

export default function App() {
  return <AppStateProvider><AppContent /></AppStateProvider>;
}
