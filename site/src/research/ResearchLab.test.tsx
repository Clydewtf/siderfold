import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ResearchLabApp } from './ResearchLab';

const snapshotId = '11111111-1111-4111-8111-111111111111';

function metric(name: string, value: number) {
  return {
    value,
    formula: 'numerator / denominator; null when denominator = 0',
    unit: 'share',
    period: { kind: 'point_in_time', as_of: '2026-09-25T12:00:00Z' },
    filter: 'eligible records in the frozen snapshot',
    missing: 'null when the denominator is zero',
    numerator: value * 10,
    denominator: 10,
    sample_size: 10,
    snapshot_id: snapshotId,
    limitation: `${name}: connected sources only.`,
    status: 'computed'
  };
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' }
  });
}

describe('research quality panel', () => {
  it('loads and displays only snapshot-bound documented quality metrics', async () => {
    const qualityMetrics = {
      freshness: metric('freshness', 0.6),
      completeness: metric('completeness', 0.8),
      conflicts: metric('conflicts', 0.1),
      source_coverage: metric('source coverage', 0.5),
      review_status: metric('review status', 0.2),
      undocumented_quality: metric('undocumented', 1)
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/analytics/snapshots')) {
        return jsonResponse({
          items: [{
            snapshot_id: snapshotId,
            scope: 'published_catalog_quality',
            calculation_version: 'catalog-quality/v3',
            as_of: '2026-09-25T12:00:00Z',
            created_at: '2026-09-25T12:01:00Z',
            freshness_window_days: 30,
            registry_fingerprint: 'a'.repeat(64),
            input_fingerprint: 'b'.repeat(64),
            data_class: 'real',
            program_source_keys: ['potanin-competitions'],
            program_count: 10,
            capabilities: { quality: true, baseline: true, regional_indicators: true, network: true, temporal_series: true },
            compatible: true,
            exclusion_reasons: [],
            limitations: ['Connected sources only.']
          }],
          class_counts: { real: 1, test: 0, synthetic: 0, unknown: 0 }
        });
      }
      if (url.endsWith(`/analytics/snapshots/${snapshotId}/quality`)) {
        return jsonResponse({
          snapshot_id: snapshotId,
          scope: 'published_catalog_quality',
          calculation_version: 'catalog-quality/v3',
          as_of: '2026-09-25T12:00:00Z',
          input_fingerprint: 'b'.repeat(64),
          data_class: 'real',
          quality: {
            version: 'catalog-quality-metrics/v1',
            snapshot_id: snapshotId,
            data_class: 'real',
            metrics: qualityMetrics,
            limitations: ['Connected sources only.']
          }
        });
      }
      if (url.endsWith(`/analytics/snapshots/${snapshotId}/baseline`)) {
        return jsonResponse({
          snapshot_id: snapshotId,
          scope: 'published_catalog_quality',
          calculation_version: 'catalog-quality/v3',
          as_of: '2026-09-25T12:00:00Z',
          input_fingerprint: 'b'.repeat(64),
          data_class: 'real',
          baseline: { version: 'catalog-baseline/v1', snapshot_id: snapshotId, data_class: 'real', metrics: {}, groups: {}, method: {} }
        });
      }
      if (url.endsWith(`/analytics/snapshots/${snapshotId}/regional-indicators`)) {
        return jsonResponse({
          snapshot_id: snapshotId,
          scope: 'published_catalog_quality',
          calculation_version: 'catalog-quality/v3',
          as_of: '2026-09-25T12:00:00Z',
          input_fingerprint: 'b'.repeat(64),
          data_class: 'real',
          regional_indicators: { version: 'catalog-regional-indicators/v1', snapshot_id: snapshotId, data_class: 'real', dimensions: {} }
        });
      }
      if (url.endsWith(`/analytics/snapshots/${snapshotId}/network`)) {
        return jsonResponse({
          snapshot_id: snapshotId,
          scope: 'published_catalog_quality',
          calculation_version: 'catalog-quality/v3',
          as_of: '2026-09-25T12:00:00Z',
          input_fingerprint: 'b'.repeat(64),
          data_class: 'real',
          network: { version: 'catalog-network/v1', snapshot_id: snapshotId, data_class: 'real', dimensions: {} }
        });
      }
      throw new Error(`Unexpected research API URL: ${url}`);
    }));

    render(<ResearchLabApp />);
    fireEvent.change(screen.getByLabelText('Токен внутреннего API'), { target: { value: 'local-test-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Открыть лабораторию' }));

    const panel = await screen.findByRole('region', { name: 'Качество данных выбранного среза' });
    expect(within(panel).getByText('Полнота обязательных полей')).toBeTruthy();
    expect(within(panel).getByText(/80\s*%/)).toBeTruthy();
    expect(within(panel).queryByText('undocumented_quality')).toBeNull();
    await waitFor(() => expect(screen.getByText(/Версия приложения 0\.9\.0; Git/)).toBeTruthy());
  });
});
