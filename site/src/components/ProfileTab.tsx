import type {
  BackendFeature,
  CardDensity,
  SupportProgram,
  SupportSource,
  ThemePreference
} from '../types';
import { useAppState } from '../state/AppStateProvider';
import { EmptyState } from './ui';

const backendActions: { feature: BackendFeature; label: string }[] = [
  { feature: 'signIn', label: 'Войти' },
  { feature: 'registration', label: 'Зарегистрироваться' },
  { feature: 'notifications', label: 'Настроить уведомления' },
  { feature: 'documents', label: 'Открыть документы' },
  { feature: 'applications', label: 'Открыть заявки' },
  { feature: 'reportExport', label: 'Экспортировать отчет' },
  { feature: 'profileSync', label: 'Синхронизировать профиль' }
];

export function ProfileTab({
  programs,
  sources
}: {
  programs: readonly SupportProgram[];
  sources: readonly SupportSource[];
}) {
  const { state, actions } = useAppState();
  const favoritePrograms = state.favoriteProgramIds
    .map((id) => programs.find((program) => program.id === id))
    .filter((item): item is SupportProgram => Boolean(item));
  const favoriteSources = state.favoriteSourceIds
    .map((id) => sources.find((source) => source.id === id))
    .filter((item): item is SupportSource => Boolean(item));
  const recentPrograms = state.recentProgramIds
    .map((id) => programs.find((program) => program.id === id))
    .filter((item): item is SupportProgram => Boolean(item));
  const regions = Array.from(new Set(programs.flatMap((program) => program.regions)))
    .filter((region) => region !== 'Россия' && region !== 'Онлайн')
    .sort((a, b) => a.localeCompare(b, 'ru'));
  const topics = Array.from(new Set(programs.flatMap((program) => program.topics)))
    .sort((a, b) => a.localeCompare(b, 'ru'));

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <p className="text-sm font-semibold uppercase tracking-[0.12em] text-cobalt">Локальный профиль</p>
      <h1 className="mt-3 text-4xl font-semibold">Профиль</h1>
      <p className="mt-4 max-w-2xl text-sm leading-6 text-graphite">
        Настройки сохраняются только на этом устройстве. Аккаунт и серверная синхронизация не подключены.
      </p>

      <section className="mt-10 grid gap-4 md:grid-cols-2">
        <label className="grid gap-2 text-sm font-semibold">
          Тема интерфейса
          <select
            value={state.theme}
            onChange={(event) => actions.setTheme(event.target.value as ThemePreference)}
            className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
          >
            <option value="system">Как в системе</option>
            <option value="light">Светлая</option>
            <option value="dark">Темная</option>
          </select>
        </label>
        <label className="grid gap-2 text-sm font-semibold">
          Плотность карточек
          <select
            value={state.display.density}
            onChange={(event) => actions.setDensity(event.target.value as CardDensity)}
            className="rounded-lg border border-ink/10 bg-white px-3 py-2 text-ink"
          >
            <option value="comfortable">Комфортная</option>
            <option value="compact">Компактная</option>
          </select>
        </label>
        <label className="flex items-center gap-3 text-sm font-semibold">
          <input
            type="checkbox"
            checked={state.display.showDataQuality}
            onChange={(event) => actions.setShowDataQuality(event.target.checked)}
          />
          Показывать качество данных
        </label>
        <label className="flex items-center gap-3 text-sm font-semibold">
          <input
            type="checkbox"
            checked={state.display.reduceMotion}
            onChange={(event) => actions.setReduceMotion(event.target.checked)}
          />
          Уменьшить анимацию
        </label>
      </section>

      <PreferenceButtons
        title="Предпочтительные регионы"
        values={regions}
        selected={state.preferredRegions}
        labelPrefix="Предпочитать регион"
        onToggle={actions.togglePreferredRegion}
      />
      <PreferenceButtons
        title="Предпочтительные тематики"
        values={topics}
        selected={state.preferredTopics}
        labelPrefix="Предпочитать тематику"
        onToggle={actions.togglePreferredTopic}
      />

      <EntityList title="Избранные программы" items={favoritePrograms.map((item) => item.title)} />
      <EntityList title="Избранные источники" items={favoriteSources.map((item) => item.name)} />
      <EntityList title="Недавно просмотренные" items={recentPrograms.map((item) => item.title)} />

      <section className="mt-10">
        <h2 className="text-2xl font-semibold">Возможности аккаунта</h2>
        <p className="mt-2 text-sm text-graphite">Демо-режим: эти действия требуют backend.</p>
        <div className="mt-4 flex flex-wrap gap-3">
          {backendActions.map((item) => (
            <button
              key={item.feature}
              type="button"
              onClick={() => actions.requestBackendFeature(item.feature)}
              className="rounded-lg border border-ink/10 bg-white px-4 py-2 text-sm font-semibold text-ink"
            >
              {item.label}
            </button>
          ))}
        </div>
        {state.backendNotice ? (
          <p role="status" className="mt-4 rounded-lg bg-cobalt/10 p-4 text-sm text-cobalt">
            {state.backendNotice.message}
          </p>
        ) : null}
      </section>
    </div>
  );
}

function PreferenceButtons<T extends string>({
  title,
  values,
  selected,
  labelPrefix,
  onToggle
}: {
  title: string;
  values: readonly T[];
  selected: readonly T[];
  labelPrefix: string;
  onToggle: (value: T) => void;
}) {
  return (
    <section className="mt-10">
      <h2 className="text-2xl font-semibold">{title}</h2>
      <div className="mt-4 flex flex-wrap gap-2">
        {values.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={selected.includes(value)}
            aria-label={labelPrefix + ' ' + value}
            onClick={() => onToggle(value)}
            className="rounded-full border border-ink/10 bg-white/70 px-3 py-2 text-sm font-semibold"
          >
            {value}
          </button>
        ))}
      </div>
    </section>
  );
}

function EntityList({ title, items }: { title: string; items: readonly string[] }) {
  return (
    <section className="mt-10">
      <h2 className="text-2xl font-semibold">{title}</h2>
      {items.length > 0 ? (
        <ul className="mt-4 grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <li key={item} className="rounded-lg border border-ink/10 bg-white/70 p-4">{item}</li>
          ))}
        </ul>
      ) : (
        <div className="mt-4">
          <EmptyState
            title={title + ': пока пусто'}
            description="Данные появятся после действий в каталоге или источниках."
          />
        </div>
      )}
    </section>
  );
}
