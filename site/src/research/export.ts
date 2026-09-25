import type { ResearchSnapshot } from './api';

export type MetricRow = {
  metric_key: string;
  value: unknown;
  formula: string;
  unit: string;
  period: unknown;
  filter: string;
  missing: unknown;
  uncertainty: unknown;
  sample_size: number;
  numerator?: unknown;
  denominator?: unknown;
  snapshot_id: string;
  limitation: string;
  status: string;
};

export type ResearchData = {
  snapshot: Record<string, unknown>;
  quality_metrics?: Record<string, unknown>;
  baseline?: Record<string, unknown>;
  regional_indicators?: Record<string, unknown>;
  network?: Record<string, unknown>;
  temporal_series?: Record<string, unknown>;
};

export type ExportMetadata = {
  snapshot_ids: string[];
  calculation_code_version: {
    application_version: string;
    snapshot_calculation_versions: Record<string, string>;
    metric_versions: Record<string, string>;
    source_revision: string;
    source_tree_dirty: boolean;
  };
  parameters: Record<string, unknown>;
  exported_at: string;
  input_fingerprints: Array<{ snapshot_id: string; sha256: string }>;
  data_sha256: string;
};

export type ResearchExport = {
  metadata: ExportMetadata;
  data: ResearchData;
};

const BASELINE_KEY = /^(opportunities\.count|opportunities\.source\.[^.]+\.(count|share)|funding\.(record_share|numeric_share|quantiles_status|quantile\..+)|deadlines\.(presence_share|upcoming_share|overdue_count|days\.(Q25|median|Q75))|source\.execution_coverage\.[^.]+)$/;
const NETWORK_METRICS = new Set(['node_count', 'edge_count', 'density', 'connected_components']);
const QUALITY_METRICS_VERSION = 'catalog-quality-metrics/v1';
const QUALITY_METRIC_KEYS = new Set(['freshness', 'completeness', 'conflicts', 'source_coverage', 'review_status']);

export const RESEARCH_BUILD_INFO = {
  applicationVersion: import.meta.env.VITE_APP_VERSION || 'unknown',
  sourceRevision: import.meta.env.VITE_SOURCE_REVISION || 'unknown',
  sourceTreeDirty: import.meta.env.VITE_SOURCE_TREE_DIRTY === 'true'
} as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])])
  );
}

export function canonicalJson(value: unknown): string {
  const serialized = JSON.stringify(canonicalValue(value));
  if (serialized === undefined) throw new Error('Значение нельзя представить как JSON.');
  return serialized;
}

export async function sha256Hex(value: unknown): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('SHA-256 недоступен в этом окружении браузера.');
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (part) => part.toString(16).padStart(2, '0')).join('');
}

function periodOf(metric: Record<string, unknown>): unknown {
  if (metric.period !== undefined) return metric.period;
  if (metric.week_start !== undefined || metric.week_end !== undefined) {
    return { start: metric.week_start ?? null, end: metric.week_end ?? null };
  }
  if (metric.interval_start !== undefined || metric.interval_end !== undefined) {
    return { start: metric.interval_start ?? null, end: metric.interval_end ?? null };
  }
  return null;
}

function asMetricRow(metricKey: string, value: unknown): MetricRow | null {
  if (!isRecord(value)) return null;
  const period = periodOf(value);
  const filter = value.filter ?? value.filter_description;
  if (
    typeof value.formula !== 'string'
    || typeof value.unit !== 'string'
    || typeof filter !== 'string'
    || typeof value.sample_size !== 'number'
    || !Number.isSafeInteger(value.sample_size)
    || value.sample_size < 0
    || typeof value.snapshot_id !== 'string'
    || typeof value.limitation !== 'string'
    || period === null
    || !('missing' in value)
    || !('value' in value)
  ) return null;
  return {
    metric_key: metricKey,
    value: value.value,
    formula: value.formula,
    unit: value.unit,
    period,
    filter,
    missing: value.missing,
    uncertainty: value.uncertainty ?? null,
    sample_size: value.sample_size,
    ...(typeof value.numerator === 'number' || value.numerator === null ? { numerator: value.numerator } : {}),
    ...(typeof value.denominator === 'number' || value.denominator === null ? { denominator: value.denominator } : {}),
    snapshot_id: value.snapshot_id,
    limitation: value.limitation,
    status: typeof value.status === 'string' ? value.status : 'status_not_recorded'
  };
}

