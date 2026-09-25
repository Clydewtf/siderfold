import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  createResearchApiClient,
  ResearchApiError,
  type ResearchApiClient,
  type ResearchSnapshot,
  type SnapshotMetricResponse,
  type SnapshotList,
  type TemporalSeriesResponse
} from './api';
import {
  buildCsvExport,
  buildSvgExport,
  collectMetricRows,
  createResearchExport,
  documentedResearchData,
  RESEARCH_BUILD_INFO,
  type ChartValue,
  type ResearchData
} from './export';

type SnapshotResponses = {
  quality: SnapshotMetricResponse | null;
  baseline: SnapshotMetricResponse | null;
  regional: SnapshotMetricResponse | null;
  network: SnapshotMetricResponse | null;
  errors: string[];
};

type LabData = ResearchData & { snapshot: Record<string, unknown> };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return 'Не вычислено';
  if (typeof value === 'number') return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4 }).format(value);
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
  return JSON.stringify(value);
}

function qualityLabel(metricKey: string): string {
  const key = metricKey.replace('quality_metrics.metrics.', '');
  const labels: Record<string, string> = {
    freshness: 'Свежесть наблюдений',
    completeness: 'Полнота обязательных полей',
    conflicts: 'Явные конфликты в очереди review',
    source_coverage: 'Покрытие запусков реестра',
    review_status: 'Открытые review-кейсы'
  };
  return labels[key] ?? key;
}

function qualityValue(row: ReturnType<typeof collectMetricRows>[number]): string {
  return typeof row.value === 'number' && row.unit === 'share'
    ? new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 }).format(row.value)
    : displayValue(row.value);
}

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Дата неизвестна' : new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC'
  }).format(date) + ' UTC';
}

function errorMessage(error: unknown): string {
  return error instanceof ResearchApiError ? error.message : 'Не удалось получить аналитические данные.';
}

function AccessGate({ onConnected }: { onConnected: (client: ResearchApiClient, snapshots: SnapshotList) => void }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) {
      setError('Введите токен внутреннего доступа.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const client = createResearchApiClient({ token: token.trim() });
      const snapshots = await client.listSnapshots();
      onConnected(client, snapshots);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-container flex min-h-screen items-center" aria-labelledby="research-access-title">
      <section className="mx-auto w-full max-w-2xl rounded-2xl border border-ink/10 bg-white/80 p-6 shadow-panel sm:p-9">
        <p className="eyebrow">Внутренний read-only раздел</p>
        <h1 id="research-access-title" className="mt-3 text-3xl font-semibold tracking-tight text-ink">Аналитическая лаборатория</h1>
        <p className="mt-4 max-w-xl text-sm leading-6 text-graphite">
          Лаборатория читает агрегированные AnalyticsSnapshot через защищённый API. Токен действует только в этой вкладке и не сохраняется.
        </p>
        <form className="mt-7 grid gap-4" onSubmit={(event) => void submit(event)}>
          <label className="field-label" htmlFor="research-token">
            Токен внутреннего API
            <input
              id="research-token"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              aria-describedby={error ? 'research-access-error' : undefined}
            />
          </label>
          {error ? <p id="research-access-error" role="alert" className="text-sm text-clay">{error}</p> : null}
          <div className="flex flex-wrap gap-3">
            <button type="submit" className="button-primary" disabled={busy}>{busy ? 'Проверяем…' : 'Открыть лабораторию'}</button>
            <a className="button-secondary" href="/">Вернуться в каталог</a>
          </div>
        </form>
      </section>
    </main>
  );
}

