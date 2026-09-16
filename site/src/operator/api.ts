import type {
  AccessMode,
  FundingAmountDto,
  FundingDto,
  ProgramContentSectionDto,
  ProgramResourceDto,
  SourceStatus,
  TaxonomyDto,
  TimelineEventDto
} from '../data-access/catalogApi';

export type ReviewCaseStatus = 'open' | 'needs_clarification' | 'resolved';
export type QualitySeverity = 'warning' | 'error';
export type ReviewActionKind = 'accept' | 'reject' | 'merge' | 'needs_clarification';
export type DiscoveryActionKind = 'link_to_registered_source' | 'reject' | 'needs_clarification';

export type ReviewQueueItem = {
  review_case_id: string;
  staged_record_id: string;
  status: ReviewCaseStatus;
  opened_at: string;
  reason_codes: string[];
  title: string | null;
  source_url: string | null;
};

export type QualityIssue = {
  id: string;
  staged_record_id: string;
  record_key: string;
  staged_state: string;
  source_id: string;
  severity: QualitySeverity;
  code: string;
  message: string;
  created_at: string;
  review_case_id: string | null;
  resolution: ReviewIssueResolution | null;
};

export type ReviewIssueResolution = {
  id: string;
  review_revision_id: string;
  reason: string;
  actor: string;
  created_at: string;
};

export type ReviewAction = {
  id: string;
  action: ReviewActionKind | 'auto_merge';
  reason: string;
  actor: string;
  deduplication_match_id: string | null;
  target_staged_record_id: string | null;
  target_program_id: string | null;
  review_decision_id: string | null;
  prior_values: Record<string, unknown>;
  result_values: Record<string, unknown>;
  created_at: string;
};

export type ReviewRevision = {
  id: string;
  revision_number: number;
  changed_fields: string[];
  deduplication_snapshot: Record<string, unknown>;
  reason: string;
  actor: string;
  created_at: string;
  resolved_issue_ids: string[];
};

export type ReviewProvenance = {
  source_id: string;
  source_name: string;
  source_canonical_url: string;
  source_url: string;
  raw_capture_id: string;
  ingestion_run_id: string;
  received_at: string;
  content_sha256: string;
  content_format: string;
  adapter_name: string;
  adapter_version: string;
};

export type ReviewPublicPreview = {
  title: string;
  source: { id: string; name: string; canonical_url: string };
  source_url: string;
  observed_at: string;
  source_published_on: string | null;
  summary: string | null;
  source_status: SourceStatus;
  deadline_on: string | null;
  funding: FundingDto | null;
  geographies: TaxonomyDto[];
  themes: TaxonomyDto[];
  eligibility_summary: string | null;
  eligibility_geography_note: string | null;
  access_mode: AccessMode;
  application_url: string | null;
  application_start_on: string | null;
  application_end_on: string | null;
  funding_amounts: FundingAmountDto[];
  timeline: TimelineEventDto[];
  resources: ProgramResourceDto[];
  content_sections: ProgramContentSectionDto[];
};

export type ReviewCaseDetail = ReviewQueueItem & {
  opened_snapshot: Record<string, unknown>;
  source_record: Record<string, unknown>;
  effective_record: Record<string, unknown>;
  provenance: ReviewProvenance;
  quality_issues: QualityIssue[];
  actions: ReviewAction[];
  revisions: ReviewRevision[];
  public_preview: ReviewPublicPreview;
};

export type CanonicalReviewResult = {
  operation_id: string;
  replayed: boolean;
  review_case_id: string;
  staged_record_id: string;
  review_action_id: string;
  program_id: string | null;
  review_decision_id: string | null;
};

export type ReviewRevisionResult = {
  operation_id: string;
  replayed: boolean;
  review_case_id: string;
  staged_record_id: string;
  review_revision_id: string;
  revision_number: number;
  changed_fields: string[];
  resolved_issue_ids: string[];
};

export type DiscoveryReviewItem = {
  review_case_id: string;
  status: ReviewCaseStatus;
  subject_type: 'message' | 'url';
  subject_reference: string;
  opened_at: string;
  reason_codes: string[];
};