function visitMetricTree(
  value: unknown,
  path: string,
  rows: MetricRow[],
  depth = 0
): void {
  if (depth > 12) return;
  const row = asMetricRow(path, value);
  if (row) {
    rows.push(row);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => visitMetricTree(item, `${path}.${index}`, rows, depth + 1));
  } else if (isRecord(value)) {
    Object.keys(value).sort().forEach((key) => {
      visitMetricTree(value[key], path ? `${path}.${key}` : key, rows, depth + 1);
    });
  }
}

function collectBaseline(data: ResearchData, rows: MetricRow[]): void {
  const metrics = data.baseline?.metrics;
  if (!isRecord(metrics)) return;
  Object.keys(metrics).sort().forEach((key) => {
    if (BASELINE_KEY.test(key)) visitMetricTree(metrics[key], `baseline.metrics.${key}`, rows);
  });
}

function collectQuality(data: ResearchData, rows: MetricRow[]): void {
  const quality = data.quality_metrics;
  if (!isRecord(quality) || quality.version !== QUALITY_METRICS_VERSION || !isRecord(quality.metrics)) return;
  for (const key of QUALITY_METRIC_KEYS) {
    visitMetricTree(quality.metrics[key], `quality_metrics.metrics.${key}`, rows);
  }
}

function collectRegional(data: ResearchData, rows: MetricRow[]): void {
  const dimensions = data.regional_indicators?.dimensions;
  if (!isRecord(dimensions)) return;
  for (const dimension of ['geography', 'theme'] as const) {
    const section = dimensions[dimension];
    if (!isRecord(section)) continue;
    visitMetricTree(section.coverage, `regional_indicators.${dimension}.coverage`, rows);
    const categories = section.categories;
    if (!isRecord(categories)) continue;
    Object.keys(categories).sort().forEach((slug) => {
      visitMetricTree(categories[slug], `regional_indicators.${dimension}.categories.${slug}`, rows);
    });
  }
}

function collectNetwork(data: ResearchData, rows: MetricRow[]): void {
  const dimensions = data.network?.dimensions;
  if (!isRecord(dimensions)) return;
  for (const dimension of ['program', 'theme', 'geography'] as const) {
    const graph = dimensions[dimension];
    const metrics = isRecord(graph) && isRecord(graph.metrics) ? graph.metrics : null;
    if (!metrics) continue;
    for (const key of NETWORK_METRICS) {
      visitMetricTree(metrics[key], `network.${dimension}.${key}`, rows);
    }
  }
}

function collectTemporal(data: ResearchData, rows: MetricRow[]): void {
  const temporal = data.temporal_series;
  if (!temporal || temporal.version !== 'catalog-temporal/v1' || !Array.isArray(temporal.cohorts)) return;
  for (const [cohortIndex, cohort] of temporal.cohorts.entries()) {
    if (!isRecord(cohort) || !Array.isArray(cohort.points)) continue;
    for (const [pointIndex, point] of cohort.points.entries()) {
      if (!isRecord(point) || point.status !== 'computed' || !isRecord(point.metrics)) continue;
      for (const domain of ['programs', 'deadlines', 'funding', 'taxonomy', 'updates']) {
        visitMetricTree(
          point.metrics[domain],
          `temporal_series.cohorts.${cohortIndex}.points.${pointIndex}.metrics.${domain}`,
          rows
        );
      }
    }
  }
}

export function collectMetricRows(data: ResearchData): MetricRow[] {
  const rows: MetricRow[] = [];
  collectQuality(data, rows);
  collectBaseline(data, rows);
  collectRegional(data, rows);
  collectNetwork(data, rows);
  collectTemporal(data, rows);
  return rows;
}