function cleanNetworkResponse(response: SnapshotMetricResponse | null): Record<string, unknown> | undefined {
  const network = response?.network;
  if (!isRecord(network) || network.version !== 'catalog-network/v1' || !isRecord(network.dimensions)) return undefined;
  const dimensions: Record<string, unknown> = {};
  for (const dimension of ['program', 'theme', 'geography'] as const) {
    const graph = network.dimensions[dimension];
    if (!isRecord(graph)) continue;
    const graphMetrics = record(graph.metrics);
    dimensions[dimension] = {
      dimension: graph.dimension,
      version: graph.version,
      snapshot_id: graph.snapshot_id,
      data_class: graph.data_class,
      window: graph.window,
      unit_of_observation: graph.unit_of_observation,
      filter: graph.filter,
      graph_definition: graph.graph_definition,
      metrics: Object.fromEntries(
        ['node_count', 'edge_count', 'density', 'connected_components']
          .filter((key) => isRecord(graphMetrics[key]))
          .map((key) => [key, graphMetrics[key]])
      ),
      normalization: graph.normalization,
      warning: graph.warning,
      warnings: graph.warnings,
      limitations: graph.limitations
    };
  }
  return {
    version: network.version,
    snapshot_id: network.snapshot_id,
    data_class: network.data_class,
    as_of: network.as_of,
    scope: network.scope,
    calculation_version: network.calculation_version,
    registry_fingerprint: network.registry_fingerprint,
    dimensions,
    limitations: network.limitations
  };
}

function createLabData(
  snapshot: ResearchSnapshot,
  responses: SnapshotResponses,
  temporalSeries: TemporalSeriesResponse | null
): LabData {
  const raw = {
    snapshot: {
      snapshot_id: snapshot.snapshot_id,
      scope: snapshot.scope,
      calculation_version: snapshot.calculation_version,
      as_of: snapshot.as_of,
      created_at: snapshot.created_at,
      freshness_window_days: snapshot.freshness_window_days,
      registry_fingerprint: snapshot.registry_fingerprint,
      input_fingerprint: snapshot.input_fingerprint,
      data_class: snapshot.data_class,
      program_source_keys: snapshot.program_source_keys,
      program_count: snapshot.program_count,
      limitations: snapshot.limitations
    },
    ...(responses.quality?.quality ? { quality_metrics: responses.quality.quality } : {}),
    ...(responses.baseline?.baseline ? { baseline: responses.baseline.baseline } : {}),
    ...(responses.regional?.regional_indicators ? { regional_indicators: responses.regional.regional_indicators } : {}),
    ...(cleanNetworkResponse(responses.network) ? { network: cleanNetworkResponse(responses.network) } : {}),
    ...(temporalSeries ? { temporal_series: temporalSeries } : {})
  } satisfies ResearchData;
  return documentedResearchData(raw) as LabData;
}