export type DiscoveryReviewResult = {
  operation_id: string;
  replayed: boolean;
  review_case_id: string;
  discovery_review_action_id: string;
  status: ReviewCaseStatus;
  target_source_key: string | null;
};

export type SourceDefinition = {
  source_key: string;
  name: string;
  canonical_url: string;
  allowed_url_prefixes: string[];
  allowed_exact_urls: string[];
  access_method: string;
  schedule: string;
  status: string;
  responsible: string;
  adapter_name: string;
  adapter_version: string;
};

export type ExecutionRun = {
  id: string;
  source_id: string;
  source_key: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  ingestion_run_id: string | null;
  attempt_count: number;
  result_kind: string | null;
  error_codes: string[];
  metrics: Record<string, unknown>;
};

export type IngestionRun = {
  id: string;
  source_id: string;
  adapter_name: string;
  adapter_version: string;
  status: string;
  received_at: string;
  started_at: string | null;
  finished_at: string | null;
  raw_capture_count: number;
  staged_record_count: number;
  quality_issue_count: number;
  quality_error_count: number;
  run_statistics: Record<string, unknown>;
};

export type PublicationResult = {
  operation_id: string;
  replayed: boolean;
  program_id: string;
  review_case_id: string;
  review_decision_id: string;
  program_publication_action_id: string;
  published_at?: string;
  archived_at?: string;
};

export type OperatorApiClient = {
  listReviewCases: () => Promise<ReviewQueueItem[]>;
  getReviewCase: (reviewCaseId: string) => Promise<ReviewCaseDetail>;
  listQualityIssues: () => Promise<QualityIssue[]>;
  listDiscoveryCases: () => Promise<DiscoveryReviewItem[]>;
  listSourceDefinitions: () => Promise<SourceDefinition[]>;
  listExecutionRuns: () => Promise<ExecutionRun[]>;
  listIngestionRuns: () => Promise<IngestionRun[]>;
  applyReviewAction: (
    reviewCaseId: string,
    payload: { action: ReviewActionKind; reason: string; deduplication_match_id?: string },
    idempotencyKey: string
  ) => Promise<CanonicalReviewResult>;
  saveReviewRevision: (
    reviewCaseId: string,
    payload: { reason: string; patch: Record<string, unknown>; resolve_issue_ids?: string[] },
    idempotencyKey: string
  ) => Promise<ReviewRevisionResult>;
  applyDiscoveryAction: (
    reviewCaseId: string,
    payload: { action: DiscoveryActionKind; reason: string; source_key?: string },
    idempotencyKey: string
  ) => Promise<DiscoveryReviewResult>;
  archiveProgram: (programId: string, reason: string, idempotencyKey: string) => Promise<PublicationResult>;
  republishProgram: (programId: string, reason: string, idempotencyKey: string) => Promise<PublicationResult>;
};

export type OperatorApiErrorKind = 'network' | 'unauthorized' | 'http' | 'invalid_response';

export class OperatorApiError extends Error {
  readonly kind: OperatorApiErrorKind;
  readonly status: number | null;

  constructor(kind: OperatorApiErrorKind, message: string, status: number | null = null) {
    super(message);
    this.name = 'OperatorApiError';
    this.kind = kind;
    this.status = status;
  }
}

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

