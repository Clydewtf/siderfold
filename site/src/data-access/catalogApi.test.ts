import { describe, expect, it, vi } from 'vitest';
import {
  CatalogApiError,
  createCatalogApiClient,
  type ProgramDetailDto,
  type ProgramListItemDto
} from './catalogApi';

const source = {
  id: 'source-1',
  name: 'Источник',
  canonical_url: 'https://example.org'
};

const sourceLink = {
  source,
  source_url: 'https://example.org/programs/one',
  observed_at: '2025-02-14T10:30:00Z'
};

const listItem: ProgramListItemDto = {
  id: 'program-1',
  title: 'Программа',
  publication_status: 'published',
  published_at: '2025-02-10T09:00:00Z',
  updated_at: '2025-02-14T10:30:00Z',
  deadline_on: null,
  funding: {
    value_kind: 'unknown',
    currency_code: null,
    exact_amount: null,
    min_amount: null,
    max_amount: null
  },
  primary_source: sourceLink
};

const detail: ProgramDetailDto = {
  ...listItem,
  sources: [sourceLink],
  geographies: [{ slug: 'russia', name: 'Россия' }],
  themes: [{ slug: 'science', name: 'Наука' }]
};

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' }
  });
}

describe('catalog API client', () => {
  it('serializes public catalog filters and parses the response', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => response({
      items: [listItem],
      page: 2,
      page_size: 20,
      total: 21
    }));
    const client = createCatalogApiClient({ baseUrl: 'https://api.example.org/api/v1', fetcher });

    const result = await client.listPrograms({
      page: 2,
      pageSize: 20,
      sort: 'updated_at',
      order: 'asc',
      query: '  грант  ',
      sourceId: 'source-1',
      theme: 'science',
      geography: 'russia',
      fundingKind: 'unknown',
      deadlineFrom: '2025-01-01',
      deadlineTo: '2025-12-31'
    });

    expect(result.items[0].funding?.value_kind).toBe('unknown');
    const requestUrl = new URL(String(fetcher.mock.calls[0]?.[0]));
    expect(requestUrl.pathname).toBe('/api/v1/programs');
    expect(requestUrl.searchParams.get('page')).toBe('2');
    expect(requestUrl.searchParams.get('page_size')).toBe('20');
    expect(requestUrl.searchParams.get('q')).toBe('грант');
    expect(requestUrl.searchParams.get('source_id')).toBe('source-1');
    expect(requestUrl.searchParams.get('funding_kind')).toBe('unknown');
    expect(requestUrl.searchParams.get('deadline_from')).toBe('2025-01-01');
    expect(requestUrl.searchParams.get('deadline_to')).toBe('2025-12-31');
  });

  it('parses the public detail and rejects non-public or malformed responses', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => response(detail));
    const client = createCatalogApiClient({ baseUrl: 'https://api.example.org/api/v1', fetcher });

    const result = await client.getProgram('program-1');
    expect(result.themes[0]?.name).toBe('Наука');
    expect(result.sources[0]?.source_url).toBe('https://example.org/programs/one');

    const privateClient = createCatalogApiClient({
      baseUrl: 'https://api.example.org/api/v1',
      fetcher: vi.fn(async () => response({ ...detail, publication_status: 'draft' }))
    });
    await expect(privateClient.getProgram('program-1')).rejects.toMatchObject({
      kind: 'invalid_response'
    });

    const malformedClient = createCatalogApiClient({
      baseUrl: 'https://api.example.org/api/v1',
      fetcher: vi.fn(async () => response({ ...detail, funding: { ...detail.funding, exact_amount: 'not-a-number' } }))
    });
    await expect(malformedClient.getProgram('program-1')).rejects.toBeInstanceOf(CatalogApiError);
  });

  it('does not expose server error details through the typed client error', async () => {
    const client = createCatalogApiClient({
      baseUrl: 'https://api.example.org/api/v1',
      fetcher: vi.fn(async () => response({ code: 'database_unavailable', detail: 'postgres password' }, 503))
    });

    await expect(client.listPrograms()).rejects.toMatchObject({
      kind: 'http',
      status: 503,
      message: 'Public API request failed.'
    });
  });
});
