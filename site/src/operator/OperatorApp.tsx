import { ExternalLink, LogOut, RefreshCw, ShieldCheck } from 'lucide-react';
import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { ApiProgramDrawer } from '../components/ApiProgramDrawer';
import { EmptyState, MetricTile, Tag } from '../components/ui';
import {
  createOperatorApiClient,
  createOperatorIdempotencyKey,
  OperatorApiError,
  type DiscoveryActionKind,
  type DiscoveryReviewItem,
  type ExecutionRun,
  type IngestionRun,
  type OperatorApiClient,
  type QualityIssue,
  type ReviewActionKind,
  type ReviewCaseDetail,
  type ReviewQueueItem,
  type SourceDefinition
} from './api';
import { mapReviewPublicPreview } from './preview';

type OperatorView = 'review' | 'quality' | 'runs' | 'discovery' | 'publication';
type ReviewFilter = 'all' | 'ready' | 'quality' | 'duplicates' | 'clarification';
type ClientFactory = (options: { token: string }) => OperatorApiClient;

type DashboardData = {
  reviewCases: ReviewQueueItem[];
  qualityIssues: QualityIssue[];
  discoveryCases: DiscoveryReviewItem[];
  sourceDefinitions: SourceDefinition[];
  executionRuns: ExecutionRun[];
  ingestionRuns: IngestionRun[];
};

const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'medium',
  timeStyle: 'short'
});

const shortDateFormatter = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'medium'
});

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Не указано';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Не указано' : dateTimeFormatter.format(date);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return 'Не указано';
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return Number.isNaN(date.getTime()) ? 'Не указано' : shortDateFormatter.format(date);
}

function isExternalUrl(value: string | null | undefined): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch {
    return false;
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function errorMessage(error: unknown): string {
  if (error instanceof OperatorApiError) {
    if (error.kind === 'unauthorized') {
      return 'Доступ не подтверждён. Проверь токен и настройки внутреннего API.';
    }
    if (error.kind === 'network') {
      return 'Локальный backend недоступен. Проверь, что API-режим запущен.';
    }
  }
  return 'Операция не выполнена. Обнови данные и повтори её после проверки.';
}

function reviewReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    candidate_ready: 'готово к проверке',
    quality_warning: 'есть предупреждение',
    quality_error: 'есть ошибка качества',
    high_confidence_duplicate: 'точное совпадение',
    exact_identity_conflict: 'конфликт идентичности',
    possible_duplicate: 'возможный дубликат',
    exact_identity_requires_review: 'совпадение требует проверки',
    multiple_candidates: 'несколько совпадений'
  };
  return labels[reason] ?? reason.replaceAll('_', ' ');
}

function isCleanReviewCase(item: ReviewQueueItem, issues: QualityIssue[]): boolean {
  return item.status === 'open'
    && item.reason_codes.length === 1
    && item.reason_codes[0] === 'candidate_ready'
    && issues.length === 0;
}

function QueueStatus({ status }: { status: string }) {
  const labels: Record<string, string> = {
    open: 'Ожидает решения',
    needs_clarification: 'Нужно уточнение',
    resolved: 'Решено',
    warning: 'Предупреждение',
    error: 'Ошибка',
    succeeded: 'Успешно',
    failed: 'Ошибка запуска',
    skipped_locked: 'Пропущено: уже выполняется',
    skipped_rate_limited: 'Пропущено: лимит',
    interrupted: 'Прервано',
    completed: 'Завершён'
  };
  const tone = status.includes('error') || status === 'failed'
    ? 'border-clay/40 bg-clay/10 text-clay'
    : status === 'needs_clarification' || status.includes('warning')
      ? 'border-cobalt/35 bg-cobalt/10 text-cobalt'
      : 'border-moss/35 bg-moss/10 text-moss';
  return <Tag className={tone}>{labels[status] ?? status.replaceAll('_', ' ')}</Tag>;
}

