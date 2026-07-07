import { useRef, useState } from 'react';
import { programs, sources } from './data/seed';
import { AppShell, type TabId } from './components/AppShell';
import { HomeTab } from './components/HomeTab';
import { ProgramDrawer } from './components/ProgramDrawer';
import { ProgramsTab } from './components/ProgramsTab';
import { SourcesTab } from './components/SourcesTab';
import { useGsapEntrance } from './motion/useGsapEntrance';
import type { SupportProgram } from './types';

export default function App() {
  const rootRef = useRef<HTMLElement>(null);
  const [activeTab, setActiveTab] = useState<TabId>('home');
  const [selectedProgram, setSelectedProgram] = useState<SupportProgram | null>(null);
  const selectedSource = selectedProgram ? sources.find((source) => source.id === selectedProgram.sourceId) ?? null : null;

  useGsapEntrance(rootRef, activeTab);

  return (
    <AppShell activeTab={activeTab} onTabChange={setActiveTab}>
      <section ref={rootRef}>
        {activeTab === 'home' ? (
          <HomeTab
            sources={sources}
            programs={programs}
            onOpenPrograms={() => setActiveTab('programs')}
            onOpenSources={() => setActiveTab('sources')}
            onOpenProgram={setSelectedProgram}
          />
        ) : null}
        {activeTab === 'sources' ? <SourcesTab sources={sources} programs={programs} /> : null}
        {activeTab === 'programs' ? <ProgramsTab sources={sources} programs={programs} /> : null}
      </section>
      <ProgramDrawer program={selectedProgram} source={selectedSource} onClose={() => setSelectedProgram(null)} />
    </AppShell>
  );
}
