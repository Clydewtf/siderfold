import type { CardDensity, ThemePreference, Topic } from '../types';
import { useAppState } from '../state/AppStateProvider';

export function ProfileSettings() {
  const { state, actions } = useAppState();

  return (
    <section aria-labelledby="display-settings-title" className="profile-section">
      <div className="profile-section__heading">
        <div>
          <p className="eyebrow">На этом устройстве</p>
          <h2 id="display-settings-title">Отображение</h2>
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="field-label">
          Тема интерфейса
          <select
            value={state.theme}
            onChange={(event) => actions.setTheme(event.target.value as ThemePreference)}
          >
            <option value="system">Как в системе</option>
            <option value="light">Светлая</option>
            <option value="dark">Темная</option>
          </select>
        </label>
        <label className="field-label">
          Плотность карточек
          <select
            value={state.display.density}
            onChange={(event) => actions.setDensity(event.target.value as CardDensity)}
          >
            <option value="comfortable">Комфортная</option>
            <option value="compact">Компактная</option>
          </select>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={state.display.showDataQuality}
            onChange={(event) => actions.setShowDataQuality(event.target.checked)}
          />
          Показывать качество данных
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={state.display.reduceMotion}
            onChange={(event) => actions.setReduceMotion(event.target.checked)}
          />
          Уменьшить анимацию
        </label>
      </div>
    </section>
  );
}

export function ProfilePreferences({
  regionOptions,
  topicOptions
}: {
  regionOptions: readonly string[];
  topicOptions: readonly Topic[];
}) {
  const { state, actions } = useAppState();

  return (
    <section className="profile-section">
      <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-1">
        <fieldset className="min-w-0">
          <legend className="sr-only">Предпочтительные регионы</legend>
          <h2 className="break-words">Предпочтительные регионы</h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {regionOptions.map((region) => (
              <button
                key={region}
                type="button"
                aria-label={`Предпочитать регион ${region}`}
                aria-pressed={state.preferredRegions.includes(region)}
                className="button-secondary"
                onClick={() => actions.togglePreferredRegion(region)}
              >
                {region}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset className="min-w-0">
          <legend className="sr-only">Предпочтительные тематики</legend>
          <h2 className="break-words">Предпочтительные тематики</h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {topicOptions.map((topic) => (
              <button
                key={topic}
                type="button"
                aria-label={`Предпочитать тематику ${topic}`}
                aria-pressed={state.preferredTopics.includes(topic)}
                className="button-secondary"
                onClick={() => actions.togglePreferredTopic(topic)}
              >
                {topic}
              </button>
            ))}
          </div>
        </fieldset>
      </div>
    </section>
  );
}
