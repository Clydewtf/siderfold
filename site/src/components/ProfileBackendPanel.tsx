import { BACKEND_CAPABILITIES } from '../lib/backendFeatures';
import { useAppState } from '../state/AppStateProvider';

export function ProfileBackendPanel() {
  const { state, actions } = useAppState();
  const capabilities = BACKEND_CAPABILITIES.filter((item) => item.surface === 'profile');

  return (
    <section aria-labelledby="account-capabilities-title" className="profile-section">
      <div className="profile-section__heading">
        <div>
          <p className="eyebrow">Следующий этап</p>
          <h2 id="account-capabilities-title">Аккаунт и backend</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-graphite">
            Локальные функции выше работают сейчас. Возможности ниже показаны только как готовые точки будущего подключения.
          </p>
        </div>
      </div>
      <ul data-density-grid className="grid gap-3 md:grid-cols-2">
        {capabilities.map((item) => (
          <li key={item.feature} data-density-card className="profile-capability-card">
            <p className="eyebrow">Демо-режим</p>
            <h3 className="mt-2 text-lg font-semibold">{item.title}</h3>
            <p className="mt-2 text-sm leading-6 text-graphite">{item.description}</p>
            <button
              type="button"
              className="button-secondary mt-4"
              onClick={() => actions.requestBackendFeature(item.feature)}
            >
              {item.actionLabel}
            </button>
          </li>
        ))}
      </ul>
      {state.backendNotice?.feature !== 'reportExport' ? (
        state.backendNotice ? (
          <p role="status" aria-live="polite" className="demo-status">{state.backendNotice.message}</p>
        ) : null
      ) : null}
    </section>
  );
}
