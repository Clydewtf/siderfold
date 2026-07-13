import { useMemo } from 'react';
import type { SupportProgram, SupportSource } from '../types';
import { buildProfileViewModel } from '../lib/profile';
import { useAppState } from '../state/AppStateProvider';
import { ProfileBackendPanel } from './ProfileBackendPanel';
import { ProfileCollections } from './ProfileCollections';
import { ProfilePreferences, ProfileSettings } from './ProfileControls';
import { DemoNotice, PageIntro } from './ui';

export function ProfileTab({
  programs,
  sources
}: {
  programs: readonly SupportProgram[];
  sources: readonly SupportSource[];
}) {
  const { state, actions } = useAppState();
  const profile = useMemo(
    () => buildProfileViewModel(state, programs, sources),
    [state, programs, sources]
  );
  const sourceById = useMemo(
    () => new Map(sources.map((source) => [source.id, source])),
    [sources]
  );

  return (
    <div className="page-container" data-page="profile">
      <PageIntro
        eyebrow="Личный кабинет агрегатора"
        title="Профиль"
        description="Избранное, история просмотра, предпочтения и настройки сохраняются только в этом браузере. Аккаунт и серверная синхронизация пока не подключены."
        aside={<DemoNotice>Демо-режим: локальные функции работают без регистрации.</DemoNotice>}
      />
      <div className="mt-10 grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
        <div className="min-w-0 break-words space-y-6">
          <ProfileCollections
            favoritePrograms={profile.favoritePrograms}
            favoriteSources={profile.favoriteSources}
            recentPrograms={profile.recentPrograms}
            sourceById={sourceById}
            onOpenProgram={(program) => actions.openProgram(program.id)}
            onToggleFavoriteProgram={actions.toggleFavoriteProgram}
            onToggleFavoriteSource={actions.toggleFavoriteSource}
            onOpenPrograms={() => actions.navigate('programs')}
            onOpenSources={() => actions.navigate('sources')}
          />
        </div>
        <aside className="min-w-0 break-words space-y-6 xl:sticky xl:top-28 xl:self-start">
          <ProfileSettings />
          <ProfilePreferences regionOptions={profile.regionOptions} topicOptions={profile.topicOptions} />
        </aside>
      </div>
      <div className="mt-6 min-w-0 break-words"><ProfileBackendPanel /></div>
    </div>
  );
}
