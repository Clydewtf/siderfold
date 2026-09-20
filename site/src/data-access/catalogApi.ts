export const fundingKinds = [
  'exact',
  'minimum',
  'maximum',
  'range',
  'unknown',
  'not_stated'
] as const;

export const sourceStatuses = ['unknown', 'open', 'closed', 'completed', 'upcoming'] as const;
export const accessModes = ['unknown', 'open', 'invitation_only'] as const;
export const fundingScopes = ['announced_total', 'per_recipient', 'per_program', 'awarded_total', 'other'] as const;
export const timelineEventKinds = ['application', 'application_open', 'application_close', 'evaluation', 'results', 'contracting', 'implementation', 'other'] as const;
export const resourceKinds = ['application', 'competition_document', 'program_document', 'result', 'detail', 'reference'] as const;

export type FundingKind = (typeof fundingKinds)[number];
export type SourceStatus = (typeof sourceStatuses)[number];
export type AccessMode = (typeof accessModes)[number];
export type FundingScope = (typeof fundingScopes)[number];
export type TimelineEventKind = (typeof timelineEventKinds)[number];
export type ResourceKind = (typeof resourceKinds)[number];
export type CatalogSort = 'published_at' | 'updated_at' | 'deadline' | 'title' | 'relevance';
export type SortOrder = 'asc' | 'desc';

export type ProgramQuery = {
  page?: number;
  pageSize?: number;
  sort?: CatalogSort;
  order?: SortOrder;
  query?: string;
  sourceId?: string;
  sourceStatus?: SourceStatus;
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

export type FundingAmountDto = FundingDto & {
  scope: FundingScope;
  label: string | null;
};

export type TimelineEventDto = {
  kind: TimelineEventKind;
  label: string;
  start_on: string | null;
  end_on: string | null;
  date_label?: string | null;
};

export type ProgramResourceDto = {
  kind: ResourceKind;
  title: string | null;
  url: string;
  source_section: string | null;
};

export type ProgramContentSectionDto = {
  heading: string;
  category: string;
  content: string;
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
  source_published_on?: string | null;
  summary?: string | null;
  source_status?: SourceStatus;
  deadline_on: string | null;
  funding: FundingDto | null;
  primary_source: SourceLinkDto;
  geographies?: TaxonomyDto[];
  themes?: TaxonomyDto[];
};

export type ProgramDetailDto = ProgramListItemDto & {
  sources: SourceLinkDto[];
  geographies: TaxonomyDto[];
  themes: TaxonomyDto[];
  summary?: string | null;
  eligibility_summary?: string | null;
  eligibility_geography_note?: string | null;
  source_status?: SourceStatus;
  access_mode?: AccessMode;
  application_url?: string | null;
  application_start_on?: string | null;
  application_end_on?: string | null;
  funding_amounts?: FundingAmountDto[];
  timeline?: TimelineEventDto[];
  resources?: ProgramResourceDto[];
  content_sections?: ProgramContentSectionDto[];
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

function optionalNullableString(value: unknown, field: string): string | null {
  return value === undefined ? null : nullableString(value, field);
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

function enumValue<T extends string>(value: unknown, values: readonly T[], field: string): T {
  if (typeof value !== 'string' || !values.includes(value as T)) {
    throw new CatalogApiError('invalid_response', `Invalid public API field: ${field}`);
  }
  return value as T;
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

function parseFundingAmount(value: unknown, prefix: string): FundingAmountDto {
  const funding = parseFunding(value);
  if (!funding || !isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    ...funding,
    scope: enumValue(value.scope, fundingScopes, `${prefix}.scope`),
    label: nullableString(value.label, `${prefix}.label`)
  };
}

function parseTimelineEvent(value: unknown, prefix: string): TimelineEventDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    kind: enumValue(value.kind, timelineEventKinds, `${prefix}.kind`),
    label: requiredString(value.label, `${prefix}.label`),
    start_on: nullableString(value.start_on, `${prefix}.start_on`),
    end_on: nullableString(value.end_on, `${prefix}.end_on`),
    date_label: optionalNullableString(value.date_label, `${prefix}.date_label`)
  };
}

function parseResource(value: unknown, prefix: string): ProgramResourceDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    kind: enumValue(value.kind, resourceKinds, `${prefix}.kind`),
    title: nullableString(value.title, `${prefix}.title`),
    url: requiredString(value.url, `${prefix}.url`),
    source_section: nullableString(value.source_section, `${prefix}.source_section`)
  };
}