function documentedMetrics(
  source: unknown,
  allowed: (key: string) => boolean,
  expectedSnapshotId?: string
): Record<string, unknown> {
  if (!isRecord(source)) return {};
  const result: Record<string, unknown> = {};
  for (const key of Object.keys(source).sort()) {
    const metric = asMetricRow(key, source[key]);
    if (allowed(key) && metric && (!expectedSnapshotId || metric.snapshot_id === expectedSnapshotId)) {
      result[key] = source[key];
    }
  }
  return result;
}

const TEMPORAL_PROGRAM_KEYS = new Set([
  'stock', 'newly_observed', 'removed_from_published_scope', 'published_since_previous'
]);
const TEMPORAL_DEADLINE_KEYS = new Set([
  'with_date', 'upcoming_or_today', 'overdue', 'missing', 'changed_values_since_previous',
  'status_transitions_since_previous'
]);
const TEMPORAL_UPDATE_KEYS = new Set([
  'updated_at_changed', 'deadline_changed', 'funding_changed', 'taxonomy_changed_programs',
  'any_tracked_update'
]);

function sanitizeTemporalMetrics(source: unknown, snapshotId: string): Record<string, unknown> {
  if (!isRecord(source)) return {};
  const result: Record<string, unknown> = {};
  const domainMetrics = (domain: string, allowedKeys: Set<string>) => {
    const nested = isRecord(source[domain]) ? source[domain] : {};
    const flat = Object.fromEntries(
      [...allowedKeys]
        .filter((key) => Object.hasOwn(source, `${domain}.${key}`))
        .map((key) => [key, source[`${domain}.${key}`]])
    );
    return documentedMetrics({ ...flat, ...nested }, (key) => allowedKeys.has(key), snapshotId);
  };
  result.programs = domainMetrics('programs', TEMPORAL_PROGRAM_KEYS);
  result.deadlines = domainMetrics('deadlines', TEMPORAL_DEADLINE_KEYS);
  if (isRecord(source.funding)) {
    const funding: Record<string, unknown> = {};
    const changed = asMetricRow('funding.changed_programs_since_previous', source.funding.changed_programs_since_previous);
    const changedMatchesSnapshot = changed?.snapshot_id === snapshotId;
    if (changedMatchesSnapshot) funding.changed_programs_since_previous = source.funding.changed_programs_since_previous;
    const snapshotMetrics = documentedMetrics(source.funding.snapshot_metrics, (key) => BASELINE_KEY.test(key), snapshotId);
    if (Object.keys(snapshotMetrics).length) funding.snapshot_metrics = snapshotMetrics;
    result.funding = funding;
  }
  if (isRecord(source.taxonomy)) {
    const taxonomy: Record<string, unknown> = {};
    for (const dimension of ['theme', 'geography'] as const) {
      const current = source.taxonomy[dimension];
      if (!isRecord(current)) continue;
      const coverage = isRecord(current.coverage) ? {
        labelled_programs: asMetricRow('taxonomy.coverage.labelled_programs', current.coverage.labelled_programs)?.snapshot_id === snapshotId
          ? current.coverage.labelled_programs
          : undefined
      } : {};
      const categories: Record<string, unknown> = {};
      if (isRecord(current.categories)) {
        for (const [taxonomyId, category] of Object.entries(current.categories)) {
          if (!isRecord(category)) continue;
          const count = asMetricRow(`taxonomy.${dimension}.${taxonomyId}.count`, category.count)?.snapshot_id === snapshotId
            ? category.count
            : undefined;
          const share = asMetricRow(`taxonomy.${dimension}.${taxonomyId}.share`, category.share)?.snapshot_id === snapshotId
            ? category.share
            : undefined;
          if (count === undefined && share === undefined) continue;
          categories[taxonomyId] = {
            taxonomy_id: category.taxonomy_id,
            slug: category.slug,
            label: category.label,
            category_present_in_snapshot: category.category_present_in_snapshot,
            ...(count === undefined ? {} : { count }),
            ...(share === undefined ? {} : { share })
          };
        }
      }
      const membershipMetric = asMetricRow(
        `taxonomy.${dimension}.membership_changes_since_previous`,
        current.membership_changes_since_previous
      );
      const membership = membershipMetric?.snapshot_id === snapshotId
        ? current.membership_changes_since_previous
        : undefined;
      taxonomy[dimension] = {
        coverage,
        categories,
        ...(membership === undefined ? {} : { membership_changes_since_previous: membership })
      };
    }
    result.taxonomy = taxonomy;
  }
  result.updates = documentedMetrics(source.updates, (key) => TEMPORAL_UPDATE_KEYS.has(key), snapshotId);
  return result;
}

