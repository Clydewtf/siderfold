import { describe, expect, it } from 'vitest';
import {
  buildCsvExport,
  buildSvgExport,
  canonicalJson,
  collectMetricRows,
  createResearchExport,
  documentedResearchData,
  sha256Hex,
  type ResearchData
} from './export';
import type { ResearchSnapshot } from './api';

const firstId = '11111111-1111-4111-8111-111111111111';
const secondId = '22222222-2222-4222-8222-222222222222';
const exportedAt = new Date('2026-09-26T09:30:00.000Z');

function metric(snapshotId: string, value: unknown, extra: Record<string, unknown> = {}) {
  return {
    value,
    formula: 'control formula',
    unit: 'programs',
    period: { kind: 'point_in_time', as_of: '2026-09-25T00:00:00Z' },
    filter: 'published eligible platform programs',
    missing: 'unknown remains missing',
    sample_size: 4,
    snapshot_id: snapshotId,
    limitation: 'Connected sources only.',
    ...extra
  };
}

function snapshot(snapshotId: string, inputFingerprint: string): ResearchSnapshot {
  return {
    snapshot_id: snapshotId,
    scope: 'published_catalog_quality',
    calculation_version: 'catalog-quality/v3',
    as_of: '2026-09-25T00:00:00Z',
    created_at: '2026-09-25T00:01:00Z',
    freshness_window_days: 30,
    registry_fingerprint: 'c'.repeat(64),
    input_fingerprint: inputFingerprint,
    data_class: 'real',
    program_source_keys: ['potanin-competitions', 'timchenko-competitions'],
    program_count: 4,
    capabilities: { quality: true, baseline: true, regional_indicators: true, network: true, temporal_series: true },
    compatible: true,
    exclusion_reasons: [],
    limitations: ['Only connected sources.']
  };
}

function researchData(): ResearchData {
  return {
    snapshot: {
      snapshot_id: firstId,
      scope: 'published_catalog_quality',
      calculation_version: 'catalog-quality/v3',
      as_of: '2026-09-25T00:00:00Z',
      created_at: '2026-09-25T00:01:00Z',
      freshness_window_days: 30,
      registry_fingerprint: 'c'.repeat(64),
      input_fingerprint: 'a'.repeat(64),
      data_class: 'real',
      program_source_keys: ['potanin-competitions'],
      program_count: 4,
      limitations: ['Only connected sources.']
    },
    quality_metrics: {
      version: 'catalog-quality-metrics/v1',
      snapshot_id: firstId,
      data_class: 'real',
      metrics: {
        freshness: metric(firstId, 0.75, { unit: 'share' }),
        completeness: metric(firstId, 0.5, { unit: 'share' }),
        conflicts: metric(firstId, 0, { unit: 'share' }),
        source_coverage: metric(firstId, 0.5, { unit: 'share' }),
        review_status: metric(firstId, 0.25, { unit: 'share' }),
        undocumented_quality: metric(firstId, 1)
      },
      limitations: ['Snapshot-level quality only.']
    },
    baseline: {
      version: 'catalog-baseline/v1',
      snapshot_id: firstId,
      data_class: 'real',
      period: 'point-in-time',
      metrics: {
        'opportunities.count': metric(firstId, 4, { numerator: 4, denominator: 4 }),
        'unregistered.metric': metric(firstId, 999)
      },
      groups: {},
      method: { finite_frame_proportions: 'descriptive finite frame' }
    },
    regional_indicators: {
      version: 'catalog-regional-indicators/v1',
      snapshot_id: firstId,
      data_class: 'real',
      as_of: '2026-09-25T00:00:00Z',
      period: 'point-in-time',
      unit_of_observation: 'one program',
      denominator_scope: 'connected eligible sources',
      dimensions: {
        geography: {
          coverage: metric(firstId, 0.75),
          categories: { north: metric(firstId, 0.25, { slug: 'north', label: 'North' }) },
          multi_label: true
        }
      },
      composite_index: { status: 'deferred', weights: null },
      limitations: ['Observed incidence only.']
    },
    network: {
      version: 'catalog-network/v1',
      snapshot_id: firstId,
      data_class: 'real',
      as_of: '2026-09-25T00:00:00Z',
      scope: 'published_catalog_quality',
      calculation_version: 'catalog-quality/v3',
      registry_fingerprint: 'c'.repeat(64),
      dimensions: {
        program: {
          dimension: 'program',
          snapshot_id: firstId,
          data_class: 'real',
          metrics: {
            node_count: metric(firstId, 6),
            edge_count: metric(firstId, 4),
            density: metric(firstId, 0.5),
            connected_components: metric(firstId, 2)
          },
          nodes: [{ id: 'private-node' }],
          edges: [{ from: 'private-node', to: 'other-node' }]
        }
      }
    },
    temporal_series: {
      version: 'catalog-temporal/v1',
      frequency: 'weekly',
      data_class: 'real',
      window: { from: '2026-09-01', to: '2026-09-30' },
      selection: 'latest compatible snapshot per week',
      cohorts: [{
        scope: 'published_catalog_quality',
        calculation_version: 'catalog-quality/v3',
        freshness_window_days: 30,
        registry_fingerprint: 'c'.repeat(64),
        data_class: 'real',
        snapshot_ids: [firstId, secondId],
        periods_without_snapshot_are_missing: true,
        points: [{
          period: { start: '2026-09-21', end: '2026-09-27' },
          status: 'computed',
          snapshot_id: secondId,
          as_of: '2026-09-25T00:00:00Z',
          compared_snapshot_id: firstId,
          unit_of_observation: 'one program in frozen snapshot',
          filter: 'eligible real snapshots',
          metrics: {
            'programs.stock': metric(secondId, 4, {
              period: { kind: 'utc_iso_week_snapshot', week_start: '2026-09-21', week_end: '2026-09-27' }
            })
          },
          limitations: ['Observed catalogue state only.']
        }]
      }]
    }
  };
}

