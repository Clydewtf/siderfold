import type { ProfileViewModel } from '../lib/profile';
import type { SupportProgram, SupportSource } from '../types';
import { EmptyState } from './ui';

export type ProfileCollectionsProps = Pick<
  ProfileViewModel,
  'favoritePrograms' | 'favoriteSources' | 'recentPrograms'
> & {
  sourceById: ReadonlyMap<string, SupportSource>;
  onOpenProgram: (program: SupportProgram) => void;
  onToggleFavoriteProgram: (programId: string) => void;
  onToggleFavoriteSource: (sourceId: string) => void;
  onOpenPrograms: () => void;
  onOpenSources: () => void;
};

export function ProfileCollections({
  favoritePrograms,
  favoriteSources,
  recentPrograms,
  sourceById,
  onOpenProgram,
  onToggleFavoriteProgram,
  onToggleFavoriteSource,
  onOpenPrograms,
  onOpenSources
}: ProfileCollectionsProps) {
  return (
    <>
      <section aria-labelledby="favorite-programs-title" className="profile-section">
        <div className="profile-section__heading">
          <div>
            <p className="eyebrow">Сохранено локально</p>
            <h2 id="favorite-programs-title">Избранные программы</h2>
          </div>
          <span aria-label={`Избранных программ: ${favoritePrograms.length}`} className="count-badge">
            {favoritePrograms.length}
          </span>
        </div>
        {favoritePrograms.length === 0 ? (
          <EmptyState title="Избранных программ пока нет" description="Добавляйте программы в каталоге — они сохранятся на этом устройстве.">
            <button type="button" className="button-secondary" onClick={onOpenPrograms}>Найти программы</button>
          </EmptyState>
        ) : (
          <ul data-density-grid className="profile-card-grid">
            {favoritePrograms.map((program) => (
              <li key={program.id} data-density-card className="profile-entity-card">
                <div className="min-w-0">
                  <p className="eyebrow">Источник: {sourceById.get(program.sourceId)?.name ?? 'не найден'}</p>
                  <h3 className="break-words text-xl font-semibold">{program.title}</h3>
                  <p className="mt-2 line-clamp-2 text-sm leading-6 text-graphite">{program.description}</p>
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  <button type="button" className="button-primary" onClick={() => onOpenProgram(program)} aria-label={`Открыть программу ${program.title}`}>Открыть</button>
                  <button type="button" className="button-secondary" onClick={() => onToggleFavoriteProgram(program.id)} aria-label={`Убрать программу ${program.title} из избранного`}>Убрать</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="recent-programs-title" className="profile-section">
        <div className="profile-section__heading">
          <div><p className="eyebrow">История на устройстве</p><h2 id="recent-programs-title">Недавно просмотренные программы</h2></div>
          <span aria-label={`Недавно просмотренных программ: ${recentPrograms.length}`} className="count-badge">{recentPrograms.length}</span>
        </div>
        {recentPrograms.length === 0 ? (
          <EmptyState title="История просмотра пока пуста" description="Откройте карточку программы — она появится здесь.">
            <button type="button" className="button-secondary" onClick={onOpenPrograms}>Найти программы</button>
          </EmptyState>
        ) : (
          <ul data-density-grid className="profile-card-grid">
            {recentPrograms.map((program) => <li key={program.id} data-density-card className="profile-entity-card">
              <p className="eyebrow">Источник: {sourceById.get(program.sourceId)?.name ?? 'не найден'}</p>
              <h3 className="mt-2 break-words text-xl font-semibold">{program.title}</h3>
              <button type="button" className="button-secondary mt-4" onClick={() => onOpenProgram(program)} aria-label={`Открыть программу ${program.title}`}>Открыть снова</button>
            </li>)}
          </ul>
        )}
      </section>

      <section aria-labelledby="favorite-sources-title" className="profile-section">
        <div className="profile-section__heading">
          <div><p className="eyebrow">Сохранено локально</p><h2 id="favorite-sources-title">Избранные источники</h2></div>
          <span aria-label={`Избранных источников: ${favoriteSources.length}`} className="count-badge">{favoriteSources.length}</span>
        </div>
        {favoriteSources.length === 0 ? (
          <EmptyState title="Избранных источников пока нет" description="Сохраняйте проверенные организации в разделе источников.">
            <button type="button" className="button-secondary" onClick={onOpenSources}>Смотреть источники</button>
          </EmptyState>
        ) : (
          <ul data-density-grid className="profile-card-grid">
            {favoriteSources.map((source) => <li key={source.id} data-density-card className="profile-entity-card">
              <p className="eyebrow">{source.type} · {source.region}</p>
              <h3 className="mt-2 break-words text-xl font-semibold">{source.name}</h3>
              <p className="mt-2 text-sm leading-6 text-graphite">{source.trustNote}</p>
              <button type="button" className="button-secondary mt-4" onClick={() => onToggleFavoriteSource(source.id)} aria-label={`Удалить ${source.name} из избранного`}>Убрать</button>
            </li>)}
          </ul>
        )}
      </section>
    </>
  );
}