function sanitizeTemporal(source: unknown): Record<string, unknown> | undefined {
  if (
    !isRecord(source)
    || source.version !== 'catalog-temporal/v1'
    || source.data_class !== 'real'
    || !Array.isArray(source.cohorts)
  ) {
    return undefined;
  }
  const cohorts = source.cohorts.flatMap((cohort) => {
    if (!isRecord(cohort) || cohort.data_class !== 'real' || !Array.isArray(cohort.points)) return [];
    const points = cohort.points.flatMap((point) => {
      if (!isRecord(point)) return [];
      const pointSnapshotId = typeof point.snapshot_id === 'string' ? point.snapshot_id : '';
      return [{
        period: point.period,
        status: point.status,
        snapshot_id: point.snapshot_id,
        as_of: point.as_of,
        compared_snapshot_id: point.compared_snapshot_id,
        change_interval: point.change_interval,
        unit_of_observation: point.unit_of_observation,
        filter: point.filter,
        metrics: pointSnapshotId ? sanitizeTemporalMetrics(point.metrics, pointSnapshotId) : {},
        warnings: point.warnings,
        limitations: point.limitations
      }];
    });
    return [{
      scope: cohort.scope,
      calculation_version: cohort.calculation_version,
      freshness_window_days: cohort.freshness_window_days,
      registry_fingerprint: cohort.registry_fingerprint,
      data_class: cohort.data_class,
      snapshot_ids: cohort.snapshot_ids,
      periods_without_snapshot_are_missing: cohort.periods_without_snapshot_are_missing,
      points,
      limitations: cohort.limitations
    }];
  });
  return {
    version: source.version,
    frequency: source.frequency,
    data_class: source.data_class,
    window: source.window,
    selection: source.selection,
    cohorts,
    status: source.status,
    limitations: source.limitations
  };
}