function safeDownload(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function sourceChartValues(data: LabData | null): ChartValue[] {
  return collectMetricRows(data ?? { snapshot: {} })
    .filter((row) => row.metric_key.startsWith('baseline.metrics.opportunities.source.') && row.metric_key.endsWith('.count'))
    .flatMap((row) => typeof row.value === 'number' && Number.isFinite(row.value)
      ? [{ label: row.metric_key.slice('baseline.metrics.opportunities.source.'.length, -'.count'.length), value: row.value }]
      : [])
    .sort((left, right) => left.label.localeCompare(right.label, 'en'));
}

function taxonomyCoverageValues(data: LabData | null): ChartValue[] {
  const rows = collectMetricRows(data ?? { snapshot: {} });
  return (['geography', 'theme'] as const).flatMap((dimension) => {
    const metric = rows.find((row) => row.metric_key === `regional_indicators.${dimension}.coverage`);
    return typeof metric?.value === 'number' && Number.isFinite(metric.value)
      ? [{ label: dimension === 'geography' ? 'Региональные метки' : 'Тематические метки', value: metric.value * 100 }]
      : [];
  });
}

function timeSeriesValues(series: TemporalSeriesResponse | null): ChartValue[] {
  if (!series || series.version !== 'catalog-temporal/v1' || !Array.isArray(series.cohorts)) return [];
  const data = documentedResearchData({ snapshot: {}, temporal_series: series });
  return collectMetricRows(data)
    .filter((row) => row.metric_key.endsWith('.metrics.programs.stock'))
    .flatMap((row) => {
      const period = isRecord(row.period) ? row.period : {};
      const start = typeof period.start === 'string'
        ? period.start
        : typeof period.week_start === 'string'
          ? period.week_start
          : null;
      return typeof row.value === 'number' && Number.isFinite(row.value) && start
        ? [{ label: start, value: row.value }]
        : [];
    })
    .sort((left, right) => left.label.localeCompare(right.label));
}

function Bars({ title, unit, values }: { title: string; unit: string; values: readonly ChartValue[] }) {
  const max = Math.max(1, ...values.map((entry) => Math.abs(entry.value)));
  const rowHeight = 38;
  return (
    <div>
      <svg role="img" aria-label={title} viewBox={`0 0 820 ${82 + values.length * rowHeight}`} className="w-full">
        <title>{title}</title>
        {values.map((entry, index) => {
          const y = 22 + index * rowHeight;
          const width = Math.abs(entry.value) / max * 500;
          return (
            <g key={`${entry.label}-${index}`}>
              <text x="0" y={y + 17} fontSize="13" fill="#272a2f">{entry.label}</text>
              <rect x="250" y={y} width={width} height="22" rx="5" fill="#2f5f9e" />
              <text x={260 + width} y={y + 17} fontSize="13" fill="#272a2f">{displayValue(entry.value)} {unit}</text>
            </g>
          );
        })}
      </svg>
      <ul className="sr-only" aria-label={`${title}: значения`}>
        {values.map((entry) => <li key={entry.label}>{entry.label}: {displayValue(entry.value)} {unit}</li>)}
      </ul>
    </div>
  );
}

function MetricDetails({ row }: { row: ReturnType<typeof collectMetricRows>[number] }) {
  return (
    <details>
      <summary>Метод и границы</summary>
      <dl className="mt-2 grid gap-2 text-xs leading-5 text-graphite">
        <div><dt className="font-semibold">Формула</dt><dd>{row.formula}</dd></div>
        <div><dt className="font-semibold">Период</dt><dd>{displayValue(row.period)}</dd></div>
        <div><dt className="font-semibold">Фильтр</dt><dd>{row.filter}</dd></div>
        <div><dt className="font-semibold">Пропуски</dt><dd>{displayValue(row.missing)}</dd></div>
        <div><dt className="font-semibold">Неопределённость</dt><dd>{displayValue(row.uncertainty)}</dd></div>
        {row.numerator !== undefined ? <div><dt className="font-semibold">Числитель</dt><dd>{displayValue(row.numerator)}</dd></div> : null}
        {row.denominator !== undefined ? <div><dt className="font-semibold">Знаменатель</dt><dd>{displayValue(row.denominator)}</dd></div> : null}
        <div><dt className="font-semibold">Ограничение</dt><dd>{row.limitation}</dd></div>
      </dl>
    </details>
  );
}

function ResearchWorkspace({
  client,
  snapshots,
  classCounts,
  onSignOut
}: {
  client: ResearchApiClient;
  snapshots: ResearchSnapshot[];
  classCounts: Record<string, number>;
  onSignOut: () => void;
}) {
  const eligibleSnapshots = useMemo(
    () => snapshots.filter((snapshot) => snapshot.compatible && snapshot.data_class === 'real'),
    [snapshots]
  );
  const temporalSnapshots = useMemo(
    () => eligibleSnapshots.filter((snapshot) => snapshot.capabilities.temporal_series).sort((a, b) => a.as_of.localeCompare(b.as_of)),
    [eligibleSnapshots]
  );
  const [snapshotId, setSnapshotId] = useState('');
  const [snapshotResponses, setSnapshotResponses] = useState<SnapshotResponses | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(false);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [seriesFrom, setSeriesFrom] = useState('');
  const [seriesTo, setSeriesTo] = useState('');
  const [series, setSeries] = useState<TemporalSeriesResponse | null>(null);
  const [loadingSeries, setLoadingSeries] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!snapshotId && eligibleSnapshots.length) setSnapshotId(eligibleSnapshots[0].snapshot_id);
  }, [eligibleSnapshots, snapshotId]);

  useEffect(() => {
    if (!temporalSnapshots.length) return;
    setSeriesFrom(temporalSnapshots[0].as_of.slice(0, 10));
    setSeriesTo(temporalSnapshots[temporalSnapshots.length - 1].as_of.slice(0, 10));
  }, [temporalSnapshots]);

  const selectedSnapshot = eligibleSnapshots.find((snapshot) => snapshot.snapshot_id === snapshotId) ?? null;

  useEffect(() => {
    if (!selectedSnapshot) {
      setSnapshotResponses(null);
      return;
    }
    let cancelled = false;
    setLoadingSnapshot(true);
    setSnapshotError(null);
    setSeries(null);
    const request = async () => {
      const errors: string[] = [];
      const safeRequest = async (
        enabled: boolean,
        label: string,
        action: () => Promise<SnapshotMetricResponse>
      ): Promise<SnapshotMetricResponse | null> => {
        if (!enabled) return null;
        try {
          return await action();
        } catch (error) {
          errors.push(`${label}: ${errorMessage(error)}`);
          return null;
        }
      };
      const [quality, baseline, regional, network] = await Promise.all([
        safeRequest(selectedSnapshot.capabilities.quality, 'Качество данных', () => client.getQualityMetrics(selectedSnapshot.snapshot_id)),
        safeRequest(selectedSnapshot.capabilities.baseline, 'Baseline', () => client.getBaseline(selectedSnapshot.snapshot_id)),
        safeRequest(selectedSnapshot.capabilities.regional_indicators, 'Региональные показатели', () => client.getRegionalIndicators(selectedSnapshot.snapshot_id)),
        safeRequest(selectedSnapshot.capabilities.network, 'Сетевые метрики', () => client.getNetwork(selectedSnapshot.snapshot_id))
      ]);
      if (cancelled) return;
      setSnapshotResponses({ quality, baseline, regional, network, errors });
      if (!quality && !baseline && !regional && !network) setSnapshotError('Для snapshot не удалось загрузить документированные показатели.');
      setLoadingSnapshot(false);
    };
    void request();
    return () => { cancelled = true; };
  }, [client, selectedSnapshot]);

  const data = useMemo(() => selectedSnapshot && snapshotResponses
    ? createLabData(selectedSnapshot, snapshotResponses, series)
    : null, [selectedSnapshot, snapshotResponses, series]);
  const metricRows = useMemo(() => data ? collectMetricRows(data) : [], [data]);
  const qualityRows = useMemo(
    () => metricRows.filter((row) => row.metric_key.startsWith('quality_metrics.metrics.')),
    [metricRows]
  );
  const sourceBars = useMemo(() => sourceChartValues(data), [data]);
  const coverageBars = useMemo(() => taxonomyCoverageValues(data), [data]);
  const temporalBars = useMemo(() => timeSeriesValues(series), [series]);

  async function requestSeries(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSeriesError(null);
    setSeries(null);
    if (!seriesFrom || !seriesTo || seriesFrom > seriesTo) {
      setSeriesError('Укажите корректный включительный интервал дат.');
      return;
    }
    setLoadingSeries(true);
    try {
      const result = await client.getTemporalSeries(seriesFrom, seriesTo, 'real');
      if (result.version !== 'catalog-temporal/v1' || result.data_class !== 'real') {
        throw new Error('Временной результат не относится к документированной версии и классу real.');
      }
      setSeries(result);
    } catch (error) {
      setSeriesError(errorMessage(error));
    } finally {
      setLoadingSeries(false);
    }
  }

  function exportParameters(format: string, figure?: string): Record<string, unknown> {
    return {
      selected_snapshot_id: selectedSnapshot?.snapshot_id ?? null,
      metric_groups: ['quality_metrics', 'baseline', 'regional_indicators', 'network', ...(series ? ['temporal_series'] : [])],
      temporal_window: series ? { from: seriesFrom, to: seriesTo, frequency: 'weekly', data_class: 'real' } : null,
      network_dimensions: ['program', 'theme', 'geography'],
      format,
      ...(figure ? { figure } : {})
    };
  }

  async function createExport(format: string, figure?: string) {
    if (!data || !selectedSnapshot) return null;
    setExportError(null);
    try {
      const result = await createResearchExport(data, eligibleSnapshots, exportParameters(format, figure));
      return result;
    } catch (error) {
      setExportError(errorMessage(error));
      return null;
    }
  }

  async function downloadJson() {
    const result = await createExport('json');
    if (!result) return;
    safeDownload(`siderfold-research-${selectedSnapshot?.snapshot_id}.json`, JSON.stringify(result, null, 2), 'application/json;charset=utf-8');
    setNotice('JSON-отчёт сохранён.');
  }

  async function downloadCsv() {
    const result = await createExport('csv');
    if (!result) return;
    try {
      const csv = await buildCsvExport(result);
      safeDownload(`siderfold-research-${selectedSnapshot?.snapshot_id}.csv`, `\uFEFF${csv}`, 'text/csv;charset=utf-8');
      setNotice('CSV-таблица с метаданными сохранена.');
    } catch (error) {
      setExportError(errorMessage(error));
    }
  }

  async function downloadSvg(title: string, unit: string, values: ChartValue[], figure: string) {
    const result = await createExport('svg', figure);
    if (!result) return;
    try {
      const svg = await buildSvgExport(title, unit, values, result, exportParameters('svg', figure));
      safeDownload(`siderfold-${figure}-${selectedSnapshot?.snapshot_id}.svg`, svg, 'image/svg+xml;charset=utf-8');
      setNotice('SVG-график с методикой и метаданными сохранён.');
    } catch (error) {
      setExportError(errorMessage(error));
    }
  }

  const sourceRevisionNote = data
    ? `Версия приложения ${RESEARCH_BUILD_INFO.applicationVersion}; Git ${RESEARCH_BUILD_INFO.sourceRevision}${RESEARCH_BUILD_INFO.sourceTreeDirty ? ' (рабочее дерево изменено на момент сборки)' : ' (чистое дерево на момент сборки)'}.`
    : null;
  const excludedClasses = ['test', 'synthetic', 'unknown'].map((name) => `${name}: ${classCounts[name] ?? 0}`).join(' · ');
  const computedSeriesPoints = temporalBars.length;

  return (
    <main className="page-container" aria-labelledby="research-title">
      <header className="flex flex-col gap-5 border-b border-ink/10 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">Исследовательский слой · read-only</p>
          <h1 id="research-title" className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Аналитическая лаборатория</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-graphite">Показатели строятся из зафиксированных AnalyticsSnapshot по документированным формулам. Основной каталог и его демо-аналитика здесь не используются.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a className="button-secondary" href="/">Каталог</a>
          <button type="button" className="button-secondary" onClick={onSignOut}>Завершить сессию</button>
        </div>
      </header>

      <section className="mt-6 rounded-xl border border-cobalt/25 bg-cobalt/10 p-4 text-sm leading-6 text-graphite" aria-label="Граница данных">
        <strong>Граница охвата.</strong> `real` означает класс snapshot в локальной operational БД и допустимый source scope. Это не аудит каждой строки и не полное покрытие экосистемы. FASIE, Telegram-discovery как программы, raw captures и review payloads в лабораторию не входят.
        <p className="mt-2">Не показываются в лаборатории: {excludedClasses}. `test`, `synthetic` и `unknown` исключены из реальных таблиц и экспортов.</p>
      </section>

      {eligibleSnapshots.length === 0 ? (
        <section className="mt-7 rounded-xl border border-ink/10 bg-white/75 p-6">
          <h2 className="text-xl font-semibold">Нет совместимых real snapshot-ов</h2>
          <p className="mt-2 text-sm leading-6 text-graphite">Проверьте защищённый реестр AnalyticsSnapshot и классификацию базы. Тестовые и синтетические данные здесь не подменяют реальные.</p>
        </section>
      ) : (
        <>
          <section className="mt-7 grid gap-5 rounded-xl border border-ink/10 bg-white/75 p-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]" aria-labelledby="snapshot-choice-title">
            <label className="field-label" htmlFor="research-snapshot">
              <span id="snapshot-choice-title">AnalyticsSnapshot</span>
              <select id="research-snapshot" value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)}>
                {eligibleSnapshots.map((snapshot) => (
                  <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>
                    {snapshot.as_of.slice(0, 10)} · {snapshot.program_count ?? 'число карточек неизвестно'} · {snapshot.calculation_version}
                  </option>
                ))}
              </select>
            </label>
            {selectedSnapshot ? (
              <dl className="grid gap-x-5 gap-y-2 text-sm sm:grid-cols-2">
                <div><dt className="font-semibold">Snapshot ID</dt><dd className="break-all font-mono text-xs">{selectedSnapshot.snapshot_id}</dd></div>
                <div><dt className="font-semibold">Срез</dt><dd>{dateLabel(selectedSnapshot.as_of)}</dd></div>
                <div><dt className="font-semibold">Расчёт</dt><dd>{selectedSnapshot.calculation_version}</dd></div>
                <div><dt className="font-semibold">Источники программы</dt><dd>{selectedSnapshot.program_source_keys.join(', ') || 'неизвестно'}</dd></div>
                <div className="sm:col-span-2"><dt className="font-semibold">Fingerprint входа (SHA-256)</dt><dd className="break-all font-mono text-xs">{selectedSnapshot.input_fingerprint}</dd></div>
              </dl>
            ) : null}
          </section>

          {loadingSnapshot ? <p role="status" className="mt-6 text-sm text-graphite">Загружаем агрегированные метрики snapshot…</p> : null}
          {snapshotError ? <p role="alert" className="mt-5 rounded-lg border border-clay/30 bg-clay/10 p-4 text-sm text-clay">{snapshotError}</p> : null}
          {snapshotResponses?.errors.map((error) => <p key={error} role="status" className="mt-3 text-sm text-clay">{error}</p>)}

          {data ? (
            <>
              <section className="mt-8 rounded-xl border border-ink/10 bg-white/75 p-5" aria-labelledby="quality-metrics-title">
                <h2 id="quality-metrics-title" className="text-xl font-semibold">Качество данных выбранного среза</h2>
                <p className="mt-2 text-sm leading-6 text-graphite">Метрики качества рассчитываются отдельно от baseline. Они описывают сохранённый roster и очереди review, а не полноту всего рынка или истинность внешних страниц.</p>
                {qualityRows.length ? (
                  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {qualityRows.map((row) => (
                      <article key={row.metric_key} className="rounded-lg border border-ink/10 bg-white p-4">
                        <h3 className="font-semibold">{qualityLabel(row.metric_key)}</h3>
                        <p className="mt-2 text-2xl font-semibold tabular-nums text-ink">{qualityValue(row)}</p>
                        <p className="mt-1 text-xs text-graphite">n = {displayValue(row.sample_size)} · {row.status}</p>
                        <div className="mt-2"><MetricDetails row={row} /></div>
                      </article>
                    ))}
                  </div>
                ) : <p className="mt-4 text-sm text-graphite">Для этого snapshot нет полного набора документированных quality metrics.</p>}
              </section>

              <section className="mt-8 grid gap-5 lg:grid-cols-2" aria-label="Графики документированных показателей">
                <article className="rounded-xl border border-ink/10 bg-white/75 p-5">
                  <h2 className="text-lg font-semibold">Карточки по primary source</h2>
                  <p className="mt-1 text-xs leading-5 text-graphite">Точные количества опубликованных карточек в выбранном snapshot, не доли полного рынка.</p>
                  {sourceBars.length ? <Bars title="Карточки по primary source" unit="карточек" values={sourceBars} /> : <p className="mt-4 text-sm text-graphite">Документированные значения для графика отсутствуют.</p>}
                  {sourceBars.length ? <button type="button" className="button-secondary mt-3" onClick={() => void downloadSvg('Карточки по primary source', 'карточек', sourceBars, 'source-counts')}>Скачать SVG</button> : null}
                </article>
                <article className="rounded-xl border border-ink/10 bg-white/75 p-5">
                  <h2 className="text-lg font-semibold">Покрытие явных taxonomy-меток</h2>
                  <p className="mt-1 text-xs leading-5 text-graphite">Доли от всех карточек snapshot; метки неполны и могут пересекаться.</p>
                  {coverageBars.length ? <Bars title="Покрытие явных taxonomy-меток" unit="%" values={coverageBars} /> : <p className="mt-4 text-sm text-graphite">Этот snapshot не содержит совместимого manifest v3.</p>}
                  {coverageBars.length ? <button type="button" className="button-secondary mt-3" onClick={() => void downloadSvg('Покрытие явных taxonomy-меток', '% карточек', coverageBars, 'taxonomy-coverage')}>Скачать SVG</button> : null}
                </article>
              </section>

              <section className="mt-8 rounded-xl border border-ink/10 bg-white/75 p-5" aria-labelledby="time-series-title">
                <h2 id="time-series-title" className="text-xl font-semibold">Временные ряды</h2>
                <p className="mt-2 text-sm leading-6 text-graphite">Недельные точки по UTC собираются только из совместимых snapshot-ов. Пропущенные недели остаются пропусками. Появление в каталоге — момент наблюдения платформы, не дата возникновения конкурса у источника.</p>
                {temporalSnapshots.length < 2 ? <p className="mt-3 rounded-lg bg-ink/5 p-3 text-sm">Совместимых real v3 snapshot-ов меньше двух; тренд и изменения между срезами не интерпретируются.</p> : null}
                {selectedSnapshot?.capabilities.temporal_series ? (
                  <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(event) => void requestSeries(event)}>
                    <label className="field-label" htmlFor="series-from">С даты<input id="series-from" type="date" value={seriesFrom} onChange={(event) => setSeriesFrom(event.target.value)} /></label>
                    <label className="field-label" htmlFor="series-to">По дату включительно<input id="series-to" type="date" value={seriesTo} onChange={(event) => setSeriesTo(event.target.value)} /></label>
                    <button type="submit" className="button-primary" disabled={loadingSeries}>{loadingSeries ? 'Рассчитываем…' : 'Построить недельный ряд'}</button>
                  </form>
                ) : <p className="mt-3 text-sm text-graphite">Временной расчёт требует совместимого manifest v3.</p>}
                {seriesError ? <p role="alert" className="mt-3 text-sm text-clay">{seriesError}</p> : null}
                {series ? (
                  <div className="mt-5">
                    {computedSeriesPoints >= 2 ? (
                      <>
                        <h3 className="font-semibold">Запас опубликованных карточек по выбранным неделям</h3>
                        <Bars title="Запас опубликованных карточек по неделям" unit="карточек" values={temporalBars} />
                        <button type="button" className="button-secondary mt-3" onClick={() => void downloadSvg('Запас опубликованных карточек по неделям', 'карточек', temporalBars, 'weekly-program-stock')}>Скачать SVG</button>
                      </>
                    ) : <p role="status" className="rounded-lg bg-ink/5 p-3 text-sm">В интервале найдено меньше двух рассчитанных точек. Это состояние каталога, не временной тренд.</p>}
                    <p className="mt-3 text-xs text-graphite">Статус API: {String(series.status)}. Когорт: {Array.isArray(series.cohorts) ? series.cohorts.length : 0}; точек с данными: {computedSeriesPoints}.</p>
                  </div>
                ) : null}
              </section>

              <section className="mt-8 rounded-xl border border-ink/10 bg-white/75 p-5" aria-labelledby="network-title">
                <h2 id="network-title" className="text-xl font-semibold">Сетевые метрики</h2>
                <p className="mt-2 text-sm leading-6 text-graphite">Левая доля графа — технический primary source, не установленный организатор. Показываются агрегированные узлы, рёбра, плотность и компоненты; связи не означают причинность, качество или спрос.</p>
              </section>

              <section className="mt-8 rounded-xl border border-ink/10 bg-white/75 p-5" aria-labelledby="metric-table-title">
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <div>
                    <h2 id="metric-table-title" className="text-xl font-semibold">Исходные документированные показатели</h2>
                    <p className="mt-1 text-sm text-graphite">Число строк: {metricRows.length}. Значения сохраняют пропуски и статусы расчёта.</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="button-secondary" onClick={() => void downloadJson()} disabled={!metricRows.length}>Скачать JSON</button>
                    <button type="button" className="button-secondary" onClick={() => void downloadCsv()} disabled={!metricRows.length}>Скачать CSV</button>
                  </div>
                </div>
                <div className="mt-4 max-w-full overflow-x-auto" role="region" aria-label="Таблица показателей" tabIndex={0}>
                  <table className="w-full min-w-[960px] border-collapse text-left text-sm">
                    <thead><tr className="border-b border-ink/15"><th className="p-2">Ключ</th><th className="p-2">Значение</th><th className="p-2">Единица</th><th className="p-2">n</th><th className="p-2">Статус</th><th className="p-2">Подробности</th></tr></thead>
                    <tbody>
                      {metricRows.map((row) => (
                        <tr key={row.metric_key} className="border-b border-ink/10 align-top">
                          <th scope="row" className="max-w-80 break-all p-2 font-mono text-xs">{row.metric_key}</th>
                          <td className="p-2">{displayValue(row.value)}</td>
                          <td className="p-2">{row.unit}</td>
                          <td className="p-2">{displayValue(row.sample_size)}</td>
                          <td className="p-2">{row.status}</td>
                          <td className="p-2"><MetricDetails row={row} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!metricRows.length ? <p className="mt-4 text-sm text-graphite">Для этого snapshot нет документированных метрик совместимых версий.</p> : null}
                <p className="mt-4 text-xs leading-5 text-graphite">Неописанные или неполные метрики скрываются. Git-ревизия расчётного кода не хранится: {sourceRevisionNote}</p>
              </section>

              <section className="mt-8 grid gap-5 lg:grid-cols-2" aria-label="Методика и ограничения">
                <article className="rounded-xl border border-ink/10 bg-white/75 p-5">
                  <h2 className="text-lg font-semibold">Методика</h2>
                  <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-graphite">
                    <li>Единица каталожных показателей — уникальная опубликованная Program в замороженном roster.</li>
                    <li>Финансирование разделяется по валюте и exact/minimum/maximum/range; неизвестные суммы не превращаются в ноль.</li>
                    <li>Доли taxonomy используют все подходящие карточки в знаменателе; отсутствующая метка остаётся неизвестной.</li>
                    <li>Интервалы bootstrap выводятся только там, где они записаны и обоснованы методикой E2.</li>
                  </ul>
                </article>
                <article className="rounded-xl border border-ink/10 bg-white/75 p-5">
                  <h2 className="text-lg font-semibold">Ограничения интерпретации</h2>
                  <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-graphite">
                    {(selectedSnapshot?.limitations.length ? selectedSnapshot.limitations : ['Ограничения snapshot не указаны.']).map((limitation) => <li key={limitation}>{limitation}</li>)}
                    <li>Источник является технической атрибуцией primary_source; доступные метрики не оценивают весь рынок возможностей.</li>
                    <li>Синтетические, тестовые и неизвестные данные не смешиваются с real и не экспортируются как реальные.</li>
                  </ul>
                </article>
              </section>
            </>
          ) : null}

          {exportError ? <p role="alert" className="mt-5 rounded-lg border border-clay/30 bg-clay/10 p-4 text-sm text-clay">{exportError}</p> : null}
          {notice ? <p role="status" className="mt-5 text-sm text-moss">{notice}</p> : null}
        </>
      )}
    </main>
  );
}

export function ResearchLabApp() {
  const [client, setClient] = useState<ResearchApiClient | null>(null);
  const [snapshotList, setSnapshotList] = useState<SnapshotList | null>(null);
  function connect(nextClient: ResearchApiClient, snapshots: SnapshotList) {
    setClient(nextClient);
    setSnapshotList(snapshots);
  }
  if (!client || !snapshotList) {
    return <AccessGate onConnected={connect} />;
  }
  return (
    <ResearchWorkspace
      key="research-session"
      client={client}
      snapshots={snapshotList.items}
      classCounts={snapshotList.class_counts}
      onSignOut={() => { setClient(null); setSnapshotList(null); }}
    />
  );
}
