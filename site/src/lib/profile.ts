import type {
  PersistedAppState, SupportProgram, SupportSource, Topic
} from '../types';

export type ProfileViewModel = {
  favoritePrograms: readonly SupportProgram[];
  favoriteSources: readonly SupportSource[];
  recentPrograms: readonly SupportProgram[];
  regionOptions: readonly string[];
  topicOptions: readonly Topic[];
};

function resolveInOrder<T extends { id: string }>(
  ids: readonly string[],
  entities: readonly T[]
): T[] {
  const byId = new Map(entities.map((entity) => [entity.id, entity]));
  return Array.from(new Set(ids))
    .map((id) => byId.get(id))
    .filter((entity): entity is T => entity !== undefined);
}

export function buildProfileViewModel(
  state: PersistedAppState,
  programs: readonly SupportProgram[],
  sources: readonly SupportSource[]
): ProfileViewModel {
  const regionOptions = Array.from(new Set(
    programs.flatMap((program) => program.regions)
      .filter((region) => region !== 'Россия' && region !== 'Онлайн')
  )).sort((a, b) => a.localeCompare(b, 'ru'));
  const topicOptions = Array.from(new Set(
    programs.flatMap((program) => program.topics)
  )).sort((a, b) => a.localeCompare(b, 'ru')) as Topic[];

  return {
    favoritePrograms: resolveInOrder(state.favoriteProgramIds, programs),
    favoriteSources: resolveInOrder(state.favoriteSourceIds, sources),
    recentPrograms: resolveInOrder(state.recentProgramIds, programs),
    regionOptions,
    topicOptions
  };
}
