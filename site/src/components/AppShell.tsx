import type { KeyboardEvent, ReactNode } from 'react';
import { BarChart3, Database, Home } from 'lucide-react';

export type TabId = 'home' | 'sources' | 'programs';

const tabs: { id: TabId; label: string; icon: typeof Home }[] = [
  { id: 'home', label: 'Главная', icon: Home },
  { id: 'sources', label: 'Источники', icon: Database },
  { id: 'programs', label: 'Каталог', icon: BarChart3 }
];

function getTabId(tab: TabId) {
  return `app-tab-${tab}`;
}

function getPanelId(tab: TabId) {
  return `app-panel-${tab}`;
}

export function AppShell({
  activeTab,
  onTabChange,
  children
}: {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  children: ReactNode;
}) {
  function moveToTab(tab: TabId) {
    onTabChange(tab);
    document.getElementById(getTabId(tab))?.focus();
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    const lastIndex = tabs.length - 1;
    let nextIndex: number | null = null;

    if (event.key === 'ArrowRight') {
      nextIndex = currentIndex === lastIndex ? 0 : currentIndex + 1;
    }
    if (event.key === 'ArrowLeft') {
      nextIndex = currentIndex === 0 ? lastIndex : currentIndex - 1;
    }
    if (event.key === 'Home') {
      nextIndex = 0;
    }
    if (event.key === 'End') {
      nextIndex = lastIndex;
    }

    if (nextIndex === null) {
      return;
    }

    event.preventDefault();
    moveToTab(tabs[nextIndex].id);
  }

  return (
    <main className="min-h-screen w-full max-w-full overflow-x-clip bg-paper text-ink">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(circle_at_20%_10%,rgba(47,95,158,0.18),transparent_32%),radial-gradient(circle_at_80%_20%,rgba(164,106,77,0.18),transparent_26%),linear-gradient(180deg,#f7f2e8,#ece5d6)]" />
      <header className="sticky top-0 z-30 border-b border-ink/10 bg-paper/[0.82] backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <button
            type="button"
            onClick={() => onTabChange('home')}
            className="inline-flex items-center gap-3 text-left focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
            aria-label="Stargate - на главную"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-ink text-sm font-semibold text-white">S</span>
            <span className="grid">
              <span className="text-lg font-semibold text-ink">Stargate</span>
              <span className="w-fit rounded-full border border-ink/10 bg-white/70 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-normal text-graphite">
                MVP seed
              </span>
            </span>
          </button>
          <nav
            aria-label="Основные разделы"
            role="tablist"
            className="grid grid-cols-3 gap-1 rounded-full border border-ink/10 bg-white/70 p-1 shadow-sm sm:gap-2"
          >
            {tabs.map((tab, index) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              const tabId = getTabId(tab.id);
              const panelId = getPanelId(tab.id);
              return (
                <button
                  key={tab.id}
                  id={tabId}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={panelId}
                  tabIndex={isActive ? 0 : -1}
                  onClick={() => onTabChange(tab.id)}
                  onKeyDown={(event) => handleTabKeyDown(event, index)}
                  className={`inline-flex items-center justify-center gap-1 rounded-full px-2 py-2 text-sm font-semibold transition sm:gap-2 sm:px-3 ${
                    isActive ? 'bg-ink text-white shadow-sm' : 'text-graphite hover:bg-ink/5'
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <span className="sr-only sm:not-sr-only">{tab.label}</span>
                </button>
              );
            })}
          </nav>
        </div>
      </header>
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;

        return (
          <div
            key={tab.id}
            id={getPanelId(tab.id)}
            role="tabpanel"
            aria-labelledby={getTabId(tab.id)}
            hidden={!isActive}
            tabIndex={isActive ? 0 : -1}
            className="focus:outline-none"
          >
            {isActive ? children : null}
          </div>
        );
      })}
    </main>
  );
}