type ClientOptions = {
  token: string;
  baseUrl?: string;
  fetcher?: FetchLike;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function assertRecord(value: unknown): Record<string, unknown> {
  const record = asRecord(value);
  if (!record) {
    throw new OperatorApiError('invalid_response', 'Internal API returned an invalid response.');
  }
  return record;
}

function assertArray<T>(value: unknown): T[] {
  if (!Array.isArray(value)) {
    throw new OperatorApiError('invalid_response', 'Internal API returned an invalid list response.');
  }
  return value as T[];
}

function ensureNonblank(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${field} is required.`);
  return normalized;
}

function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, '')}${path}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 401 || response.status === 404) {
    throw new OperatorApiError('unauthorized', 'Operator access is unavailable.', response.status);
  }
  if (!response.ok) {
    throw new OperatorApiError('http', 'Internal API request failed.', response.status);
  }
  try {
    return await response.json() as T;
  } catch {
    throw new OperatorApiError('invalid_response', 'Internal API returned invalid JSON.');
  }
}

export function createOperatorIdempotencyKey(prefix: string): string {
  const randomId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
  return `operator-ui:${prefix}:${randomId}`;
}

export function createOperatorApiClient({
  token,
  baseUrl = '/api/internal/v1',
  fetcher = fetch
}: ClientOptions): OperatorApiClient {
  const authorization = `Bearer ${ensureNonblank(token, 'Token')}`;

  async function getList<T>(path: string): Promise<T[]> {
    try {
      const response = await fetcher(joinUrl(baseUrl, path), {
        headers: { Accept: 'application/json', Authorization: authorization }
      });
      return assertArray<T>(await parseResponse<unknown>(response));
    } catch (error) {
      if (error instanceof OperatorApiError) throw error;
      throw new OperatorApiError('network', 'Internal API is not reachable.');
    }
  }

  async function getRecord<T>(path: string): Promise<T> {
    try {
      const response = await fetcher(joinUrl(baseUrl, path), {
        headers: { Accept: 'application/json', Authorization: authorization }
      });
      return assertRecord(await parseResponse<unknown>(response)) as T;
    } catch (error) {
      if (error instanceof OperatorApiError) throw error;
      throw new OperatorApiError('network', 'Internal API is not reachable.');
    }
  }

  async function post<T>(path: string, payload: Record<string, unknown>, idempotencyKey: string): Promise<T> {
    try {
      const response = await fetcher(joinUrl(baseUrl, path), {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          Authorization: authorization,
          'Content-Type': 'application/json',
          'Idempotency-Key': ensureNonblank(idempotencyKey, 'Idempotency key')
        },
        body: JSON.stringify(payload)
      });
      return assertRecord(await parseResponse<unknown>(response)) as T;
    } catch (error) {
      if (error instanceof OperatorApiError) throw error;
      throw new OperatorApiError('network', 'Internal API is not reachable.');
    }
  }

  return {
    listReviewCases: () => getList<ReviewQueueItem>('/review/cases?limit=1000'),
    getReviewCase: (reviewCaseId) => getRecord<ReviewCaseDetail>(`/review/cases/${encodeURIComponent(reviewCaseId)}`),
    listQualityIssues: () => getList<QualityIssue>('/quality/issues?limit=1000'),
    listDiscoveryCases: () => getList<DiscoveryReviewItem>('/discovery-review/cases?limit=1000'),
    listSourceDefinitions: () => getList<SourceDefinition>('/source-definitions'),
    listExecutionRuns: () => getList<ExecutionRun>('/runs?limit=100'),
    listIngestionRuns: () => getList<IngestionRun>('/ingestion-runs?limit=100'),
    applyReviewAction: (reviewCaseId, payload, idempotencyKey) => post<CanonicalReviewResult>(
      `/review/cases/${encodeURIComponent(reviewCaseId)}/actions`,
      payload,
      idempotencyKey
    ),
    saveReviewRevision: (reviewCaseId, payload, idempotencyKey) => post<ReviewRevisionResult>(
      `/review/cases/${encodeURIComponent(reviewCaseId)}/revisions`,
      payload,
      idempotencyKey
    ),
    applyDiscoveryAction: (reviewCaseId, payload, idempotencyKey) => post<DiscoveryReviewResult>(
      `/discovery-review/cases/${encodeURIComponent(reviewCaseId)}/actions`,
      payload,
      idempotencyKey
    ),
    archiveProgram: (programId, reason, idempotencyKey) => post<PublicationResult>(
      `/programs/${encodeURIComponent(programId)}/archive`,
      { reason },
      idempotencyKey
    ),
    republishProgram: (programId, reason, idempotencyKey) => post<PublicationResult>(
      `/programs/${encodeURIComponent(programId)}/republish`,
      { reason },
      idempotencyKey
    )
  };
}