function Panel({
  title,
  description,
  children,
  className = ''
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-ink/10 bg-white/65 p-5 shadow-sm ${className}`}>
      <header>
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-6 text-graphite/80">{description}</p> : null}
      </header>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function AccessGate({
  clientFactory,
  onConnected
}: {
  clientFactory: ClientFactory;
  onConnected: (client: OperatorApiClient) => void;
}) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) {
      setError('Введи токен внутреннего доступа.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const client = clientFactory({ token: token.trim() });
      await client.listReviewCases();
      onConnected(client);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page-container flex min-h-screen items-center" aria-labelledby="operator-access-title">
      <section className="mx-auto w-full max-w-xl rounded-2xl border border-ink/10 bg-white/75 p-6 shadow-panel sm:p-8">
        <div className="flex items-center gap-3 text-cobalt">
          <ShieldCheck className="h-7 w-7" aria-hidden="true" />
          <p className="eyebrow">Локальный операторский доступ</p>
        </div>
        <h1 id="operator-access-title" className="mt-4 text-3xl font-semibold tracking-tight text-ink">Проверка и публикация</h1>
        <p className="mt-3 max-w-lg text-sm leading-6 text-graphite">
          Эта панель работает только с защищённым внутренним API. Токен нужен для текущей вкладки и не сохраняется в браузере или в сборке сайта.
        </p>
        <form className="mt-6 space-y-4" onSubmit={submit}>
          <label className="field-label">
            Токен внутреннего доступа
            <input
              autoComplete="off"
              name="operator-token"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="INTERNAL_API_TOKEN"
            />
          </label>
          {error ? <p role="alert" className="rounded-lg border border-clay/35 bg-clay/10 p-3 text-sm text-clay">{error}</p> : null}
          <button type="submit" disabled={busy} className="button-primary w-full">
            {busy ? 'Проверяем доступ…' : 'Открыть операторскую панель'}
          </button>
        </form>
      </section>
    </main>
  );
}

function ReviewActions({
  detail,
  busy,
  onAction,
  onOpenCorrections
}: {
  detail: ReviewCaseDetail;
  busy: boolean;
  onAction: (action: ReviewActionKind, reason: string, matchId?: string) => Promise<void>;
  onOpenCorrections: () => void;
}) {
  const [selectedAction, setSelectedAction] = useState<ReviewActionKind | null>(null);
  const [reason, setReason] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const snapshot = asRecord(detail.opened_snapshot);
  const matches = Array.isArray(snapshot.matches) ? snapshot.matches.map(asRecord) : [];
  const reviewMatches = matches.filter((match) => asString(match.id) !== null);
  const [selectedMatchId, setSelectedMatchId] = useState<string>('');

  useEffect(() => {
    setSelectedAction(null);
    setReason('');
    setSelectedMatchId('');
    setActionError(null);
  }, [detail.review_case_id]);

  async function confirm() {
    if (!selectedAction || !reason.trim()) return;
    if (selectedAction === 'merge' && !selectedMatchId) return;
    setActionError(null);
    try {
      await onAction(selectedAction, reason.trim(), selectedAction === 'merge' ? selectedMatchId : undefined);
    } catch (error) {
      setActionError(errorMessage(error));
    }
  }

  if (detail.status === 'resolved') {
    return null;
  }

  return (
    <section aria-labelledby="review-actions-title" className="mt-6 rounded-xl border border-ink/15 bg-paper/70 p-4">
      <h3 id="review-actions-title" className="font-semibold text-ink">Решение оператора</h3>
      <p className="mt-1 text-sm leading-6 text-graphite">Любое решение требует причины и записывается в историю. Публикация возможна только без блокирующих ошибок качества.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={busy} className="button-primary" onClick={() => setSelectedAction('accept')}>Принять и опубликовать</button>
        <button type="button" disabled={busy} className="button-secondary" onClick={onOpenCorrections}>Внести правки</button>
        <button type="button" disabled={busy} className="button-secondary" onClick={() => setSelectedAction('needs_clarification')}>Запросить уточнение</button>
        <button type="button" disabled={busy} className="button-secondary" onClick={() => setSelectedAction('reject')}>Отклонить</button>
        {reviewMatches.length > 0 ? <button type="button" disabled={busy} className="button-secondary" onClick={() => setSelectedAction('merge')}>Объединить как дубликат</button> : null}
      </div>

      {selectedAction ? (
        <div className="mt-4 space-y-3 rounded-lg border border-ink/10 bg-white/70 p-4">
          <p className="text-sm font-semibold text-ink">Подтверди действие: {selectedAction === 'accept' ? 'принять и опубликовать' : selectedAction === 'reject' ? 'отклонить' : selectedAction === 'merge' ? 'объединить как дубликат' : 'запросить уточнение'}</p>
          {selectedAction === 'merge' ? (
            <label className="field-label">
              Подтверждённое совпадение
              <select value={selectedMatchId} onChange={(event) => setSelectedMatchId(event.target.value)}>
                <option value="">Выбери совпадение</option>
                {reviewMatches.map((match) => {
                  const id = asString(match.id) ?? '';
                  const targetProgram = asString(match.target_program_id);
                  const targetStage = asString(match.target_staged_record_id);
                  const evidence = asRecord(match.evidence);
                  const level = asString(evidence.match_level) ?? 'сопоставление';
                  return <option key={id} value={id}>{level}: {targetProgram ? `программа ${targetProgram}` : `кандидат ${targetStage ?? 'не указан'}`}</option>;
                })}
              </select>
            </label>
          ) : null}
          <label className="field-label">
            Причина решения
            <textarea
              className="min-h-28 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Например: данные сверены с официальной страницей источника."
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy || !reason.trim() || (selectedAction === 'merge' && !selectedMatchId)}
              className="button-primary"
              onClick={() => void confirm()}
            >
              {busy ? 'Сохраняем…' : 'Подтвердить'}
            </button>
            <button type="button" disabled={busy} className="button-secondary" onClick={() => setSelectedAction(null)}>Отмена</button>
          </div>
          {actionError ? <p role="alert" className="text-sm text-clay">{actionError}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

type ReviewDetailTab = 'source' | 'preview' | 'corrections';

function reviewFieldLabel(key: string): string {
  const labels: Record<string, string> = {
    title: 'Название',
    record_key: 'Ключ записи',
    record_url: 'Страница источника',
    external_id: 'Внешний ID',
    deadline_on: 'Дедлайн',
    funding: 'Финансирование',
    value_kind: 'Тип суммы',
    currency_code: 'Валюта',
    exact_amount: 'Точная сумма',
    min_amount: 'Минимальная сумма',
    max_amount: 'Максимальная сумма',
    payload: 'Извлечённые данные',
    source_status: 'Статус у источника',
    source_title: 'Заголовок на источнике',
    source_published_on: 'Дата публикации у источника',
    source_last_modified_at: 'Последнее изменение у источника',
    application: 'Подача заявки',
    start_on: 'Начало',
    end_on: 'Окончание',
    url: 'Ссылка',
    candidate_urls: 'Найденные варианты ссылок',
    date_evidence: 'Основание для даты',
    timeline: 'График',
    kind: 'Тип',
    label: 'Название',
    evidence: 'Основание',
    taxonomy: 'Тематики и регионы',
    themes: 'Тематики',
    geographies: 'Регионы',
    slug: 'Ключ',
    name: 'Название',
    summary: 'Краткое описание',
    eligibility: 'Условия участия',
    geography_note: 'Территория участия',
    access_mode: 'Условия подачи',
    contacts: 'Контактные лица',
    role: 'Роль',
    email: 'Эл. почта',
    phone: 'Телефон',
    sections: 'Разделы страницы',
    content_inventory: 'Инвентарь содержимого',
    blocks: 'Блоки страницы',
    heading: 'Заголовок блока',
    category: 'Категория',
    text: 'Текст',
    links: 'Ссылки',
    document_urls: 'Документы',
    result_urls: 'Результаты',
    detail_urls: 'Дополнительные страницы',
    inventory: 'Все найденные материалы',
    artifacts: 'Материалы и документы',
    section_title: 'Раздел источника',
    section_category: 'Категория раздела',
    capture: 'Сведения о материале',
    content_format: 'Формат',
    warnings: 'Предупреждения'
  };
  return labels[key] ?? key.replaceAll('_', ' ');
}

function StructuredSourceValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined || value === '') {
    return <span className="text-graphite/70">Не указано</span>;
  }
  if (typeof value === 'string') {
    return isExternalUrl(value) ? (
      <a href={value} target="_blank" rel="noreferrer" className="break-all font-medium text-cobalt hover:underline">{value}</a>
    ) : <span className="whitespace-pre-wrap break-words text-ink">{value}</span>;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return <span className="text-ink">{String(value)}</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-graphite/70">Нет данных</span>;
    return (
      <ol className="space-y-2">
        {value.map((item, index) => <li key={`${depth}-${index}`} className="rounded-md border border-ink/10 bg-white/60 p-3"><StructuredSourceValue value={item} depth={depth + 1} /></li>)}
      </ol>
    );
  }
  const record = asRecord(value);
  const entries = Object.entries(record);
  if (entries.length === 0) return <span className="text-graphite/70">Нет данных</span>;
  return (
    <dl className="space-y-2">
      {entries.map(([key, item]) => (
        <div key={key} className={depth === 0 ? 'rounded-lg border border-ink/10 bg-paper/45 p-3' : ''}>
          <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-graphite/70">{reviewFieldLabel(key)}</dt>
          <dd className="mt-1 text-sm leading-6 text-graphite"><StructuredSourceValue value={item} depth={depth + 1} /></dd>
        </div>
      ))}
    </dl>
  );
}

function SourceDataView({ detail }: { detail: ReviewCaseDetail }) {
  const sourceUrl = asString(detail.source_record.record_url) ?? detail.source_url;
  return (
    <section className="mt-5 space-y-5">
      <div className="rounded-lg border border-ink/10 bg-paper/55 p-4">
        <h3 className="font-semibold text-ink">Происхождение записи</h3>
        <p className="mt-1 text-sm leading-6 text-graphite">Это неизменяемые технические сведения о полученной странице. Полное содержимое RawCapture и путь к локальному файлу здесь намеренно не показываются.</p>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2">
          <DetailField label="Источник" value={detail.provenance.source_name} />
          <DetailField label="Получено" value={formatDateTime(detail.provenance.received_at)} />
          <DetailField label="Адаптер" value={`${detail.provenance.adapter_name} ${detail.provenance.adapter_version}`} />
          <DetailField label="Формат" value={detail.provenance.content_format} />
          <DetailField label="Хеш содержимого" value={detail.provenance.content_sha256} />
          <DetailField label="Raw capture" value={detail.provenance.raw_capture_id} />
        </dl>
        {isExternalUrl(sourceUrl) ? <a href={sourceUrl} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cobalt hover:underline">Открыть официальную страницу <ExternalLink className="h-4 w-4" aria-hidden="true" /></a> : null}
      </div>

      <div className="rounded-lg border border-ink/10 bg-white/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold text-ink">Все собранные данные источника</h3>
          <Tag>{detail.revisions.length > 0 ? `Есть версий правок: ${detail.revisions.length}` : 'Без ручных правок'}</Tag>
        </div>
        <p className="mt-1 text-sm leading-6 text-graphite">Показаны исходные структурированные поля адаптера: включая ссылки, документы, график, блоки страницы и контакты. Ручные правки не изменяют этот слой.</p>
        <div className="mt-4"><StructuredSourceValue value={detail.source_record} /></div>
      </div>
    </section>
  );
}

function sourceIssueLabel(issue: QualityIssue): string {
  if (issue.code.includes('unclassified_content_block')) return 'Нераспознанный блок страницы';
  if (issue.code.includes('application_url_ambiguous')) return 'Неоднозначная ссылка для подачи';
  return reviewReasonLabel(issue.code);
}

function QualityIssues({ issues }: { issues: QualityIssue[] }) {
  return (
    <section className="mt-6">
      <h3 className="font-semibold text-ink">Проблемы качества</h3>
      {issues.length === 0 ? <p className="mt-2 text-sm text-moss">Нет зарегистрированных проблем качества.</p> : (
        <ul className="mt-3 space-y-2">
          {issues.map((issue) => (
            <li key={issue.id} className="rounded-lg border border-ink/10 bg-paper/60 p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><QueueStatus status={issue.severity} /><span className="font-medium text-ink">{sourceIssueLabel(issue)}</span></div>
              <p className="mt-2 text-graphite">{issue.message}</p>
              {issue.resolution ? <p className="mt-2 text-xs leading-5 text-moss">Исправлено версией правок: {issue.resolution.reason} · {issue.resolution.actor} · {formatDateTime(issue.resolution.created_at)}</p> : <p className="mt-2 text-xs text-graphite/70">Код: {issue.code}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type CorrectionResourceKind = 'document' | 'result' | 'reference';

type CorrectionFundingAmount = {
  id: string;
  scope: string;
  label: string;
  valueKind: string;
  currency: string;
  exact: string;
  minimum: string;
  maximum: string;
  evidence: string;
};

type CorrectionTimelineEvent = {
  id: string;
  kind: string;
  label: string;
  startOn: string;
  endOn: string;
  evidence: string;
};

type CorrectionResource = {
  id: string;
  kind: CorrectionResourceKind;
  label: string;
  url: string;
  sectionTitle: string;
  sectionCategory: string;
  contentFormat: string;
};

type CorrectionContentBlock = {
  id: string;
  heading: string;
  category: string;
  text: string;
};

type CorrectionForm = {
  title: string;
  summary: string;
  sourcePublishedOn: string;
  sourceStatus: string;
  deadlineOn: string;
  applicationUrl: string;
  applicationStartOn: string;
  applicationEndOn: string;
  accessMode: string;
  eligibilitySummary: string;
  eligibilityGeographyNote: string;
  themes: string;
  geographies: string;
  fundingKind: string;
  fundingCurrency: string;
  fundingExact: string;
  fundingMinimum: string;
  fundingMaximum: string;
  fundingAmounts: CorrectionFundingAmount[];
  timeline: CorrectionTimelineEvent[];
  resources: CorrectionResource[];
  contentBlocks: CorrectionContentBlock[];
};

let correctionItemSequence = 0;

function correctionItemId(prefix: string): string {
  correctionItemSequence += 1;
  return `${prefix}-${correctionItemSequence}`;
}

function asInputDate(value: string | null): string {
  return value?.slice(0, 10) ?? '';
}

function asInputAmount(value: string | number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value);
}

function isSocialResourceUrl(value: string): boolean {
  try {
    const hostname = new URL(value).hostname.toLocaleLowerCase('en').replace(/^www\./, '');
    return ['t.me', 'telegram.me', 'vk.com', 'vkontakte.ru'].some(
      (host) => hostname === host || hostname.endsWith(`.${host}`)
    );
  } catch {
    return false;
  }
}

function correctionResourceKind(kind: string): CorrectionResourceKind {
  if (kind === 'result') return 'result';
  if (kind === 'reference') return 'reference';
  return 'document';
}

function defaultResourceCategory(kind: CorrectionResourceKind, url: string): string {
  if (kind === 'result') return 'results';
  if (kind === 'reference' && isSocialResourceUrl(url)) return 'official_channels';
  return 'documents';
}

function effectivePayload(detail: ReviewCaseDetail): Record<string, unknown> {
  return asRecord(detail.effective_record.payload);
}

function correctionFundingAmounts(detail: ReviewCaseDetail): CorrectionFundingAmount[] {
  const funding = asRecord(effectivePayload(detail).funding);
  const amounts = Array.isArray(funding.amounts) ? funding.amounts : [];
  return amounts.map((rawAmount) => {
    const amount = asRecord(rawAmount);
    const value = asRecord(amount.value);
    return {
      id: correctionItemId('funding'),
      scope: asString(amount.scope) ?? 'other',
      label: asString(amount.label) ?? '',
      valueKind: asString(value.value_kind) ?? 'not_stated',
      currency: asString(value.currency_code) ?? '',
      exact: asInputAmount(asString(value.exact_amount)),
      minimum: asInputAmount(asString(value.min_amount)),
      maximum: asInputAmount(asString(value.max_amount)),
      evidence: asString(amount.evidence) ?? ''
    };
  });
}

function correctionTimeline(detail: ReviewCaseDetail): CorrectionTimelineEvent[] {
  const rawTimeline = effectivePayload(detail).timeline;
  const events: unknown[] = Array.isArray(rawTimeline) ? rawTimeline : [];
  return events.map((rawEvent) => {
    const event = asRecord(rawEvent);
    return {
      id: correctionItemId('timeline'),
      kind: asString(event.kind) ?? 'other',
      label: asString(event.label) ?? '',
      startOn: asInputDate(asString(event.start_on)),
      endOn: asInputDate(asString(event.end_on)),
      evidence: asString(event.evidence) ?? ''
    };
  });
}

function correctionResources(detail: ReviewCaseDetail): CorrectionResource[] {
  const rawArtifactValues = effectivePayload(detail).artifacts;
  const rawArtifacts = Array.isArray(rawArtifactValues) ? rawArtifactValues.map(asRecord) : [];
  return detail.public_preview.resources.map((resource) => {
    const rawArtifact = rawArtifacts.find((artifact) => asString(artifact.url) === resource.url) ?? {};
    const kind = correctionResourceKind(resource.kind);
    const url = resource.url;
    return {
      id: correctionItemId('resource'),
      kind,
      label: resource.title ?? '',
      url,
      sectionTitle: resource.source_section ?? '',
      sectionCategory: asString(rawArtifact.section_category) ?? defaultResourceCategory(kind, url),
      contentFormat: asString(asRecord(rawArtifact.capture).content_format) ?? ''
    };
  });
}

function correctionContentBlocks(detail: ReviewCaseDetail): CorrectionContentBlock[] {
  return detail.public_preview.content_sections.map((section) => ({
    id: correctionItemId('content'),
    heading: section.heading,
    category: section.category,
    text: section.content
  }));
}

function correctionForm(detail: ReviewCaseDetail): CorrectionForm {
  const preview = detail.public_preview;
  return {
    title: preview.title,
    summary: preview.summary ?? '',
    sourcePublishedOn: asInputDate(preview.source_published_on),
    sourceStatus: preview.source_status,
    deadlineOn: asInputDate(preview.deadline_on),
    applicationUrl: preview.application_url ?? '',
    applicationStartOn: asInputDate(preview.application_start_on),
    applicationEndOn: asInputDate(preview.application_end_on),
    accessMode: preview.access_mode,
    eligibilitySummary: preview.eligibility_summary ?? '',
    eligibilityGeographyNote: preview.eligibility_geography_note ?? '',
    themes: preview.themes.map((item) => item.name).join('\n'),
    geographies: preview.geographies.map((item) => item.name).join('\n'),
    fundingKind: preview.funding?.value_kind ?? 'not_stated',
    fundingCurrency: preview.funding?.currency_code ?? '',
    fundingExact: asInputAmount(preview.funding?.exact_amount),
    fundingMinimum: asInputAmount(preview.funding?.min_amount),
    fundingMaximum: asInputAmount(preview.funding?.max_amount),
    fundingAmounts: correctionFundingAmounts(detail),
    timeline: correctionTimeline(detail),
    resources: correctionResources(detail),
    contentBlocks: correctionContentBlocks(detail)
  };
}

function taxonomyPatch(value: string, existing: { name: string; slug: string }[]) {
  const knownSlugs = new Map(existing.map((item) => [item.name.trim().toLocaleLowerCase('ru'), item.slug]));
  return value.split('\n').map((item) => item.trim()).filter(Boolean).map((name) => ({
    name,
    ...(knownSlugs.get(name.toLocaleLowerCase('ru')) ? { slug: knownSlugs.get(name.toLocaleLowerCase('ru')) } : {})
  }));
}

function fundingValuePatch({
  valueKind,
  currency,
  exact,
  minimum,
  maximum
}: {
  valueKind: string;
  currency: string;
  exact: string;
  minimum: string;
  maximum: string;
}): Record<string, string | null> {
  const base = {
    value_kind: valueKind,
    currency_code: null,
    exact_amount: null,
    min_amount: null,
    max_amount: null
  };
  if (valueKind === 'unknown' || valueKind === 'not_stated') return base;
  if (!currency.trim()) throw new Error('Укажи валюту финансирования.');
  const funding = { ...base, currency_code: currency.trim().toUpperCase() };
  if (valueKind === 'exact') {
    if (!exact.trim()) throw new Error('Укажи точную сумму финансирования.');
    return { ...funding, exact_amount: exact.trim() };
  }
  if (valueKind === 'minimum') {
    if (!minimum.trim()) throw new Error('Укажи минимальную сумму финансирования.');
    return { ...funding, min_amount: minimum.trim() };
  }
  if (valueKind === 'maximum') {
    if (!maximum.trim()) throw new Error('Укажи максимальную сумму финансирования.');
    return { ...funding, max_amount: maximum.trim() };
  }
  if (!minimum.trim() || !maximum.trim()) throw new Error('Укажи обе границы финансирования.');
  return { ...funding, min_amount: minimum.trim(), max_amount: maximum.trim() };
}

function reviewFundingPatch(form: CorrectionForm): Record<string, string | null> {
  return fundingValuePatch({
    valueKind: form.fundingKind,
    currency: form.fundingCurrency,
    exact: form.fundingExact,
    minimum: form.fundingMinimum,
    maximum: form.fundingMaximum
  });
}

function optionalText(value: string): string | null {
  return value.trim() || null;
}

function sameTaxonomyNames(left: string, right: string): boolean {
  const normalize = (value: string) => value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right));
}

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function fundingAmountPatchItems(items: CorrectionFundingAmount[]): Record<string, unknown>[] {
  return items.map((item) => ({
    scope: item.scope,
    label: optionalText(item.label),
    value: fundingValuePatch({
      valueKind: item.valueKind,
      currency: item.currency,
      exact: item.exact,
      minimum: item.minimum,
      maximum: item.maximum
    }),
    evidence: optionalText(item.evidence)
  }));
}

function timelinePatchItems(items: CorrectionTimelineEvent[]): Record<string, string | null>[] {
  return items.map((item) => {
    const label = optionalText(item.label);
    if (!label) throw new Error('Укажи название каждого события графика.');
    if (!item.startOn && !item.endOn) throw new Error('Укажи хотя бы одну дату для каждого события графика.');
    if (item.startOn && item.endOn && item.startOn > item.endOn) {
      throw new Error('Дата начала события графика не может быть позже даты окончания.');
    }
    return {
      kind: item.kind,
      label,
      start_on: item.startOn || null,
      end_on: item.endOn || null,
      evidence: optionalText(item.evidence)
    };
  });
}

function resourcePatchItems(items: CorrectionResource[]): Record<string, string | null>[] {
  const urls = new Set<string>();
  return items.map((item) => {
    const label = optionalText(item.label);
    const url = optionalText(item.url);
    if (!label) throw new Error('Укажи название каждого материала карточки.');
    if (!url || !/^https?:\/\//i.test(url)) {
      throw new Error('Укажи корректную абсолютную ссылку для каждого материала.');
    }
    if (urls.has(url)) throw new Error('Одна и та же ссылка указана в материалах больше одного раза.');
    urls.add(url);
    if (item.sectionCategory === 'official_channels' && !isSocialResourceUrl(url)) {
      throw new Error('Для официального канала укажи ссылку Telegram или ВКонтакте.');
    }
    return {
      kind: item.kind,
      label,
      url,
      section_title: optionalText(item.sectionTitle),
      section_category: optionalText(item.sectionCategory),
      content_format: optionalText(item.contentFormat)
    };
  });
}

function resourcePatchFingerprint(items: CorrectionResource[]): Record<string, string | null>[] {
  return items.map((item) => ({
    kind: item.kind,
    label: optionalText(item.label),
    url: optionalText(item.url),
    section_title: optionalText(item.sectionTitle),
    section_category: optionalText(item.sectionCategory),
    content_format: optionalText(item.contentFormat)
  }));
}

function contentBlockPatchItems(items: CorrectionContentBlock[]): Record<string, string>[] {
  return items.map((item) => {
    const heading = optionalText(item.heading);
    const category = optionalText(item.category);
    const text = optionalText(item.text);
    if (!heading || !category || !text) {
      throw new Error('Укажи заголовок, тип и текст для каждого дополнительного раздела.');
    }
    return { heading, category, text };
  });
}

function moveCorrectionItem<T extends { id: string }>(items: T[], id: string, offset: number): T[] {
  const index = items.findIndex((item) => item.id === id);
  const destination = index + offset;
  if (index < 0 || destination < 0 || destination >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(index, 1);
  next.splice(destination, 0, item);
  return next;
}

function reviewCorrectionPatch(
  detail: ReviewCaseDetail,
  form: CorrectionForm
): Record<string, unknown> {
  const baseline = correctionForm(detail);
  const patch: Record<string, unknown> = {};

  if (!form.title.trim()) throw new Error('Укажи название программы.');
  if (form.title.trim() !== baseline.title.trim()) patch.title = form.title.trim();
  if (optionalText(form.summary) !== optionalText(baseline.summary)) {
    patch.summary = optionalText(form.summary);
  }
  if (form.sourcePublishedOn !== baseline.sourcePublishedOn) {
    patch.source_published_on = form.sourcePublishedOn || null;
  }
  if (form.sourceStatus !== baseline.sourceStatus) patch.source_status = form.sourceStatus;
  if (form.deadlineOn !== baseline.deadlineOn) patch.deadline_on = form.deadlineOn || null;

  const fundingFields: (keyof CorrectionForm)[] = [
    'fundingKind',
    'fundingCurrency',
    'fundingExact',
    'fundingMinimum',
    'fundingMaximum'
  ];
  if (fundingFields.some((key) => form[key] !== baseline[key])) {
    patch.funding = reviewFundingPatch(form);
  }
  if (!sameJson(fundingAmountPatchItems(form.fundingAmounts), fundingAmountPatchItems(baseline.fundingAmounts))) {
    patch.funding_amounts = fundingAmountPatchItems(form.fundingAmounts);
  }
  if (!sameJson(timelinePatchItems(form.timeline), timelinePatchItems(baseline.timeline))) {
    patch.timeline = timelinePatchItems(form.timeline);
  }
  if (!sameJson(resourcePatchFingerprint(form.resources), resourcePatchFingerprint(baseline.resources))) {
    patch.resources = resourcePatchItems(form.resources);
  }
  if (!sameJson(contentBlockPatchItems(form.contentBlocks), contentBlockPatchItems(baseline.contentBlocks))) {
    patch.content_blocks = contentBlockPatchItems(form.contentBlocks);
  }

  const application: Record<string, string | null> = {};
  if (optionalText(form.applicationUrl) !== optionalText(baseline.applicationUrl)) {
    application.url = optionalText(form.applicationUrl);
  }
  if (form.applicationStartOn !== baseline.applicationStartOn) {
    application.start_on = form.applicationStartOn || null;
  }
  if (form.applicationEndOn !== baseline.applicationEndOn) {
    application.end_on = form.applicationEndOn || null;
  }
  if (Object.keys(application).length > 0) patch.application = application;

  const eligibility: Record<string, string | null> = {};
  if (optionalText(form.eligibilitySummary) !== optionalText(baseline.eligibilitySummary)) {
    eligibility.summary = optionalText(form.eligibilitySummary);
  }
  if (optionalText(form.eligibilityGeographyNote) !== optionalText(baseline.eligibilityGeographyNote)) {
    eligibility.geography_note = optionalText(form.eligibilityGeographyNote);
  }
  if (form.accessMode !== baseline.accessMode) eligibility.access_mode = form.accessMode;
  if (Object.keys(eligibility).length > 0) patch.eligibility = eligibility;

  if (
    !sameTaxonomyNames(form.themes, baseline.themes)
    || !sameTaxonomyNames(form.geographies, baseline.geographies)
  ) {
    patch.taxonomy = {
      themes: taxonomyPatch(form.themes, detail.public_preview.themes),
      geographies: taxonomyPatch(form.geographies, detail.public_preview.geographies)
    };
  }
  return patch;
}

function ReviewCorrectionEditor({
  detail,
  busy,
  onSave
}: {
  detail: ReviewCaseDetail;
  busy: boolean;
  onSave: (payload: { reason: string; patch: Record<string, unknown>; resolve_issue_ids: string[] }) => Promise<void>;
}) {
  const [form, setForm] = useState<CorrectionForm>(() => correctionForm(detail));
  const [reason, setReason] = useState('');
  const [selectedIssueIds, setSelectedIssueIds] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    setForm(correctionForm(detail));
    setReason('');
    setSelectedIssueIds(new Set());
    setFormError(null);
  }, [detail.review_case_id, detail.revisions.length]);

  function updateField<Key extends keyof CorrectionForm>(key: Key, value: CorrectionForm[Key]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateFundingAmount<Key extends keyof CorrectionFundingAmount>(
    id: string,
    key: Key,
    value: CorrectionFundingAmount[Key]
  ) {
    setForm((current) => ({
      ...current,
      fundingAmounts: current.fundingAmounts.map((item) => item.id === id ? { ...item, [key]: value } : item)
    }));
  }

  function updateTimelineEvent<Key extends keyof CorrectionTimelineEvent>(
    id: string,
    key: Key,
    value: CorrectionTimelineEvent[Key]
  ) {
    setForm((current) => ({
      ...current,
      timeline: current.timeline.map((item) => item.id === id ? { ...item, [key]: value } : item)
    }));
  }

  function updateResource<Key extends keyof CorrectionResource>(
    id: string,
    key: Key,
    value: CorrectionResource[Key]
  ) {
    setForm((current) => ({
      ...current,
      resources: current.resources.map((item) => item.id === id ? { ...item, [key]: value } : item)
    }));
  }

  function updateContentBlock<Key extends keyof CorrectionContentBlock>(
    id: string,
    key: Key,
    value: CorrectionContentBlock[Key]
  ) {
    setForm((current) => ({
      ...current,
      contentBlocks: current.contentBlocks.map((item) => item.id === id ? { ...item, [key]: value } : item)
    }));
  }

  function addFundingAmount() {
    setForm((current) => ({
      ...current,
      fundingAmounts: [...current.fundingAmounts, {
        id: correctionItemId('funding'),
        scope: 'other',
        label: '',
        valueKind: 'not_stated',
        currency: '',
        exact: '',
        minimum: '',
        maximum: '',
        evidence: ''
      }]
    }));
  }

  function addTimelineEvent() {
    setForm((current) => ({
      ...current,
      timeline: [...current.timeline, {
        id: correctionItemId('timeline'),
        kind: 'other',
        label: '',
        startOn: '',
        endOn: '',
        evidence: ''
      }]
    }));
  }

  function addResource() {
    setForm((current) => ({
      ...current,
      resources: [...current.resources, {
        id: correctionItemId('resource'),
        kind: 'document',
        label: '',
        url: '',
        sectionTitle: 'Документы конкурса',
        sectionCategory: 'documents',
        contentFormat: ''
      }]
    }));
  }

  function addContentBlock() {
    setForm((current) => ({
      ...current,
      contentBlocks: [...current.contentBlocks, {
        id: correctionItemId('content'),
        heading: '',
        category: 'criteria',
        text: ''
      }]
    }));
  }

  function toggleIssue(issueId: string) {
    setSelectedIssueIds((current) => {
      const next = new Set(current);
      if (next.has(issueId)) next.delete(issueId); else next.add(issueId);
      return next;
    });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reason.trim() || detail.status === 'resolved') return;
    setFormError(null);
    try {
      const patch = reviewCorrectionPatch(detail, form);
      await onSave({ reason: reason.trim(), patch, resolve_issue_ids: [...selectedIssueIds] });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : errorMessage(error));
    }
  }

  const unresolvedErrors = detail.quality_issues.filter((issue) => issue.severity === 'error' && issue.resolution === null);
  return (
    <form className="mt-5 space-y-5" onSubmit={(event) => void submit(event)}>
      <div className="rounded-lg border border-ink/10 bg-paper/55 p-4">
        <h3 className="font-semibold text-ink">Правки оператора</h3>
        <p className="mt-1 text-sm leading-6 text-graphite">Сохраняется новая версия данных, а не изменение исходного результата парсинга. Ссылку первоисточника, raw capture и контакты здесь менять нельзя.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="field-label sm:col-span-2">Название<input value={form.title} onChange={(event) => updateField('title', event.target.value)} /></label>
        <label className="field-label sm:col-span-2">Краткое описание<textarea className="min-h-28 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={form.summary} onChange={(event) => updateField('summary', event.target.value)} /></label>
        <label className="field-label">Дата публикации у источника<input type="date" value={form.sourcePublishedOn} onChange={(event) => updateField('sourcePublishedOn', event.target.value)} /></label>
        <label className="field-label">Статус у источника<select value={form.sourceStatus} onChange={(event) => updateField('sourceStatus', event.target.value)}><option value="unknown">Не указан</option><option value="upcoming">Скоро начнётся</option><option value="open">Открыт</option><option value="closed">Приём завершён</option><option value="completed">Завершён</option></select></label>
        <label className="field-label">Дедлайн<input type="date" value={form.deadlineOn} onChange={(event) => updateField('deadlineOn', event.target.value)} /></label>
        <label className="field-label">Ссылка для подачи<input type="url" value={form.applicationUrl} onChange={(event) => updateField('applicationUrl', event.target.value)} placeholder="https://…" /></label>
        <label className="field-label">Начало приёма<input type="date" value={form.applicationStartOn} onChange={(event) => updateField('applicationStartOn', event.target.value)} /></label>
        <label className="field-label">Окончание приёма<input type="date" value={form.applicationEndOn} onChange={(event) => updateField('applicationEndOn', event.target.value)} /></label>
        <label className="field-label">Условия подачи<select value={form.accessMode} onChange={(event) => updateField('accessMode', event.target.value)}><option value="unknown">Не указаны</option><option value="open">Открытый конкурс</option><option value="invitation_only">Только по приглашению</option></select></label>
        <label className="field-label">Территория участия<textarea className="min-h-24 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={form.eligibilityGeographyNote} onChange={(event) => updateField('eligibilityGeographyNote', event.target.value)} /></label>
        <label className="field-label sm:col-span-2">Условия участия<textarea className="min-h-28 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={form.eligibilitySummary} onChange={(event) => updateField('eligibilitySummary', event.target.value)} /></label>
        <label className="field-label">Тематики — по одной в строке<textarea className="min-h-28 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={form.themes} onChange={(event) => updateField('themes', event.target.value)} /></label>
        <label className="field-label">Регионы — по одному в строке<textarea className="min-h-28 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={form.geographies} onChange={(event) => updateField('geographies', event.target.value)} /></label>
      </div>
      <fieldset className="rounded-lg border border-ink/10 bg-white/70 p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Финансирование</legend>
        <div className="mt-2 grid gap-4 sm:grid-cols-2">
          <label className="field-label">Тип суммы<select value={form.fundingKind} onChange={(event) => updateField('fundingKind', event.target.value)}><option value="not_stated">Не указана</option><option value="unknown">Неизвестна</option><option value="exact">Точная сумма</option><option value="minimum">Минимум</option><option value="maximum">Максимум</option><option value="range">Диапазон</option></select></label>
          <label className="field-label">Валюта<input value={form.fundingCurrency} onChange={(event) => updateField('fundingCurrency', event.target.value)} placeholder="RUB" disabled={form.fundingKind === 'unknown' || form.fundingKind === 'not_stated'} /></label>
          {form.fundingKind === 'exact' ? <label className="field-label">Точная сумма<input inputMode="decimal" value={form.fundingExact} onChange={(event) => updateField('fundingExact', event.target.value)} /></label> : null}
          {form.fundingKind === 'minimum' || form.fundingKind === 'range' ? <label className="field-label">Минимальная сумма<input inputMode="decimal" value={form.fundingMinimum} onChange={(event) => updateField('fundingMinimum', event.target.value)} /></label> : null}
          {form.fundingKind === 'maximum' || form.fundingKind === 'range' ? <label className="field-label">Максимальная сумма<input inputMode="decimal" value={form.fundingMaximum} onChange={(event) => updateField('fundingMaximum', event.target.value)} /></label> : null}
        </div>
      </fieldset>
      <fieldset className="rounded-lg border border-ink/10 bg-white/70 p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Суммы финансирования</legend>
        <p className="mt-1 text-sm leading-6 text-graphite">Эти строки показываются в подробностях карточки: например, общий фонд конкурса и сумма на одного получателя.</p>
        <div className="mt-4 space-y-4">
          {form.fundingAmounts.map((amount, index) => (
            <div key={amount.id} className="rounded-lg border border-ink/10 bg-paper/55 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold text-ink">Сумма {index + 1}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="button-secondary" disabled={index === 0} onClick={() => setForm((current) => ({ ...current, fundingAmounts: moveCorrectionItem(current.fundingAmounts, amount.id, -1) }))}>Выше</button>
                  <button type="button" className="button-secondary" disabled={index === form.fundingAmounts.length - 1} onClick={() => setForm((current) => ({ ...current, fundingAmounts: moveCorrectionItem(current.fundingAmounts, amount.id, 1) }))}>Ниже</button>
                  <button type="button" className="button-secondary" onClick={() => setForm((current) => ({ ...current, fundingAmounts: current.fundingAmounts.filter((item) => item.id !== amount.id) }))}>Удалить</button>
                </div>
              </div>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <label className="field-label">Тип суммы<select value={amount.scope} onChange={(event) => updateFundingAmount(amount.id, 'scope', event.target.value)}><option value="announced_total">Фонд конкурса</option><option value="per_recipient">На одного получателя</option><option value="per_program">На одну программу</option><option value="awarded_total">Итог по результатам</option><option value="other">Другая сумма</option></select></label>
                <label className="field-label">Подпись<input value={amount.label} onChange={(event) => updateFundingAmount(amount.id, 'label', event.target.value)} placeholder="Например: Общий фонд конкурса" /></label>
                <label className="field-label">Способ указания<select value={amount.valueKind} onChange={(event) => updateFundingAmount(amount.id, 'valueKind', event.target.value)}><option value="not_stated">Не указана</option><option value="unknown">Неизвестна</option><option value="exact">Точная сумма</option><option value="minimum">Минимум</option><option value="maximum">Максимум</option><option value="range">Диапазон</option></select></label>
                <label className="field-label">Валюта<input value={amount.currency} onChange={(event) => updateFundingAmount(amount.id, 'currency', event.target.value)} placeholder="RUB" disabled={amount.valueKind === 'unknown' || amount.valueKind === 'not_stated'} /></label>
                {amount.valueKind === 'exact' ? <label className="field-label">Точная сумма<input inputMode="decimal" value={amount.exact} onChange={(event) => updateFundingAmount(amount.id, 'exact', event.target.value)} /></label> : null}
                {amount.valueKind === 'minimum' || amount.valueKind === 'range' ? <label className="field-label">Минимальная сумма<input inputMode="decimal" value={amount.minimum} onChange={(event) => updateFundingAmount(amount.id, 'minimum', event.target.value)} /></label> : null}
                {amount.valueKind === 'maximum' || amount.valueKind === 'range' ? <label className="field-label">Максимальная сумма<input inputMode="decimal" value={amount.maximum} onChange={(event) => updateFundingAmount(amount.id, 'maximum', event.target.value)} /></label> : null}
                <label className="field-label sm:col-span-2">Основание для правки<textarea className="min-h-20 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={amount.evidence} onChange={(event) => updateFundingAmount(amount.id, 'evidence', event.target.value)} placeholder="Фрагмент официальной страницы или документа" /></label>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="button-secondary mt-4" onClick={addFundingAmount}>Добавить сумму</button>
      </fieldset>
      <fieldset className="rounded-lg border border-ink/10 bg-white/70 p-4">
        <legend className="px-1 text-sm font-semibold text-ink">График</legend>
        <p className="mt-1 text-sm leading-6 text-graphite">Здесь можно поправить все этапы конкурса и порядок, в котором они увидит посетитель.</p>
        <div className="mt-4 space-y-4">
          {form.timeline.map((event, index) => (
            <div key={event.id} className="rounded-lg border border-ink/10 bg-paper/55 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold text-ink">Событие {index + 1}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="button-secondary" disabled={index === 0} onClick={() => setForm((current) => ({ ...current, timeline: moveCorrectionItem(current.timeline, event.id, -1) }))}>Выше</button>
                  <button type="button" className="button-secondary" disabled={index === form.timeline.length - 1} onClick={() => setForm((current) => ({ ...current, timeline: moveCorrectionItem(current.timeline, event.id, 1) }))}>Ниже</button>
                  <button type="button" className="button-secondary" onClick={() => setForm((current) => ({ ...current, timeline: current.timeline.filter((item) => item.id !== event.id) }))}>Удалить</button>
                </div>
              </div>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <label className="field-label sm:col-span-2">Название события<input value={event.label} onChange={(input) => updateTimelineEvent(event.id, 'label', input.target.value)} /></label>
                <label className="field-label">Тип<select value={event.kind} onChange={(input) => updateTimelineEvent(event.id, 'kind', input.target.value)}><option value="application">Приём заявок</option><option value="application_open">Начало приёма</option><option value="application_close">Окончание приёма</option><option value="evaluation">Экспертиза</option><option value="results">Результаты</option><option value="contracting">Заключение договоров</option><option value="implementation">Реализация</option><option value="other">Другое</option></select></label>
                <label className="field-label">Начало<input type="date" value={event.startOn} onChange={(input) => updateTimelineEvent(event.id, 'startOn', input.target.value)} /></label>
                <label className="field-label">Окончание<input type="date" value={event.endOn} onChange={(input) => updateTimelineEvent(event.id, 'endOn', input.target.value)} /></label>
                <label className="field-label sm:col-span-2">Основание для правки<textarea className="min-h-20 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={event.evidence} onChange={(input) => updateTimelineEvent(event.id, 'evidence', input.target.value)} placeholder="Фрагмент официального графика" /></label>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="button-secondary mt-4" onClick={addTimelineEvent}>Добавить событие</button>
      </fieldset>
      <fieldset className="rounded-lg border border-ink/10 bg-white/70 p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Документы, победители и официальные каналы</legend>
        <p className="mt-1 text-sm leading-6 text-graphite">Это ровно те материалы, которые попадут в карточку. Ссылки из обычного текста не добавляй сюда: ссылку для подачи нужно указать выше, а настоящий документ — только если он явно опубликован источником.</p>
        <div className="mt-4 space-y-4">
          {form.resources.map((resource, index) => (
            <div key={resource.id} className="rounded-lg border border-ink/10 bg-paper/55 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold text-ink">Материал {index + 1}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="button-secondary" disabled={index === 0} onClick={() => setForm((current) => ({ ...current, resources: moveCorrectionItem(current.resources, resource.id, -1) }))}>Выше</button>
                  <button type="button" className="button-secondary" disabled={index === form.resources.length - 1} onClick={() => setForm((current) => ({ ...current, resources: moveCorrectionItem(current.resources, resource.id, 1) }))}>Ниже</button>
                  <button type="button" className="button-secondary" onClick={() => setForm((current) => ({ ...current, resources: current.resources.filter((item) => item.id !== resource.id) }))}>Удалить</button>
                </div>
              </div>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <label className="field-label sm:col-span-2">Название материала<input value={resource.label} onChange={(event) => updateResource(resource.id, 'label', event.target.value)} placeholder="Например: Положение о конкурсе" /></label>
                <label className="field-label sm:col-span-2">Ссылка<input type="url" value={resource.url} onChange={(event) => updateResource(resource.id, 'url', event.target.value)} placeholder="https://…" /></label>
                <label className="field-label">Тип<select value={resource.kind} onChange={(event) => updateResource(resource.id, 'kind', event.target.value as CorrectionResourceKind)}><option value="document">Документ или ссылка</option><option value="result">Победители</option><option value="reference">Официальный канал</option></select></label>
                <label className="field-label">Размещение<select value={resource.sectionCategory} onChange={(event) => updateResource(resource.id, 'sectionCategory', event.target.value)}><option value="documents">Документы и ссылки</option><option value="results">Победители</option><option value="official_channels">Официальные каналы</option></select></label>
                <label className="field-label">Название раздела источника<input value={resource.sectionTitle} onChange={(event) => updateResource(resource.id, 'sectionTitle', event.target.value)} placeholder="Документы конкурса" /></label>
                <label className="field-label">Формат (необязательно)<input value={resource.contentFormat} onChange={(event) => updateResource(resource.id, 'contentFormat', event.target.value)} placeholder="PDF" /></label>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="button-secondary mt-4" onClick={addResource}>Добавить материал</button>
      </fieldset>
      <fieldset className="rounded-lg border border-ink/10 bg-white/70 p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Дополнительная информация</legend>
        <p className="mt-1 text-sm leading-6 text-graphite">Эти самостоятельные блоки показываются ниже основных параметров карточки.</p>
        <div className="mt-4 space-y-4">
          {form.contentBlocks.map((block, index) => (
            <div key={block.id} className="rounded-lg border border-ink/10 bg-paper/55 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold text-ink">Раздел {index + 1}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="button-secondary" disabled={index === 0} onClick={() => setForm((current) => ({ ...current, contentBlocks: moveCorrectionItem(current.contentBlocks, block.id, -1) }))}>Выше</button>
                  <button type="button" className="button-secondary" disabled={index === form.contentBlocks.length - 1} onClick={() => setForm((current) => ({ ...current, contentBlocks: moveCorrectionItem(current.contentBlocks, block.id, 1) }))}>Ниже</button>
                  <button type="button" className="button-secondary" onClick={() => setForm((current) => ({ ...current, contentBlocks: current.contentBlocks.filter((item) => item.id !== block.id) }))}>Удалить</button>
                </div>
              </div>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <label className="field-label">Заголовок<input value={block.heading} onChange={(event) => updateContentBlock(block.id, 'heading', event.target.value)} /></label>
                <label className="field-label">Тип<select value={block.category} onChange={(event) => updateContentBlock(block.id, 'category', event.target.value)}><option value="criteria">Критерии</option><option value="opportunities">Возможности</option><option value="application">Подача заявки</option><option value="results">Результаты</option></select></label>
                <label className="field-label sm:col-span-2">Текст<textarea className="min-h-28 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={block.text} onChange={(event) => updateContentBlock(block.id, 'text', event.target.value)} /></label>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="button-secondary mt-4" onClick={addContentBlock}>Добавить раздел</button>
      </fieldset>
      {unresolvedErrors.length > 0 ? <fieldset className="rounded-lg border border-clay/25 bg-clay/5 p-4"><legend className="px-1 text-sm font-semibold text-ink">Подтвердить исправление ошибок качества</legend><p className="mt-1 text-sm leading-6 text-graphite">Отметь только ошибки, которые ты исправил или проверил вручную. Исходное замечание останется в истории.</p><div className="mt-3 space-y-2">{unresolvedErrors.map((issue) => <label key={issue.id} className="flex items-start gap-2 text-sm text-ink"><input className="mt-1" type="checkbox" checked={selectedIssueIds.has(issue.id)} onChange={() => toggleIssue(issue.id)} /><span><span className="font-semibold">{sourceIssueLabel(issue)}</span><br /><span className="text-graphite">{issue.message}</span></span></label>)}</div></fieldset> : null}
      <label className="field-label">Причина правки<textarea className="min-h-24 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Что проверено у источника и почему данные изменены?" /></label>
      <div className="flex flex-wrap items-center gap-3"><button type="submit" disabled={busy || detail.status === 'resolved' || !reason.trim()} className="button-primary">{busy ? 'Сохраняем…' : 'Сохранить версию правок'}</button>{detail.status === 'needs_clarification' ? <p className="text-sm text-cobalt">После сохранения запись вернётся в очередь на решение.</p> : null}</div>
      {formError ? <p role="alert" className="text-sm text-clay">{formError}</p> : null}
    </form>
  );
}

function ReviewDetail({
  detail,
  busy,
  onAction,
  onSaveRevision
}: {
  detail: ReviewCaseDetail | null;
  busy: boolean;
  onAction: (action: ReviewActionKind, reason: string, matchId?: string) => Promise<void>;
  onSaveRevision: (reviewCaseId: string, payload: { reason: string; patch: Record<string, unknown>; resolve_issue_ids: string[] }) => Promise<void>;
}) {
  const [activeTab, setActiveTab] = useState<ReviewDetailTab>('source');
  useEffect(() => { setActiveTab('source'); }, [detail?.review_case_id]);
  if (!detail) {
    return <EmptyState title="Выбери кандидата" description="Здесь появятся исходные данные, предпросмотр карточки, замечания и история решений." />;
  }

  const snapshot = asRecord(detail.opened_snapshot);
  const matches = Array.isArray(snapshot.matches) ? snapshot.matches.map(asRecord) : [];
  const preview = mapReviewPublicPreview(detail.review_case_id, detail.public_preview);

  return (
    <Panel title={detail.public_preview.title ?? detail.title ?? 'Кандидат без названия'} description={`Кейс открыт ${formatDateTime(detail.opened_at)}`}>
      <div className="flex flex-wrap gap-2">
        <QueueStatus status={detail.status} />
        {detail.reason_codes.map((reason) => <Tag key={reason}>{reviewReasonLabel(reason)}</Tag>)}
      </div>
      <div className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label="Представление кандидата">
        {([['source', 'Данные источника'], ['preview', 'Предпросмотр карточки'], ['corrections', 'Правки оператора']] as [ReviewDetailTab, string][]).map(([tab, label]) => <button key={tab} type="button" role="tab" aria-selected={activeTab === tab} className={activeTab === tab ? 'button-primary' : 'button-secondary'} onClick={() => setActiveTab(tab)}>{label}</button>)}
      </div>
      {activeTab === 'source' ? <SourceDataView detail={detail} /> : null}
      {activeTab === 'preview' ? <div className="mt-5"><p className="mb-3 text-sm leading-6 text-graphite">Публичные поля рассчитаны по текущей версии правок и тем же правилам, что применяются при публикации. Дата добавления появится только после фактического решения.</p><ApiProgramDrawer program={preview} loading={false} error={null} isFavorite={false} onToggleFavorite={() => undefined} onRetry={() => undefined} onClose={() => undefined} embedded preview /></div> : null}
      {activeTab === 'corrections' ? <ReviewCorrectionEditor detail={detail} busy={busy} onSave={(payload) => onSaveRevision(detail.review_case_id, payload)} /> : null}

      <QualityIssues issues={detail.quality_issues} />

      {matches.length > 0 ? (
        <section className="mt-6">
          <h3 className="font-semibold text-ink">Возможные совпадения</h3>
          <ul className="mt-3 space-y-2">
            {matches.map((match) => {
              const evidence = asRecord(match.evidence);
              const evidenceLevel = asString(evidence.match_level) ?? 'сопоставление';
              const programId = asString(match.target_program_id);
              const stagedId = asString(match.target_staged_record_id);
              return (
                <li key={asString(match.id) ?? JSON.stringify(match)} className="rounded-lg border border-ink/10 bg-paper/60 p-3 text-sm">
                  <p className="font-medium text-ink">{evidenceLevel}</p>
                  <p className="mt-1 text-graphite">{programId ? `Опубликованная программа: ${programId}` : `Кандидат: ${stagedId ?? 'не указан'}`}</p>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <ReviewActions detail={detail} busy={busy} onAction={onAction} onOpenCorrections={() => setActiveTab('corrections')} />

      <section className="mt-6 border-t border-ink/10 pt-5">
        <h3 className="font-semibold text-ink">История версий правок</h3>
        {detail.revisions.length === 0 ? <p className="mt-2 text-sm text-graphite">Ручных версий пока нет.</p> : <ol className="mt-3 space-y-3">{detail.revisions.map((revision) => <li key={revision.id} className="rounded-lg border border-ink/10 bg-paper/60 p-3 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-ink">Версия {revision.revision_number}</span><span className="text-graphite">{formatDateTime(revision.created_at)}</span></div><p className="mt-2 text-graphite">{revision.reason}</p><p className="mt-2 text-xs text-graphite/70">Изменено: {revision.changed_fields.length > 0 ? revision.changed_fields.join(', ') : 'только подтверждены ошибки качества'} · Оператор: {revision.actor}</p>{revision.resolved_issue_ids.length > 0 ? <p className="mt-1 text-xs text-moss">Подтверждённо исправлено замечаний: {revision.resolved_issue_ids.length}</p> : null}</li>)}</ol>}
      </section>

      <section className="mt-6 border-t border-ink/10 pt-5">
        <h3 className="font-semibold text-ink">История решений</h3>
        {detail.actions.length === 0 ? <p className="mt-2 text-sm text-graphite">Решений ещё нет.</p> : (
          <ol className="mt-3 space-y-3">
            {detail.actions.map((action) => (
              <li key={action.id} className="rounded-lg border border-ink/10 bg-paper/60 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-ink">{reviewReasonLabel(action.action)}</span><span className="text-graphite">{formatDateTime(action.created_at)}</span></div>
                <p className="mt-2 text-graphite">{action.reason}</p>
                <p className="mt-2 text-xs text-graphite/70">Оператор: {action.actor}</p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </Panel>
  );
}

function DetailField({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-lg border border-ink/10 bg-paper/55 p-3">
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-graphite/70">{label}</dt>
      <dd className="mt-1 break-words text-sm text-ink">{value ?? 'Не указано'}</dd>
    </div>
  );
}

function ReviewWorkspace({
  reviewCases,
  issues,
  selectedCaseId,
  onSelect,
  detail,
  detailLoading,
  actionBusy,
  onAction,
  onSaveRevision
}: {
  reviewCases: ReviewQueueItem[];
  issues: QualityIssue[];
  selectedCaseId: string | null;
  onSelect: (id: string) => void;
  detail: ReviewCaseDetail | null;
  detailLoading: boolean;
  actionBusy: boolean;
  onAction: (reviewCaseId: string, action: ReviewActionKind, reason: string, matchId?: string) => Promise<void>;
  onSaveRevision: (reviewCaseId: string, payload: { reason: string; patch: Record<string, unknown>; resolve_issue_ids: string[] }) => Promise<void>;
}) {
  const [filter, setFilter] = useState<ReviewFilter>('all');
  const [selectedForBatch, setSelectedForBatch] = useState<Set<string>>(new Set());
  const [batchReason, setBatchReason] = useState('');
  const [batchConfirmed, setBatchConfirmed] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchFeedback, setBatchFeedback] = useState<string | null>(null);

  const issuesByCase = useMemo(() => {
    const grouped = new Map<string, QualityIssue[]>();
    for (const issue of issues) {
      if (!issue.review_case_id) continue;
      const current = grouped.get(issue.review_case_id) ?? [];
      current.push(issue);
      grouped.set(issue.review_case_id, current);
    }
    return grouped;
  }, [issues]);

  const cleanCases = useMemo(
    () => reviewCases.filter((item) => isCleanReviewCase(item, issuesByCase.get(item.review_case_id) ?? [])),
    [issuesByCase, reviewCases]
  );

  const visibleCases = useMemo(() => reviewCases.filter((item) => {
    const reasons = item.reason_codes;
    const itemIssues = issuesByCase.get(item.review_case_id) ?? [];
    if (filter === 'ready') return isCleanReviewCase(item, itemIssues);
    if (filter === 'quality') return itemIssues.length > 0 || reasons.some((reason) => reason.startsWith('quality_'));
    if (filter === 'duplicates') return reasons.some((reason) => reason.includes('duplicate') || reason.includes('identity'));
    if (filter === 'clarification') return item.status === 'needs_clarification';
    return true;
  }), [filter, issuesByCase, reviewCases]);

  useEffect(() => {
    const allowed = new Set(cleanCases.map((item) => item.review_case_id));
    setSelectedForBatch((current) => new Set([...current].filter((id) => allowed.has(id))));
  }, [cleanCases]);

  useEffect(() => {
    if (selectedForBatch.size === 0) setBatchConfirmed(false);
  }, [selectedForBatch]);

  function toggleBatchSelection(id: string) {
    setSelectedForBatch((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function acceptSelected() {
    const selected = cleanCases.filter((item) => selectedForBatch.has(item.review_case_id));
    if (!batchReason.trim() || selected.length === 0) return;
    setBatchBusy(true);
    setBatchFeedback(null);
    let accepted = 0;
    let skipped = 0;
    for (const item of selected) {
      try {
        await onActionForBatch(item.review_case_id, batchReason.trim());
        accepted += 1;
      } catch {
        skipped += 1;
      }
    }
    setSelectedForBatch(new Set());
    setBatchReason('');
    setBatchConfirmed(false);
    setBatchFeedback(skipped === 0 ? `Принято и опубликовано: ${accepted}.` : `Принято: ${accepted}; не выполнено: ${skipped}. Обнови очередь перед повторной попыткой.`);
    setBatchBusy(false);
  }

  async function onActionForBatch(reviewCaseId: string, reason: string) {
    await onAction(reviewCaseId, 'accept', reason);
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.45fr)]">
      <Panel title="Очередь кандидатов" description="Выбирай запись, сверяй поля с первоисточником и фиксируй решение.">
        <div role="tablist" aria-label="Фильтр очереди" className="flex flex-wrap gap-2">
          {([
            ['all', `Все (${reviewCases.length})`],
            ['ready', `Без замечаний (${cleanCases.length})`],
            ['quality', 'Качество'],
            ['duplicates', 'Совпадения'],
            ['clarification', 'Уточнение']
          ] as [ReviewFilter, string][]).map(([value, label]) => (
            <button key={value} type="button" role="tab" aria-selected={filter === value} className={filter === value ? 'button-primary' : 'button-secondary'} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>

        {cleanCases.length > 0 ? (
          <div className="mt-4 rounded-lg border border-moss/25 bg-moss/10 p-3">
            <p className="text-sm font-semibold text-ink">Безопасное массовое принятие</p>
            <p className="mt-1 text-xs leading-5 text-graphite">Доступно только для открытых записей с единственной причиной «готово к проверке» и без проблем качества. Каждая запись всё равно проходит серверную проверку и получает отдельную запись аудита.</p>
            {selectedForBatch.size > 0 ? (
              <div className="mt-3 space-y-2">
                <label className="field-label text-sm">Общая причина
                  <textarea className="min-h-20 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={batchReason} onChange={(event) => setBatchReason(event.target.value)} placeholder="Например: данные сверены с официальными страницами источников." />
                </label>
                <label className="flex items-start gap-2 text-xs leading-5 text-graphite"><input type="checkbox" checked={batchConfirmed} onChange={(event) => setBatchConfirmed(event.target.checked)} />Я проверил выбранные записи и подтверждаю их публикацию.</label>
                <button type="button" disabled={batchBusy || !batchReason.trim() || !batchConfirmed} className="button-primary" onClick={() => void acceptSelected()}>{batchBusy ? 'Сохраняем решения…' : `Принять выбранные (${selectedForBatch.size})`}</button>
              </div>
            ) : <p className="mt-2 text-xs text-graphite">Отметь подходящие записи в списке ниже.</p>}
            {batchFeedback ? <p role="status" className="mt-3 text-sm text-graphite">{batchFeedback}</p> : null}
          </div>
        ) : null}

        <ul className="mt-4 max-h-[62vh] space-y-2 overflow-y-auto pr-1" aria-label="Кандидаты для проверки">
          {visibleCases.map((item) => {
            const itemIssues = issuesByCase.get(item.review_case_id) ?? [];
            const clean = isCleanReviewCase(item, itemIssues);
            const selected = item.review_case_id === selectedCaseId;
            return (
              <li key={item.review_case_id}>
                <div className={`rounded-lg border p-3 ${selected ? 'border-cobalt bg-cobalt/10' : 'border-ink/10 bg-paper/45'}`}>
                  <div className="flex items-start gap-2">
                    {clean ? <input aria-label={`Выбрать ${item.title ?? 'кандидат'} для массового принятия`} type="checkbox" checked={selectedForBatch.has(item.review_case_id)} onChange={() => toggleBatchSelection(item.review_case_id)} /> : null}
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onSelect(item.review_case_id)}>
                      <p className="break-words text-sm font-semibold text-ink">{item.title ?? 'Кандидат без названия'}</p>
                      <p className="mt-1 text-xs text-graphite">{formatDateTime(item.opened_at)}</p>
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <QueueStatus status={item.status} />
                    {item.reason_codes.map((reason) => <Tag key={reason}>{reviewReasonLabel(reason)}</Tag>)}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        {visibleCases.length === 0 ? <div className="mt-4"><EmptyState title="Подходящих кандидатов нет" description="Смени фильтр или запусти источник отдельно, когда готов к новому сбору." /></div> : null}
      </Panel>

      <div>
        {detailLoading ? <Panel title="Загружаем детали"><p role="status" className="text-sm text-graphite">Получаем безопасную операторскую сводку…</p></Panel> : <ReviewDetail detail={detail} busy={actionBusy} onAction={(action, reason, matchId) => detail ? onAction(detail.review_case_id, action, reason, matchId) : Promise.resolve()} onSaveRevision={onSaveRevision} />}
      </div>
    </div>
  );
}

function QualityWorkspace({ issues, onOpenReviewCase }: { issues: QualityIssue[]; onOpenReviewCase: (id: string) => void }) {
  return (
    <Panel title="Проблемы качества" description="Ошибки блокируют публикацию; предупреждения требуют осознанной проверки перед решением.">
      {issues.length === 0 ? <EmptyState title="Проблем качества нет" description="Для текущих staging-кандидатов нет зарегистрированных предупреждений или ошибок." /> : (
        <ul className="space-y-3">
          {issues.map((issue) => (
            <li key={issue.id} className="rounded-lg border border-ink/10 bg-paper/45 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap gap-2"><QueueStatus status={issue.severity} /><Tag>{issue.code}</Tag></div><span className="text-xs text-graphite">{formatDateTime(issue.created_at)}</span></div>
              <p className="mt-3 text-sm leading-6 text-ink">{issue.message}</p>
              <p className="mt-2 break-all text-xs text-graphite">Ключ записи: {issue.record_key}</p>
              {issue.review_case_id ? <button type="button" className="button-secondary mt-3" onClick={() => onOpenReviewCase(issue.review_case_id!)}>Открыть кейс</button> : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RunsWorkspace({
  executionRuns,
  ingestionRuns,
  sourceDefinitions
}: {
  executionRuns: ExecutionRun[];
  ingestionRuns: IngestionRun[];
  sourceDefinitions: SourceDefinition[];
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Panel title="Запуски адаптеров" description="Сбор запускается только отдельной CLI-командой. Панель показывает результат и не начинает сетевые запросы.">
        {executionRuns.length === 0 ? <EmptyState title="Запусков пока нет" description="После явного запуска источника здесь появится его журнал." /> : <RunList runs={executionRuns} />}
      </Panel>
      <Panel title="Пакеты загрузки" description="Показывает, сколько исходных материалов и кандидатов прошло через контур происхождения.">
        {ingestionRuns.length === 0 ? <EmptyState title="Пакетов пока нет" description="После успешного запуска источника здесь появятся сохранённые загрузки." /> : <IngestionList runs={ingestionRuns} />}
      </Panel>
      <Panel title="Разрешённые источники" description="Реестр определяет, какие источники и URL может использовать адаптер. Секреты сюда не передаются." className="xl:col-span-2">
        {sourceDefinitions.length === 0 ? <EmptyState title="Реестр недоступен" description="Проверь конфигурацию источников перед запуском сбора." /> : (
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {sourceDefinitions.map((source) => (
              <li key={source.source_key} className="rounded-lg border border-ink/10 bg-paper/45 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2"><p className="font-semibold text-ink">{source.name}</p><QueueStatus status={source.status} /></div>
                <p className="mt-2 text-xs text-graphite">{source.source_key} · {source.adapter_name} {source.adapter_version}</p>
                <p className="mt-2 text-xs text-graphite">Расписание: {source.schedule}; ответственный: {source.responsible}</p>
                {isExternalUrl(source.canonical_url) ? <a href={source.canonical_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-cobalt hover:underline">Открыть источник <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></a> : null}
                <p className="mt-2 text-xs text-graphite">Разрешённых URL-маршрутов: {source.allowed_url_prefixes.length + source.allowed_exact_urls.length}</p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function RunList({ runs }: { runs: ExecutionRun[] }) {
  return (
    <ul className="space-y-3">
      {runs.map((run) => (
        <li key={run.id} className="rounded-lg border border-ink/10 bg-paper/45 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-ink">{run.source_key}</p><QueueStatus status={run.status} /></div>
          <p className="mt-2 text-sm text-graphite">Начат: {formatDateTime(run.started_at)} · попыток: {run.attempt_count}</p>
          <p className="mt-1 text-xs text-graphite">Результат: {run.result_kind ?? 'не указан'}{run.error_codes.length > 0 ? ` · коды: ${run.error_codes.join(', ')}` : ''}</p>
        </li>
      ))}
    </ul>
  );
}

function IngestionList({ runs }: { runs: IngestionRun[] }) {
  return (
    <ul className="space-y-3">
      {runs.map((run) => (
        <li key={run.id} className="rounded-lg border border-ink/10 bg-paper/45 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold text-ink">{run.adapter_name} {run.adapter_version}</p><QueueStatus status={run.status} /></div>
          <p className="mt-2 text-sm text-graphite">Получен: {formatDateTime(run.received_at)}</p>
          <p className="mt-1 text-xs text-graphite">Raw: {run.raw_capture_count}; кандидаты: {run.staged_record_count}; замечания: {run.quality_issue_count}; ошибки: {run.quality_error_count}</p>
        </li>
      ))}
    </ul>
  );
}

function DiscoveryWorkspace({
  cases,
  sourceDefinitions,
  busy,
  onAction
}: {
  cases: DiscoveryReviewItem[];
  sourceDefinitions: SourceDefinition[];
  busy: boolean;
  onAction: (reviewCaseId: string, action: DiscoveryActionKind, reason: string, sourceKey?: string) => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [action, setAction] = useState<DiscoveryActionKind | null>(null);
  const [reason, setReason] = useState('');
  const [sourceKey, setSourceKey] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const selected = cases.find((item) => item.review_case_id === selectedId) ?? cases[0] ?? null;

  useEffect(() => {
    if (selected && selected.review_case_id !== selectedId) setSelectedId(selected.review_case_id);
  }, [selected, selectedId]);

  async function confirm() {
    if (!selected || !action || !reason.trim() || (action === 'link_to_registered_source' && !sourceKey)) return;
    setActionError(null);
    try {
      await onAction(selected.review_case_id, action, reason.trim(), action === 'link_to_registered_source' ? sourceKey : undefined);
      setAction(null);
      setReason('');
      setSourceKey('');
    } catch (error) {
      setActionError(errorMessage(error));
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.2fr)]">
      <Panel title="Discovery-кандидаты" description="Telegram и другие discovery-источники не публикуют программу. Они передают только внешние ссылки на проверку.">
        {cases.length === 0 ? <EmptyState title="Кандидатов нет" description="Неоднозначных внешних ссылок пока нет в ручной проверке." /> : (
          <ul className="space-y-2">
            {cases.map((item) => <li key={item.review_case_id}><button type="button" className={`w-full rounded-lg border p-3 text-left ${item.review_case_id === selected?.review_case_id ? 'border-cobalt bg-cobalt/10' : 'border-ink/10 bg-paper/45'}`} onClick={() => setSelectedId(item.review_case_id)}><p className="break-all text-sm font-semibold text-ink">{item.subject_reference}</p><div className="mt-2 flex flex-wrap gap-2"><QueueStatus status={item.status} />{item.reason_codes.map((reasonCode) => <Tag key={reasonCode}>{reviewReasonLabel(reasonCode)}</Tag>)}</div></button></li>)}
          </ul>
        )}
      </Panel>
      <Panel title={selected ? 'Проверка внешней ссылки' : 'Выбери discovery-кандидат'} description={selected ? `Обнаружено ${formatDateTime(selected.opened_at)}` : undefined}>
        {selected ? <>
          {isExternalUrl(selected.subject_reference) ? <a href={selected.subject_reference} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-semibold text-cobalt hover:underline">Открыть внешнюю ссылку <ExternalLink className="h-4 w-4" aria-hidden="true" /></a> : <p className="break-all text-sm text-ink">{selected.subject_reference}</p>}
          <p className="mt-4 text-sm leading-6 text-graphite">Связывай URL только с уже разрешённым адаптером первоисточника. Если источника нет в реестре или ссылка ненадёжна, оставь уточнение или отклони её.</p>
          <div className="mt-5 flex flex-wrap gap-2">
            <button type="button" disabled={busy} className="button-primary" onClick={() => setAction('link_to_registered_source')}>Связать с источником</button>
            <button type="button" disabled={busy} className="button-secondary" onClick={() => setAction('needs_clarification')}>Запросить уточнение</button>
            <button type="button" disabled={busy} className="button-secondary" onClick={() => setAction('reject')}>Отклонить</button>
          </div>
          {action ? <div className="mt-4 space-y-3 rounded-lg border border-ink/10 bg-paper/55 p-4">
            {action === 'link_to_registered_source' ? <label className="field-label">Разрешённый источник<select value={sourceKey} onChange={(event) => setSourceKey(event.target.value)}><option value="">Выбери источник</option>{sourceDefinitions.filter((source) => source.status === 'active').map((source) => <option key={source.source_key} value={source.source_key}>{source.name} — {source.source_key}</option>)}</select></label> : null}
            <label className="field-label">Причина<textarea className="min-h-24 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
            <div className="flex gap-2"><button type="button" disabled={busy || !reason.trim() || (action === 'link_to_registered_source' && !sourceKey)} className="button-primary" onClick={() => void confirm()}>{busy ? 'Сохраняем…' : 'Подтвердить'}</button><button type="button" disabled={busy} className="button-secondary" onClick={() => setAction(null)}>Отмена</button></div>
            {actionError ? <p role="alert" className="text-sm text-clay">{actionError}</p> : null}
          </div> : null}
        </> : <EmptyState title="Кандидатов нет" description="Когда discovery найдёт неоднозначную ссылку, она появится здесь." />}
      </Panel>
    </div>
  );
}

function PublicationWorkspace({
  busy,
  onArchive,
  onRepublish
}: {
  busy: boolean;
  onArchive: (programId: string, reason: string) => Promise<void>;
  onRepublish: (programId: string, reason: string) => Promise<void>;
}) {
  const [programId, setProgramId] = useState('');
  const [reason, setReason] = useState('');
  const [mode, setMode] = useState<'archive' | 'republish'>('archive');
  const [feedback, setFeedback] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!programId.trim() || !reason.trim()) return;
    try {
      if (mode === 'archive') await onArchive(programId.trim(), reason.trim());
      else await onRepublish(programId.trim(), reason.trim());
      setFeedback(mode === 'archive' ? 'Программа архивирована и больше не видна в публичном каталоге.' : 'Программа снова опубликована в публичном каталоге.');
      setReason('');
    } catch (error) {
      setFeedback(errorMessage(error));
    }
  }

  return (
    <Panel title="Управление опубликованной программой" description="Архивирование скрывает карточку из public API, не удаляя доказательства. Повторно опубликовать можно только архивированную программу.">
      <form className="max-w-2xl space-y-4" onSubmit={submit}>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Действие с программой">
          <button type="button" role="radio" aria-checked={mode === 'archive'} className={mode === 'archive' ? 'button-primary' : 'button-secondary'} onClick={() => setMode('archive')}>Архивировать</button>
          <button type="button" role="radio" aria-checked={mode === 'republish'} className={mode === 'republish' ? 'button-primary' : 'button-secondary'} onClick={() => setMode('republish')}>Повторно опубликовать</button>
        </div>
        <label className="field-label">ID программы<input value={programId} onChange={(event) => setProgramId(event.target.value)} placeholder="UUID опубликованной программы" /></label>
        <label className="field-label">Причина<textarea className="min-h-24 w-full resize-y rounded-xl border border-ink/20 bg-white p-3 text-ink" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Почему статус программы нужно изменить?" /></label>
        <button type="submit" disabled={busy || !programId.trim() || !reason.trim()} className="button-primary">{busy ? 'Сохраняем…' : mode === 'archive' ? 'Подтвердить архивирование' : 'Подтвердить публикацию'}</button>
        {feedback ? <p role="status" className="rounded-lg border border-ink/10 bg-paper/55 p-3 text-sm text-graphite">{feedback}</p> : null}
      </form>
    </Panel>
  );
}

function OperatorWorkspace({ client, onSignOut }: { client: OperatorApiClient; onSignOut: () => void }) {
  const [activeView, setActiveView] = useState<OperatorView>('review');
  const [data, setData] = useState<DashboardData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReviewCaseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [reviewCases, qualityIssues, discoveryCases, sourceDefinitions, executionRuns, ingestionRuns] = await Promise.all([
        client.listReviewCases(),
        client.listQualityIssues(),
        client.listDiscoveryCases(),
        client.listSourceDefinitions(),
        client.listExecutionRuns(),
        client.listIngestionRuns()
      ]);
      setData({ reviewCases, qualityIssues, discoveryCases, sourceDefinitions, executionRuns, ingestionRuns });
      setSelectedCaseId((current) => reviewCases.some((item) => item.review_case_id === current)
        ? current
        : reviewCases[0]?.review_case_id ?? null);
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!selectedCaseId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void client.getReviewCase(selectedCaseId)
      .then((nextDetail) => { if (!cancelled) setDetail(nextDetail); })
      .catch((error) => { if (!cancelled) setNotice(errorMessage(error)); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [client, selectedCaseId]);

  async function applyReviewAction(reviewCaseId: string, action: ReviewActionKind, reason: string, matchId?: string) {
    setActionBusy(true);
    setNotice(null);
    try {
      const result = await client.applyReviewAction(
        reviewCaseId,
        { action, reason, ...(matchId ? { deduplication_match_id: matchId } : {}) },
        createOperatorIdempotencyKey(action)
      );
      setNotice(result.program_id ? 'Решение сохранено: программа опубликована.' : 'Решение сохранено в журнале аудита.');
      await refresh();
    } catch (error) {
      setNotice(errorMessage(error));
      throw error;
    } finally {
      setActionBusy(false);
    }
  }

  async function applyDiscoveryAction(reviewCaseId: string, action: DiscoveryActionKind, reason: string, sourceKey?: string) {
    setActionBusy(true);
    setNotice(null);
    try {
      await client.applyDiscoveryAction(
        reviewCaseId,
        { action, reason, ...(sourceKey ? { source_key: sourceKey } : {}) },
        createOperatorIdempotencyKey(action)
      );
      setNotice('Решение discovery сохранено в журнале аудита.');
      await refresh();
    } catch (error) {
      setNotice(errorMessage(error));
      throw error;
    } finally {
      setActionBusy(false);
    }
  }

  async function saveReviewRevision(
    reviewCaseId: string,
    payload: { reason: string; patch: Record<string, unknown>; resolve_issue_ids: string[] }
  ) {
    setActionBusy(true);
    setNotice(null);
    try {
      const result = await client.saveReviewRevision(
        reviewCaseId,
        payload,
        createOperatorIdempotencyKey('save-revision')
      );
      setNotice(`Сохранена версия правок №${result.revision_number}.`);
      await refresh();
      const nextDetail = await client.getReviewCase(reviewCaseId);
      setDetail(nextDetail);
    } catch (error) {
      setNotice(errorMessage(error));
      throw error;
    } finally {
      setActionBusy(false);
    }
  }

  async function archiveProgram(programId: string, reason: string) {
    setActionBusy(true);
    try {
      await client.archiveProgram(programId, reason, createOperatorIdempotencyKey('archive'));
    } finally {
      setActionBusy(false);
    }
  }

  async function republishProgram(programId: string, reason: string) {
    setActionBusy(true);
    try {
      await client.republishProgram(programId, reason, createOperatorIdempotencyKey('republish'));
    } finally {
      setActionBusy(false);
    }
  }

  const reviewCount = data?.reviewCases.length ?? 0;
  const errorCount = data?.qualityIssues.filter((issue) => issue.severity === 'error').length ?? 0;
  const discoveryCount = data?.discoveryCases.length ?? 0;

  return (
    <main className="page-container" aria-labelledby="operator-title">
      <header className="flex flex-col gap-5 border-b border-ink/10 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">Локальная операторская панель</p>
          <h1 id="operator-title" className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Проверка данных и публикация</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-graphite">Публичный каталог остаётся изолированным: здесь доступны только защищённые операции с кандидатами, качеством, источниками и аудитом.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="button-secondary" onClick={() => void refresh()} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Обновить</button>
          <button type="button" className="button-secondary" onClick={onSignOut}><LogOut className="mr-2 h-4 w-4" aria-hidden="true" />Выйти</button>
        </div>
      </header>

      {notice ? <p role="status" className="mt-5 rounded-lg border border-cobalt/25 bg-cobalt/10 p-3 text-sm text-graphite">{notice}</p> : null}
      {loadError ? <div className="mt-7"><EmptyState title="Панель временно недоступна" description={loadError}><button type="button" className="button-primary" onClick={() => void refresh()}>Повторить</button></EmptyState></div> : null}

      {!loadError ? <>
        <section aria-label="Сводка очередей" className="mt-7 grid gap-3 sm:grid-cols-3">
          <MetricTile label="Каноническая очередь" value={reviewCount} hint="кандидатов ждут решения" />
          <MetricTile label="Блокирующие ошибки" value={errorCount} hint="публикация таких записей запрещена" />
          <MetricTile label="Discovery-кандидаты" value={discoveryCount} hint="внешние ссылки ждут маршрутизации" />
        </section>

        <nav className="mt-7 flex flex-wrap gap-2" aria-label="Разделы операторской панели">
          {([
            ['review', 'Очередь'],
            ['quality', 'Качество'],
            ['runs', 'Запуски'],
            ['discovery', 'Discovery'],
            ['publication', 'Публикация']
          ] as [OperatorView, string][]).map(([view, label]) => <button key={view} type="button" aria-current={activeView === view ? 'page' : undefined} className={activeView === view ? 'button-primary' : 'button-secondary'} onClick={() => setActiveView(view)}>{label}</button>)}
        </nav>

        <section className="mt-5">
          {loading || !data ? <Panel title="Загружаем операционные данные"><p role="status" className="text-sm text-graphite">Получаем очередь, журнал запусков и конфигурацию источников…</p></Panel> : null}
          {!loading && data && activeView === 'review' ? <ReviewWorkspace reviewCases={data.reviewCases} issues={data.qualityIssues} selectedCaseId={selectedCaseId} onSelect={setSelectedCaseId} detail={detail} detailLoading={detailLoading} actionBusy={actionBusy} onAction={applyReviewAction} onSaveRevision={saveReviewRevision} /> : null}
          {!loading && data && activeView === 'quality' ? <QualityWorkspace issues={data.qualityIssues} onOpenReviewCase={(id) => { setActiveView('review'); setSelectedCaseId(id); }} /> : null}
          {!loading && data && activeView === 'runs' ? <RunsWorkspace executionRuns={data.executionRuns} ingestionRuns={data.ingestionRuns} sourceDefinitions={data.sourceDefinitions} /> : null}
          {!loading && data && activeView === 'discovery' ? <DiscoveryWorkspace cases={data.discoveryCases} sourceDefinitions={data.sourceDefinitions} busy={actionBusy} onAction={applyDiscoveryAction} /> : null}
          {!loading && data && activeView === 'publication' ? <PublicationWorkspace busy={actionBusy} onArchive={archiveProgram} onRepublish={republishProgram} /> : null}
        </section>
      </> : null}
    </main>
  );
}

export function OperatorApp({ clientFactory = createOperatorApiClient }: { clientFactory?: ClientFactory }) {
  const [client, setClient] = useState<OperatorApiClient | null>(null);
  return client ? <OperatorWorkspace client={client} onSignOut={() => setClient(null)} /> : <AccessGate clientFactory={clientFactory} onConnected={setClient} />;
}
