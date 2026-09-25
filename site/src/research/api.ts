export type ResearchSnapshot = {
  snapshot_id: string;
  scope: string;
  calculation_version: string;
  as_of: string;
  created_at: string;
  freshness_window_days: number;
  registry_fingerprint: string;
  input_fingerprint: string;
  data_class: string;
  program_source_keys: string[];
  program_count: number | null;
  capabilities: {
    quality: boolean;
    baseline: boolean;
    regional_indicators: boolean;
    network: boolean;
    temporal_series: boolean;
  };
  compatible: boolean;
  exclusion_reasons: string[];
  limitations: string[];
};

export type SnapshotList = {
  items: ResearchSnapshot[];
  class_counts: Record<string, number>;
};

export type SnapshotMetricResponse = {
  snapshot_id: string;
  scope: string;
  calculation_version: string;
  as_of: string;
  input_fingerprint: string;
  data_class: string;
  quality?: Record<string, unknown>;
  baseline?: Record<string, unknown>;
  regional_indicators?: Record<string, unknown>;
  network?: Record<string, unknown>;
};

export type TemporalSeriesResponse = Record<string, unknown> & {
  version: string;
  frequency: string;
  data_class: string;
  window: Record<string, unknown>;
  cohorts: unknown[];
  status: string;
  limitations: string[];
};

export class ResearchApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null = null
  ) {
    super(message);
    this.name = 'ResearchApiError';
  }
}

export type ResearchApiClient = ReturnType<typeof createResearchApiClient>;

type ClientOptions = {
  token: string;
  baseUrl?: string;
  fetcher?: typeof fetch;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function ensureNonblank(value: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error('Internal API token is required.');
  return normalized;
}

function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, '')}${path}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 401 || response.status === 404) {
    throw new ResearchApiError('Доступ к аналитическому API не подтверждён.', response.status);
  }
  if (!response.ok) {
    throw new ResearchApiError(`Внутренний API вернул ошибку ${response.status}.`, response.status);
  }
  try {
    return await response.json() as T;
  } catch {
    throw new ResearchApiError('Внутренний API вернул некорректный JSON.');
  }
}

export function createResearchApiClient({
  token,
  baseUrl = '/api/internal/v1',
  fetcher = fetch
}: ClientOptions) {
  const authorization = `Bearer ${ensureNonblank(token)}`;

  async function get<T>(path: string): Promise<T> {
    try {
      const response = await fetcher(joinUrl(baseUrl, path), {
        headers: { Accept: 'application/json', Authorization: authorization },
        cache: 'no-store'
      });
      return await parseResponse<T>(response);
    } catch (error) {
      if (error instanceof ResearchApiError) throw error;
      throw new ResearchApiError('Внутренний API недоступен. Проверьте соединение с backend.');
    }
  }

  return {
    listSnapshots: async (): Promise<SnapshotList> => {
      const result = await get<unknown>('/analytics/snapshots');
      if (!isRecord(result) || !Array.isArray(result.items) || !isRecord(result.class_counts)) {
        throw new ResearchApiError('Список AnalyticsSnapshot имеет неожиданный формат.');
      }
      return result as SnapshotList;
    },
    getQualityMetrics: (snapshotId: string): Promise<SnapshotMetricResponse> =>
      get(`/analytics/snapshots/${encodeURIComponent(snapshotId)}/quality`),
    getBaseline: (snapshotId: string): Promise<SnapshotMetricResponse> =>
      get(`/analytics/snapshots/${encodeURIComponent(snapshotId)}/baseline`),
    getRegionalIndicators: (snapshotId: string): Promise<SnapshotMetricResponse> =>
      get(`/analytics/snapshots/${encodeURIComponent(snapshotId)}/regional-indicators`),
    getNetwork: (snapshotId: string): Promise<SnapshotMetricResponse> =>
      get(`/analytics/snapshots/${encodeURIComponent(snapshotId)}/network`),
    getTemporalSeries: (
      from: string,
      to: string,
      dataClass = 'real'
    ): Promise<TemporalSeriesResponse> => {
      const query = new URLSearchParams({ from, to, frequency: 'weekly', data_class: dataClass });
      return get(`/analytics/time-series?${query.toString()}`);
    }
  };
}