function parseContentSection(value: unknown, prefix: string): ProgramContentSectionDto {
  if (!isRecord(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API object: ${prefix}`);
  }
  return {
    heading: requiredString(value.heading, `${prefix}.heading`),
    category: requiredString(value.category, `${prefix}.category`),
    content: requiredString(value.content, `${prefix}.content`)
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

function parseTaxonomyList(value: unknown, prefix: string): TaxonomyDto[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) {
    throw new CatalogApiError('invalid_response', `Invalid public API collection: ${prefix}`);
  }
  return value.map((item, index) => parseTaxonomy(item, `${prefix}[${index}]`));
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
    source_published_on: value.source_published_on === undefined
      ? null
      : nullableString(value.source_published_on, `${prefix}.source_published_on`),
    summary: optionalNullableString(value.summary, `${prefix}.summary`),
    source_status: value.source_status === undefined
      ? 'unknown'
      : enumValue(value.source_status, sourceStatuses, `${prefix}.source_status`),
    deadline_on: nullableString(value.deadline_on, `${prefix}.deadline_on`),
    funding: parseFunding(value.funding),
    primary_source: parseSourceLink(value.primary_source, `${prefix}.primary_source`),
    geographies: parseTaxonomyList(value.geographies, `${prefix}.geographies`),
    themes: parseTaxonomyList(value.themes, `${prefix}.themes`)
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
  const fundingAmounts = value.funding_amounts === undefined ? [] : value.funding_amounts;
  const timeline = value.timeline === undefined ? [] : value.timeline;
  const resources = value.resources === undefined ? [] : value.resources;
  const contentSections = value.content_sections === undefined ? [] : value.content_sections;
  if (!Array.isArray(fundingAmounts) || !Array.isArray(timeline) || !Array.isArray(resources) || !Array.isArray(contentSections)) {
    throw new CatalogApiError('invalid_response', 'Invalid public API program detail collections.');
  }
  return {
    ...base,
    sources: value.sources.map((item, index) => parseSourceLink(item, `program.sources[${index}]`)),
    geographies: value.geographies.map((item, index) => parseTaxonomy(item, `program.geographies[${index}]`)),
    themes: value.themes.map((item, index) => parseTaxonomy(item, `program.themes[${index}]`)),
    summary: optionalNullableString(value.summary, 'program.summary'),
    eligibility_summary: optionalNullableString(value.eligibility_summary, 'program.eligibility_summary'),
    eligibility_geography_note: optionalNullableString(value.eligibility_geography_note, 'program.eligibility_geography_note'),
    source_status: value.source_status === undefined
      ? 'unknown'
      : enumValue(value.source_status, sourceStatuses, 'program.source_status'),
    access_mode: value.access_mode === undefined
      ? 'unknown'
      : enumValue(value.access_mode, accessModes, 'program.access_mode'),
    application_url: optionalNullableString(value.application_url, 'program.application_url'),
    application_start_on: optionalNullableString(value.application_start_on, 'program.application_start_on'),
    application_end_on: optionalNullableString(value.application_end_on, 'program.application_end_on'),
    funding_amounts: fundingAmounts.map((item, index) => parseFundingAmount(item, `program.funding_amounts[${index}]`)),
    timeline: timeline.map((item, index) => parseTimelineEvent(item, `program.timeline[${index}]`)),
    resources: resources.map((item, index) => parseResource(item, `program.resources[${index}]`)),
    content_sections: contentSections.map((item, index) => parseContentSection(item, `program.content_sections[${index}]`))
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
  queryValue(params, 'source_status', query.sourceStatus);
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
