export const fundingKinds = [
  'exact',
  'minimum',
  'maximum',
  'range',
  'unknown',
  'not_stated'
] as const;

export type FundingKind = (typeof fundingKinds)[number];
export type CatalogSort = 'published_at' | 'updated_at' | 'deadline' | 'title' | 'relevance';
export type SortOrder = 'asc' | 'desc';

export type ProgramQuery = {
  page?: number;
  pageSize?: number;
  sort?: CatalogSort;
  order?: SortOrder;
  query?: string;
  sourceId?: string;
  theme?: string;
  geography?: string;
  fundingKind?: FundingKind;
  deadlineFrom?: string;
  deadlineTo?: string;
};

export type SourceQuery = {
  page?: number;
  pageSize?: number;
  sort?: 'name' | 'program_count';
  order?: SortOrder;
  query?: string;
};

export type PublicPageDto<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
};

export type FundingDto = {
  value_kind: FundingKind;
  currency_code: string | null;
  exact_amount: string | number | null;
  min_amount: string | number | null;
  max_amount: string | number | null;
};

export type SourceRefDto = {
  id: string;
  name: string;
  canonical_url: string;
};

export type SourceLinkDto = {
  source: SourceRefDto;
  source_url: string;
  observed_at: string;
};

export type ProgramListItemDto = {
  id: string;
  title: string;
  publication_status: 'published';
  published_at: string;
  updated_at: string;
  deadline_on: string | null;
  funding: FundingDto | null;
  primary_source: SourceLinkDto;
};

export type ProgramDetailDto = ProgramListItemDto & {
  sources: SourceLinkDto[];
  geographies: TaxonomyDto[];
  themes: TaxonomyDto[];
};

export type TaxonomyDto = {
  slug: string;
  name: string;
};

export type SourceDto = SourceRefDto & {
  published_program_count: number;
};

export type SourceFilterDto = SourceRefDto;

export type FiltersDto = {
  sources: SourceFilterDto[];
  geographies: TaxonomyDto[];
  themes: TaxonomyDto[];
  funding_kinds: FundingKind[];
  deadline: {
    min_deadline: string | null;
    max_deadline: string | null;
  };
};

export type CatalogApiClient = {
  listPrograms: (query?: ProgramQuery, signal?: AbortSignal) => Promise<PublicPageDto<ProgramListItemDto>>;
  getProgram: (programId: string, signal?: AbortSignal) => Promise<ProgramDetailDto>;
  listSources: (query?: SourceQuery, signal?: AbortSignal) => Promise<PublicPageDto<SourceDto>>;
  getFilters: (signal?: AbortSignal) => Promise<FiltersDto>;
};

export type CatalogApiErrorKind = 'network' | 'timeout' | 'http' | 'invalid_response';

export class CatalogApiError extends Error {
  readonly kind: CatalogApiErrorKind;
  readonly status: number | null;

  constructor(kind: CatalogApiErrorKind, message: string, status: number | null = null) {
    super(message);
    this.name = 'CatalogApiError';
    this.kind = kind;
    this.status = status;
  }
}

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

type ClientOptions = {
  baseUrl: string;
  fetcher?: FetchLike;
  timeoutMs?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new CatalogApiError('invalid_response', `Invalid public API field: ${field}`);
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null) return null;
  return requiredString(value, field);
}