export function documentedResearchData(data: ResearchData): ResearchData {
  const snapshotId = typeof data.snapshot.snapshot_id === 'string' ? data.snapshot.snapshot_id : null;
  const snapshot = {
    snapshot_id: data.snapshot.snapshot_id,
    scope: data.snapshot.scope,
    calculation_version: data.snapshot.calculation_version,
    as_of: data.snapshot.as_of,
    created_at: data.snapshot.created_at,
    freshness_window_days: data.snapshot.freshness_window_days,
    registry_fingerprint: data.snapshot.registry_fingerprint,
    input_fingerprint: data.snapshot.input_fingerprint,
    data_class: data.snapshot.data_class,
    program_source_keys: data.snapshot.program_source_keys,
    program_count: data.snapshot.program_count,
    limitations: data.snapshot.limitations
  };
  const baseline = data.baseline;
  const baselineMatchesSnapshot = isRecord(baseline)
    && baseline.snapshot_id === snapshotId
    && baseline.data_class === data.snapshot.data_class;
  const baselineMetrics = baselineMatchesSnapshot ? documentedMetrics(
    baseline.metrics,
    (key) => BASELINE_KEY.test(key),
    snapshotId ?? undefined
  ) : {};
  const cleanBaseline = baselineMatchesSnapshot && baseline.version === 'catalog-baseline/v1'
    ? {
        version: baseline.version,
        snapshot_id: baseline.snapshot_id,
        data_class: baseline.data_class,
        period: baseline.period,
        metrics: baselineMetrics,
        groups: baseline.groups,
        method: baseline.method
      }
    : undefined;

  const quality = data.quality_metrics;
  const qualityMatchesSnapshot = isRecord(quality)
    && quality.version === QUALITY_METRICS_VERSION
    && quality.snapshot_id === snapshotId
    && quality.data_class === data.snapshot.data_class
    && isRecord(quality.metrics);
  const qualityMetrics = qualityMatchesSnapshot
    ? documentedMetrics(
        quality.metrics,
        (key) => QUALITY_METRIC_KEYS.has(key),
        snapshotId ?? undefined
      )
    : {};
  const cleanQuality = qualityMatchesSnapshot && Object.keys(qualityMetrics).length
    ? {
        version: QUALITY_METRICS_VERSION,
        snapshot_id: quality.snapshot_id,
        data_class: quality.data_class,
        metrics: qualityMetrics,
        limitations: quality.limitations
      }
    : undefined;

  const regional = data.regional_indicators;
  let cleanRegional: Record<string, unknown> | undefined;
  if (isRecord(regional)
    && regional.version === 'catalog-regional-indicators/v1'
    && regional.snapshot_id === snapshotId
    && regional.data_class === data.snapshot.data_class
    && isRecord(regional.dimensions)) {
    const dimensions: Record<string, unknown> = {};
    for (const dimension of ['geography', 'theme'] as const) {
      const current = regional.dimensions[dimension];
      if (!isRecord(current)) continue;
      const coverage = asMetricRow(`${dimension}.coverage`, current.coverage)?.snapshot_id === snapshotId
        ? current.coverage
        : undefined;
      const categories = documentedMetrics(current.categories, () => true, snapshotId ?? undefined);
      dimensions[dimension] = {
        coverage,
        categories,
        multi_label: current.multi_label,
        taxonomy_hierarchy: current.taxonomy_hierarchy
      };
    }
    cleanRegional = {
      version: regional.version,
      snapshot_id: regional.snapshot_id,
      data_class: regional.data_class,
      as_of: regional.as_of,
      period: regional.period,
      unit_of_observation: regional.unit_of_observation,
      denominator_scope: regional.denominator_scope,
      dimensions,
      taxonomy_conflicts: regional.taxonomy_conflicts,
      composite_index: regional.composite_index,
      normalization: regional.normalization,
      limitations: regional.limitations
    };
  }

  const network = data.network;
  let cleanNetwork: Record<string, unknown> | undefined;
  if (isRecord(network)
    && network.version === 'catalog-network/v1'
    && network.snapshot_id === snapshotId
    && network.data_class === data.snapshot.data_class
    && isRecord(network.dimensions)) {
    const dimensions: Record<string, unknown> = {};
    for (const dimension of ['program', 'theme', 'geography'] as const) {
      const graph = network.dimensions[dimension];
      if (!isRecord(graph)) continue;
      if (graph.snapshot_id !== snapshotId) continue;
      const metrics = documentedMetrics(graph.metrics, (key) => NETWORK_METRICS.has(key), snapshotId ?? undefined);
      dimensions[dimension] = {
        dimension: graph.dimension,
        version: graph.version,
        snapshot_id: graph.snapshot_id,
        data_class: graph.data_class,
        window: graph.window,
        unit_of_observation: graph.unit_of_observation,
        filter: graph.filter,
        graph_definition: graph.graph_definition,
        metrics,
        normalization: graph.normalization,
        warning: graph.warning,
        warnings: graph.warnings,
        limitations: graph.limitations
      };
    }
    cleanNetwork = {
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
  const temporal = sanitizeTemporal(data.temporal_series);
  return {
    snapshot,
    ...(cleanQuality ? { quality_metrics: cleanQuality } : {}),
    ...(cleanBaseline ? { baseline: cleanBaseline } : {}),
    ...(cleanRegional ? { regional_indicators: cleanRegional } : {}),
    ...(cleanNetwork ? { network: cleanNetwork } : {}),
    ...(temporal ? { temporal_series: temporal } : {})
  };
}

function snapshotIdsInTemporal(data: ResearchData): string[] {
  const ids = new Set<string>();
  const temporal = data.temporal_series;
  if (!temporal || !Array.isArray(temporal.cohorts)) return [];
  for (const cohort of temporal.cohorts) {
    if (!isRecord(cohort)) continue;
    if (Array.isArray(cohort.snapshot_ids)) {
      cohort.snapshot_ids.forEach((id) => { if (typeof id === 'string') ids.add(id); });
    }
    if (!Array.isArray(cohort.points)) continue;
    for (const point of cohort.points) {
      if (!isRecord(point)) continue;
      for (const field of ['snapshot_id', 'compared_snapshot_id']) {
        if (typeof point[field] === 'string') ids.add(point[field] as string);
      }
    }
  }
  return [...ids].sort();
}

function metricVersions(data: ResearchData): Record<string, string> {
  const versions: Record<string, string> = {};
  for (const [key, section] of [
    ['quality_metrics', data.quality_metrics],
    ['baseline', data.baseline],
    ['regional_indicators', data.regional_indicators],
    ['network', data.network],
    ['temporal_series', data.temporal_series]
  ] as const) {
    if (isRecord(section) && typeof section.version === 'string') versions[key] = section.version;
  }
  return versions;
}

export async function createResearchExport(
  data: ResearchData,
  snapshots: readonly ResearchSnapshot[],
  parameters: Record<string, unknown>,
  exportedAt = new Date()
): Promise<ResearchExport> {
  if (
    data.snapshot.data_class !== 'real'
    || snapshots.length === 0
    || snapshots.some((snapshot) => snapshot.data_class !== 'real' || !snapshot.compatible)
  ) {
    throw new Error('Экспорт доступен только для совместимых snapshot-ов класса real.');
  }
  const cleanData = documentedResearchData(data);
  const byId = new Map(snapshots.map((snapshot) => [snapshot.snapshot_id, snapshot]));
  const selectedSnapshotId = typeof cleanData.snapshot.snapshot_id === 'string' ? cleanData.snapshot.snapshot_id : null;
  if (!selectedSnapshotId) throw new Error('В отчёте отсутствует ID выбранного snapshot.');
  const selectedSnapshot = byId.get(selectedSnapshotId);
  if (
    !selectedSnapshot
    || cleanData.snapshot.data_class !== 'real'
    || cleanData.snapshot.input_fingerprint !== selectedSnapshot.input_fingerprint
  ) {
    throw new Error('Выбранный snapshot отсутствует среди совместимых real данных или fingerprint не совпадает.');
  }
  const snapshotIds = [...new Set([selectedSnapshotId, ...snapshotIdsInTemporal(cleanData)])].sort();
  const fingerprintRows = snapshotIds.map((snapshotId) => {
    const snapshot = byId.get(snapshotId);
    if (!snapshot || !/^[a-f0-9]{64}$/.test(snapshot.input_fingerprint)) {
      throw new Error(`Для snapshot ${snapshotId} недоступен SHA-256 входных данных.`);
    }
    return { snapshot_id: snapshotId, sha256: snapshot.input_fingerprint };
  });
  const dataSha256 = await sha256Hex(cleanData);
  const versions = Object.fromEntries(
    snapshotIds.map((snapshotId) => [snapshotId, byId.get(snapshotId)?.calculation_version ?? 'unknown'])
  );
  return {
    metadata: {
      snapshot_ids: snapshotIds,
      calculation_code_version: {
        application_version: RESEARCH_BUILD_INFO.applicationVersion,
        snapshot_calculation_versions: versions,
        metric_versions: metricVersions(cleanData),
        source_revision: RESEARCH_BUILD_INFO.sourceRevision,
        source_tree_dirty: RESEARCH_BUILD_INFO.sourceTreeDirty
      },
      parameters,
      exported_at: exportedAt.toISOString(),
      input_fingerprints: fingerprintRows,
      data_sha256: dataSha256
    },
    data: cleanData
  };
}

const CSV_COLUMNS = [
  'metric_key', 'value', 'unit', 'period', 'formula', 'filter', 'missing', 'uncertainty', 'numerator', 'denominator', 'sample_size', 'limitation', 'status',
  'snapshot_ids', 'calculation_code_version', 'parameters', 'exported_at', 'input_fingerprints', 'data_sha256'
] as const;

function csvCell(value: unknown): string {
  let text: string;
  if (value === null || value === undefined) text = '';
  else if (typeof value === 'object') text = canonicalJson(value);
  else text = String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

export async function buildCsvExport(exported: ResearchExport): Promise<string> {
  const rows = collectMetricRows(exported.data).sort((left, right) => left.metric_key.localeCompare(right.metric_key, 'en'));
  if (rows.length === 0) throw new Error('Нет документированных метрик для CSV-экспорта.');
  const csvDataSha256 = await sha256Hex(rows);
  const versions = canonicalJson(exported.metadata.calculation_code_version);
  const parameters = canonicalJson(exported.metadata.parameters);
  const fingerprints = canonicalJson(exported.metadata.input_fingerprints);
  const metadataColumns = [
    exported.metadata.snapshot_ids,
    versions,
    parameters,
    exported.metadata.exported_at,
    fingerprints,
    csvDataSha256
  ];
  const header = CSV_COLUMNS.map(csvCell).join(',');
  const body = rows.map((row) => [
    row.metric_key,
    row.value,
    row.unit,
    row.period,
    row.formula,
    row.filter,
    row.missing,
    row.uncertainty,
    row.numerator,
    row.denominator,
    row.sample_size,
    row.limitation,
    row.status,
    ...metadataColumns
  ].map(csvCell).join(','));
  return [header, ...body].join('\r\n');
}

function escapeXml(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&apos;');
}

export type ChartValue = { label: string; value: number };

export async function buildSvgExport(
  title: string,
  unit: string,
  values: readonly ChartValue[],
  exported: ResearchExport,
  parameters: Record<string, unknown>
): Promise<string> {
  if (values.length === 0 || values.some((entry) => !Number.isFinite(entry.value))) {
    throw new Error('Для SVG нет конечных документированных значений.');
  }
  const chartData = { title, unit, values };
  const dataSha256 = await sha256Hex(chartData);
  const metadata: ExportMetadata = { ...exported.metadata, parameters, data_sha256: dataSha256 };
  const width = 960;
  const labelWidth = 260;
  const plotWidth = 600;
  const rowHeight = 38;
  const height = 120 + values.length * rowHeight;
  const maxValue = Math.max(...values.map((entry) => Math.abs(entry.value)), 1);
  const bars = values.map((entry, index) => {
    const y = 91 + index * rowHeight;
    const barWidth = (Math.abs(entry.value) / maxValue) * plotWidth;
    return `<g><text x="16" y="${y + 17}" font-size="14">${escapeXml(entry.label)}</text><rect x="${labelWidth}" y="${y}" width="${barWidth.toFixed(2)}" height="22" rx="5" fill="#2f5f9e"/><text x="${labelWidth + barWidth + 10}" y="${y + 17}" font-size="14">${escapeXml(String(entry.value))} ${escapeXml(unit)}</text></g>`;
  }).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description"><title id="title">${escapeXml(title)}</title><desc id="description">Описательные значения из AnalyticsSnapshot ${escapeXml(metadata.snapshot_ids.join(', '))}. См. встроенные метаданные для методики, параметров и ограничений.</desc><metadata id="siderfold-export-metadata">${escapeXml(canonicalJson(metadata))}</metadata><rect width="100%" height="100%" fill="#fbf8f1"/><text x="16" y="36" font-size="21" font-weight="700" fill="#10100f">${escapeXml(title)}</text><text x="16" y="61" font-size="12" fill="#39404a">Единица: ${escapeXml(unit)} · срез: ${escapeXml(String(exported.data.snapshot.as_of ?? 'неизвестно'))}</text>${bars}</svg>`;
}
