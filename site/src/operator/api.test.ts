import { describe, expect, it, vi } from 'vitest';
import { createOperatorApiClient, OperatorApiError } from './api';

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' }
  });
}

describe('operator API client', () => {
  it('uses the supplied token only as an internal authorization header', async () => {
    const fetcher = vi.fn(async () => response([]));
    const client = createOperatorApiClient({
      token: 'local-operator-token',
      baseUrl: 'https://localhost.test/api/internal/v1',
      fetcher
    });

    await client.listReviewCases();

    expect(fetcher).toHaveBeenCalledWith(
      'https://localhost.test/api/internal/v1/review/cases?limit=1000',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer local-operator-token' })
      })
    );
  });

  it('adds a fresh idempotency header to internal write requests', async () => {
    const fetcher = vi.fn(async () => response({
      operation_id: 'operation-1',
      replayed: false,
      review_case_id: 'case-1',
      staged_record_id: 'staged-1',
      review_action_id: 'action-1',
      program_id: 'program-1',
      review_decision_id: 'decision-1'
    }));
    const client = createOperatorApiClient({
      token: 'local-operator-token',
      baseUrl: 'https://localhost.test/api/internal/v1',
      fetcher
    });

    await client.applyReviewAction(
      'case-1',
      { action: 'accept', reason: 'Поля сверены.' },
      'operator-ui:accept:one'
    );

    expect(fetcher).toHaveBeenCalledWith(
      'https://localhost.test/api/internal/v1/review/cases/case-1/actions',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer local-operator-token',
          'Idempotency-Key': 'operator-ui:accept:one'
        })
      })
    );
  });

  it('sends a correction version to the review case endpoint', async () => {
    const fetcher = vi.fn(async () => response({
      operation_id: 'operation-1',
      replayed: false,
      review_case_id: 'case-1',
      staged_record_id: 'staged-1',
      review_revision_id: 'revision-1',
      revision_number: 1,
      changed_fields: ['summary'],
      resolved_issue_ids: []
    }));
    const client = createOperatorApiClient({
      token: 'local-operator-token',
      baseUrl: 'https://localhost.test/api/internal/v1',
      fetcher
    });

    await client.saveReviewRevision(
      'case-1',
      {
        reason: 'Описание сверено с источником.',
        patch: { summary: 'Проверенное описание.' },
        resolve_issue_ids: []
      },
      'operator-ui:save-revision:one'
    );

    expect(fetcher).toHaveBeenCalledWith(
      'https://localhost.test/api/internal/v1/review/cases/case-1/revisions',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer local-operator-token',
          'Idempotency-Key': 'operator-ui:save-revision:one'
        }),
        body: JSON.stringify({
          reason: 'Описание сверено с источником.',
          patch: { summary: 'Проверенное описание.' },
          resolve_issue_ids: []
        })
      })
    );
  });

  it('does not expose internal backend error details to the operator UI', async () => {
    const client = createOperatorApiClient({
      token: 'local-operator-token',
      fetcher: vi.fn(async () => response({ detail: 'database password should not leak' }, 503))
    });

    await expect(client.listReviewCases()).rejects.toEqual(
      new OperatorApiError('http', 'Internal API request failed.', 503)
    );
  });
});