function numberValue(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API field: ${field}`);
  }
  return value;
}

function fundingKind(value: unknown, field: string): FundingKind {
  if (typeof value !== 'string' || !fundingKinds.includes(value as FundingKind)) {
    throw new CatalogApiError('invalid_response', `Invalid public API field: ${field}`);
  }
  return value as FundingKind;
}

function nullableAmount(value: unknown, field: string): string | number | null {
  if (value === null) return null;
  const numericValue = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  if (!Number.isFinite(numericValue) || numericValue <= 0 || (typeof value === 'string' && value.trim().length === 0)) {
    throw new CatalogApiError('invalid_response', `Invalid public API field: ${field}`);
  }
  return value as string | number;
}

function parseFunding(value: unknown): FundingDto | null {
  if (value === null) return null;
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', 'Invalid public API funding object.');
  }
  return {
    value_kind: fundingKind(value.value_kind, 'funding.value_kind'),
    currency_code: nullableString(value.currency_code, 'funding.currency_code'),
    exact_amount: nullableAmount(value.exact_amount, 'funding.exact_amount'),
    min_amount: nullableAmount(value.min_amount, 'funding.min_amount'),
    max_amount: nullableAmount(value.max_amount, 'funding.max_amount')
  };
}

function parseSourceRef(value: unknown, prefix: string): SourceRefDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    id: requiredString(value.id, `${prefix}.id`),
    name: requiredString(value.name, `${prefix}.name`),
    canonical_url: requiredString(value.canonical_url, `${prefix}.canonical_url`)
  };
}

function parseSourceLink(value: unknown, prefix: string): SourceLinkDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    source: parseSourceRef(value.source, `${prefix}.source`),
    source_url: requiredString(value.source_url, `${prefix}.source_url`),
    observed_at: requiredString(value.observed_at, `${prefix}.observed_at`)
  };
}

function parseTaxonomy(value: unknown, prefix: string): TaxonomyDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    slug: requiredString(value.slug, `${prefix}.slug`),
    name: requiredString(value.name, `${prefix}.name`)
  };
}

function parseProgram(value: unknown, prefix: string): ProgramListItemDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  if (value.publication_status !== 'published') {
    throw new CatalogApiError('invalid_response', `${prefix}.publication_status is not public.`);
  }
  return {
    id: requiredString(value.id, `${prefix}.id`),
    title: requiredString(value.title, `${prefix}.title`),
    publication_status: 'published',
    published_at: requiredString(value.published_at, `${prefix}.published_at`),
    updated_at: requiredString(value.updated_at, `${prefix}.updated_at`),
    deadline_on: nullableString(value.deadline_on, `${prefix}.deadline_on`),
    funding: parseFunding(value.funding),
    primary_source: parseSourceLink(value.primary_source, `${prefix}.primary_source`)
  };
}

function parseDetail(value: unknown): ProgramDetailDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', 'Invalid public API program detail.');
  }
  const base = parseProgram(value, 'program');
  if (!Array.isArray(value.sources) || !Array.isArray(value.geographies) || !Array.isArray(value.themes)) {
    throw new CatalogApiError('invalid_response', 'Invalid public API program detail collections.');
  }
  return {
    ...base,
    sources: value.sources.map((item, index) => parseSourceLink(item, `program.sources[${index}]`)),
    geographies: value.geographies.map((item, index) => parseTaxonomy(item, `program.geographies[${index}]`)),
    themes: value.themes.map((item, index) => parseTaxonomy(item, `program.themes[${index}]`))
  };
}

function parsePage<T>(value: unknown, itemParser: (item: unknown, prefix: string) => T): PublicPageDto<T> {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new CatalogApiError('invalid_response', 'Invalid public API page.');
  }
  return {
    items: value.items.map((item, index) => itemParser(item, `items[${index}]`)),
    page: numberValue(value.page, 'page'),
    page_size: numberValue(value.page_size, 'page_size'),
    total: numberValue(value.total, 'total')
  };
}

function parseSource(value: unknown, prefix: string): SourceDto {
  const source = parseSourceRef(value, prefix);
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    ...source,
    published_program_count: numberValue(value.published_program_count, `${prefix}.published_program_count`)
  };
}

function parseFilters(value: unknown): FiltersDto {
  if (!isRecord(value) || !Array.isArray(value.sources) || !Array.isArray(value.geographies) || !Array.isArray(value.themes) || !Array.isArray(value.funding_kinds) || !isRecord(value.deadline)) {
    throw new CatalogApiError('invalid_response', 'Invalid public API filters.');
  }
  return {
    sources: value.sources.map((item, index) => parseSourceRef(item, `filters.sources[${index}]`)),
    geographies: value.geographies.map((item, index) => parseTaxonomy(item, `filters.geographies[${index}]`)),
    themes: value.themes.map((item, index) => parseTaxonomy(item, `filters.themes[${index}]`)),
    funding_kinds: value.funding_kinds.map((item, index) => fundingKind(item, `filters.funding_kinds[${index}]`)),
    deadline: {
      min_deadline: nullableString(value.deadline.min_deadline, 'filters.deadline.min_deadline'),
      max_deadline: nullableString(value.deadline.max_deadline, 'filters.deadline.max_deadline')
    }
  };
}

function queryValue(params: URLSearchParams, key: string, value: string | number | undefined): void {
  if (value !== undefined && value !== '') params.set(key, String(value));
}

function buildProgramParams(query: ProgramQuery): URLSearchParams {
  const params = new URLSearchParams();
  queryValue(params, 'page', query.page);
  queryValue(params, 'page_size', query.pageSize);
  queryValue(params, 'sort', query.sort);
  queryValue(params, 'order', query.order);
  queryValue(params, 'q', query.query?.trim());
  queryValue(params, 'source_id', query.sourceId);
  queryValue(params, 'theme', query.theme);
  queryValue(params, 'geography', query.geography);
  queryValue(params, 'funding_kind', query.fundingKind);
  queryValue(params, 'deadline_from', query.deadlineFrom);
  queryValue(params, 'deadline_to', query.deadlineTo);
  return params;
}

function buildSourceParams(query: SourceQuery): URLSearchParams {
  const params = new URLSearchParams();
  queryValue(params, 'page', query.page);
  queryValue(params, 'page_size', query.pageSize);
  queryValue(params, 'sort', query.sort);
  queryValue(params, 'order', query.order);
  queryValue(params, 'q', query.query?.trim());
  return params;
}

function joinUrl(baseUrl: string, path: string, params?: URLSearchParams): string {
  const url = `${baseUrl.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`;
  const query = params?.toString();
  return query ? `${url}?${query}` : url;
}

async function requestJson(
  url: string,
  fetcher: FetchLike,
  timeoutMs: number,
  signal?: AbortSignal
): Promise<unknown> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener('abort', abortFromCaller, { once: true });

  try {
    const response = await fetcher(url, { headers: { Accept: 'application/json' }, signal: controller.signal });
    if (!response.ok) {
      throw new CatalogApiError('http', 'Public API request failed.', response.status);
    }
    try {
      return await response.json();
    } catch {
      throw new CatalogApiError('invalid_response', 'Public API returned invalid JSON.');
    }
  } catch (error) {
    if (error instanceof CatalogApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new CatalogApiError('timeout', 'Public API request timed out.');
    }
    throw new CatalogApiError('network', 'Public API is unavailable.');
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener('abort', abortFromCaller);
  }
}

export function createCatalogApiClient({ baseUrl, fetcher = window.fetch.bind(window), timeoutMs = 10_000 }: ClientOptions): CatalogApiClient {
  return {
    async listPrograms(query = {}, signal) {
      const payload = await requestJson(joinUrl(baseUrl, '/programs', buildProgramParams(query)), fetcher, timeoutMs, signal);
      return parsePage(payload, parseProgram);
    },
    async getProgram(programId, signal) {
      const payload = await requestJson(joinUrl(baseUrl, `/programs/${encodeURIComponent(programId)}`), fetcher, timeoutMs, signal);
      return parseDetail(payload);
    },
    async listSources(query = {}, signal) {
      const payload = await requestJson(joinUrl(baseUrl, '/sources', buildSourceParams(query)), fetcher, timeoutMs, signal);
      return parsePage(payload, parseSource);
    },
    async getFilters(signal) {
      const payload = await requestJson(joinUrl(baseUrl, '/filters'), fetcher, timeoutMs, signal);
      return parseFilters(payload);
    }
  };
}

export function publicApiErrorMessage(error: unknown, resource = 'данные'): string {
  if (error instanceof CatalogApiError && error.kind === 'timeout') {
    return `Не удалось вовремя загрузить ${resource}. Попробуйте ещё раз.`;
  }
  return `Не удалось загрузить ${resource}. Попробуйте ещё раз.`;
}