describe('documented research exports', () => {
  it('canonicalizes nested objects for reproducible hashes', async () => {
    expect(canonicalJson({ z: 1, a: { y: 2, x: 3 } })).toBe('{"a":{"x":3,"y":2},"z":1}');
    expect(await sha256Hex({ z: 1, a: 2 })).toBe(await sha256Hex({ a: 2, z: 1 }));
  });

  it('sanitizes undocumented metrics and network detail before export', () => {
    const clean = documentedResearchData(researchData());
    expect(clean.quality_metrics?.metrics).toHaveProperty('freshness');
    expect(clean.quality_metrics?.metrics).not.toHaveProperty('undocumented_quality');
    expect(clean.baseline?.metrics).toHaveProperty('opportunities.count');
    expect(clean.baseline?.metrics).not.toHaveProperty('unregistered.metric');
    const network = clean.network?.dimensions as Record<string, Record<string, unknown>>;
    expect(network.program).not.toHaveProperty('nodes');
    expect(network.program).not.toHaveProperty('edges');
    expect(collectMetricRows(clean).some((row) => row.metric_key.endsWith('node_count'))).toBe(true);
    expect(JSON.stringify(clean)).not.toContain('private-node');
  });

  it('normalizes the implemented flat temporal program keys for rows and exports', () => {
    const clean = documentedResearchData(researchData());
    const row = collectMetricRows(clean).find((metricRow) => metricRow.metric_key.endsWith('.metrics.programs.stock'));

    expect(row).toMatchObject({
      value: 4,
      snapshot_id: secondId,
      period: { week_start: '2026-09-21', week_end: '2026-09-27' }
    });
    expect(clean.temporal_series?.cohorts).toHaveLength(1);
  });

  it('repeats complete export metadata and fingerprints referenced real snapshots', async () => {
    const snapshots = [snapshot(firstId, 'a'.repeat(64)), snapshot(secondId, 'b'.repeat(64))];
    const parameters = { frequency: 'weekly', data_class: 'real' };
    const first = await createResearchExport(researchData(), snapshots, parameters, exportedAt);
    const again = await createResearchExport(researchData(), snapshots, parameters, exportedAt);

    expect(first.metadata).toEqual(again.metadata);
    expect(first.metadata.snapshot_ids).toEqual([firstId, secondId]);
    expect(first.metadata.input_fingerprints).toEqual([
      { snapshot_id: firstId, sha256: 'a'.repeat(64) },
      { snapshot_id: secondId, sha256: 'b'.repeat(64) }
    ]);
    expect(first.metadata.calculation_code_version.snapshot_calculation_versions).toEqual({
      [firstId]: 'catalog-quality/v3',
      [secondId]: 'catalog-quality/v3'
    });
    expect(first.metadata.calculation_code_version.metric_versions).toMatchObject({
      quality_metrics: 'catalog-quality-metrics/v1',
      baseline: 'catalog-baseline/v1',
      regional_indicators: 'catalog-regional-indicators/v1',
      network: 'catalog-network/v1',
      temporal_series: 'catalog-temporal/v1'
    });
    expect(first.metadata.calculation_code_version.application_version).toBe('0.9.0');
    expect(first.metadata.calculation_code_version.source_revision).toMatch(/^[a-f0-9]{40}$/i);
    expect(typeof first.metadata.calculation_code_version.source_tree_dirty).toBe('boolean');
    expect(first.metadata.parameters).toEqual(parameters);
    expect(first.metadata.exported_at).toBe('2026-09-26T09:30:00.000Z');
    expect(first.metadata.data_sha256).toMatch(/^[a-f0-9]{64}$/);
  });

  it('refuses non-real data and temporal references without an eligible fingerprint', async () => {
    const data = researchData();
    data.snapshot.data_class = 'synthetic';
    await expect(createResearchExport(data, [snapshot(firstId, 'a'.repeat(64))], {}, exportedAt))
      .rejects.toThrow('только для совместимых snapshot-ов класса real');

    const realData = researchData();
    await expect(createResearchExport(realData, [snapshot(firstId, 'a'.repeat(64))], {}, exportedAt))
      .rejects.toThrow(secondId);

    const mixedData = researchData();
    const cohorts = mixedData.temporal_series?.cohorts as Array<Record<string, unknown>>;
    cohorts[0].data_class = 'synthetic';
    const safeExport = await createResearchExport(mixedData, [snapshot(firstId, 'a'.repeat(64))], {}, exportedAt);
    expect(safeExport.metadata.snapshot_ids).toEqual([firstId]);
    expect(safeExport.data.temporal_series?.cohorts).toEqual([]);
  });

  it('includes export metadata in every CSV row and embeds it in SVG metadata', async () => {
    const exported = await createResearchExport(
      researchData(),
      [snapshot(firstId, 'a'.repeat(64)), snapshot(secondId, 'b'.repeat(64))],
      { view: 'control' },
      exportedAt
    );
    const csv = await buildCsvExport(exported);
    const csvDataSha256 = await sha256Hex(collectMetricRows(exported.data).sort((left, right) => left.metric_key.localeCompare(right.metric_key, 'en')));
    const csvRows = csv.split('\r\n');
    expect(csvRows.length).toBeGreaterThan(2);
    for (const row of csvRows.slice(1)) {
      expect(row).toContain(firstId);
      expect(row).toContain('2026-09-26T09:30:00.000Z');
      expect(row).toContain(csvDataSha256);
    }

    const values = [{ label: 'Источник A', value: 4 }];
    const svg = await buildSvgExport('Тест', 'программы', values, exported, { figure: 'control' });
    const parsed = new DOMParser().parseFromString(svg, 'image/svg+xml');
    const embedded = JSON.parse(parsed.querySelector('metadata')?.textContent ?? '{}') as Record<string, unknown>;
    expect(parsed.querySelector('parsererror')).toBeNull();
    expect(embedded.snapshot_ids).toEqual([firstId, secondId]);
    expect(embedded.exported_at).toBe(exported.metadata.exported_at);
    expect(embedded.data_sha256).toBe(await sha256Hex({ title: 'Тест', unit: 'программы', values }));
    expect(embedded.parameters).toEqual({ figure: 'control' });
  });
});
