export type DataMode = 'api' | 'seed';

export type RuntimeConfig = {
  mode: DataMode;
  apiBaseUrl: string;
  backendUrl: string;
  configurationError: string | null;
};

function envValue(name: string): string | undefined {
  const env = (import.meta as ImportMeta & { env?: Record<string, unknown> }).env;
  const value = env?.[name];
  return typeof value === 'string' ? value : undefined;
}

function trimTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, '');
}

export function getRuntimeConfig(): RuntimeConfig {
  const rawMode = envValue('VITE_DATA_MODE')?.trim().toLowerCase();
  const rawApiBaseUrl = envValue('VITE_API_BASE_URL')?.trim();
  const rawBackendUrl = envValue('VITE_BACKEND_URL')?.trim();

  if (rawMode && rawMode !== 'api' && rawMode !== 'seed') {
    return {
      mode: 'api',
      apiBaseUrl: '/api/v1',
      backendUrl: rawBackendUrl || 'http://127.0.0.1:8000',
      configurationError: 'VITE_DATA_MODE должен быть api или seed.'
    };
  }

  return {
    mode: rawMode === 'seed' ? 'seed' : 'api',
    apiBaseUrl: trimTrailingSlashes(rawApiBaseUrl || '/api/v1'),
    backendUrl: trimTrailingSlashes(rawBackendUrl || 'http://127.0.0.1:8000'),
    configurationError: null
  };
}
