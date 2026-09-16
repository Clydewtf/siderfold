import { ExternalLink, X } from 'lucide-react';
import { useEffect, useRef, type KeyboardEvent } from 'react';
import { formatDateRange, formatDeadline, formatOptionalDate, isValidExternalUrl } from '../lib/format';
import { fundingScopeLabel, type PublicProgram } from '../data-access/catalogMapper';
import { applicationStatus } from '../lib/applicationStatus';
import { useCurrentDate } from '../lib/useCurrentDate';
import { ApplicationStatusTag } from './ApplicationStatusTag';
import { FavoriteToggle } from './FavoriteToggle';
import { EmptyState, Tag } from './ui';

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',');

function PublicDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-ink/10 bg-white/70 p-4">
      <h3 className="text-sm font-semibold text-graphite">{label}</h3>
      <p className="mt-2 break-words text-sm text-ink">{value}</p>
    </div>
  );
}

function applicationAccessLabel(mode: PublicProgram['accessMode']): string {
  const labels: Record<PublicProgram['accessMode'], string> = {
    unknown: 'Не указан источником',
    open: 'Открытый конкурс',
    invitation_only: 'Только по приглашению'
  };
  return labels[mode];
}

function fundingDetailLabel(amount: PublicProgram['fundingAmounts'][number]): string {
  const sourceLabel = amount.sourceLabel?.trim();
  if (!sourceLabel || /на\s+одн\w+\s+(?:программ\w*|получател\w*)/i.test(sourceLabel)) {
    return amount.label;
  }
  return `${sourceLabel} — ${amount.label}`;
}

function isSocialResource(url: string): boolean {
  try {
    const hostname = new URL(url).hostname.toLocaleLowerCase('en').replace(/^www\./, '');
    return ['t.me', 'telegram.me', 'vk.com', 'vkontakte.ru'].some(
      (host) => hostname === host || hostname.endsWith(`.${host}`)
    );
  } catch {
    return false;
  }
}

function socialResourceLabel(url: string): string {
  try {
    const hostname = new URL(url).hostname.toLocaleLowerCase('en').replace(/^www\./, '');
    if (hostname === 't.me' || hostname.endsWith('.t.me') || hostname === 'telegram.me' || hostname.endsWith('.telegram.me')) {
      return 'Telegram';
    }
    if (hostname === 'vk.com' || hostname.endsWith('.vk.com') || hostname === 'vkontakte.ru' || hostname.endsWith('.vkontakte.ru')) {
      return 'ВКонтакте';
    }
  } catch {
    return 'Официальный канал';
  }
  return 'Официальный канал';
}

function isWinnerResource(resource: PublicProgram['resources'][number]): boolean {
  if (isSocialResource(resource.url)) return false;
  if (resource.kind === 'result') return true;
  return isWinnerText(`${resource.title ?? ''} ${resource.sourceSection ?? ''} ${decodedUrlPath(resource.url)}`);
}

function decodedUrlPath(url: string): string {
  try {
    return decodeURIComponent(new URL(url).pathname);
  } catch {
    return url;
  }
}

function isWinnerText(value: string): boolean {
  return /(?:победител|лауреат|(?:итог|результат)[\p{L}\p{N}_]*\s+(?:конкурс|отбор|программ))/iu.test(value);
}

function isScheduleMilestone(value: string): boolean {
  return /(?:объявлен[\p{L}\p{N}_]*\s+(?:результат|победител|итог)|подведен[\p{L}\p{N}_]*\s+(?:итог|результат)|(?:вводн[\p{L}\p{N}_]*\s+)?семинар[\p{L}\p{N}_]*\s+(?:для\s+)?победител|заключен[\p{L}\p{N}_]*\s+договор[\p{L}\p{N}_]*\s+(?:с\s+)?победител)/iu.test(value);
}

function isWinnerSection(section: PublicProgram['contentSections'][number]): boolean {
  return isWinnerText(section.heading) && !isScheduleMilestone(section.heading);
}

type WinnerResource = PublicProgram['resources'][number];

function winnerYear(resource: WinnerResource): string | null {
  const sourceSection = resource.sourceSection?.trim();
  if (!sourceSection) return null;
  const match = /(?:^|·)\s*(20\d{2}\s+год(?:а)?)\s*$/iu.exec(sourceSection);
  return match?.[1] ?? null;
}

function groupWinnerResources(resources: WinnerResource[]): Array<{ year: string | null; resources: WinnerResource[] }> {
  const groups: Array<{ year: string | null; resources: WinnerResource[] }> = [];
  for (const resource of resources) {
    const year = winnerYear(resource);
    const previous = groups[groups.length - 1];
    if (previous && previous.year === year) {
      previous.resources.push(resource);
      continue;
    }
    groups.push({ year, resources: [resource] });
  }
  return groups;
}

function ResourceCard({
  resource,
  winner = false,
  channel = false
}: {
  resource: PublicProgram['resources'][number];
  winner?: boolean;
  channel?: boolean;
}) {
  const title = channel
    ? socialResourceLabel(resource.url)
    : resource.title ?? (winner ? 'Список победителей' : resource.sourceSection ?? 'Материал источника');
  const action = winner ? 'Открыть список победителей' : channel ? 'Открыть канал' : 'Открыть материал';

  return (
    <div className="rounded-lg border border-ink/10 bg-white/70 p-4">
      <p className="font-semibold text-ink">{title}</p>
      {channel ? <p className="mt-1 text-sm text-graphite">Официальный канал конкурса</p> : null}
      {!winner && !channel && resource.sourceSection ? <p className="mt-1 text-sm text-graphite">{resource.sourceSection}</p> : null}
      {isValidExternalUrl(resource.url) ? (
        <a
          href={resource.url}
          target="_blank"
          rel="noreferrer"
          className="mt-3 inline-flex items-center text-sm font-semibold text-cobalt"
        >
          {action} <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
        </a>
      ) : null}
    </div>
  );
}

export function ApiProgramDrawer({
  program,
  loading,
  error,
  isFavorite,
  onToggleFavorite,
  onRetry,
  onClose,
  embedded = false,
  preview = false
}: {
  program: PublicProgram | null;
  loading: boolean;
  error: string | null;
  isFavorite: boolean;
  onToggleFavorite: () => void;
  onRetry: () => void;
  onClose: () => void;
  embedded?: boolean;
  preview?: boolean;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const now = useCurrentDate();
  const status = program ? applicationStatus(program, now) : null;
  const socialResources = program?.resources.filter((resource) => isSocialResource(resource.url)) ?? [];
  const winnerResources = program?.resources.filter(isWinnerResource) ?? [];
  const winnerResourceGroups = groupWinnerResources(winnerResources);
  const documentResources = program?.resources.filter(
    (resource) => resource.kind !== 'application' && !isSocialResource(resource.url) && !isWinnerResource(resource)
  ) ?? [];
  const winnerSections = program?.contentSections.filter(
    (section) => section.category === 'results' && isWinnerSection(section)
  ) ?? [];
  const additionalSections = program?.contentSections.filter((section) => section.category !== 'results') ?? [];

  useEffect(() => {
    if (embedded) return undefined;
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();

    return () => {
      if (openerRef.current && document.contains(openerRef.current)) openerRef.current.focus();
    };
  }, [embedded]);

  function getFocusableElements() {
    return Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;

    const elements = getFocusableElements();
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (!first || !last) {
      event.preventDefault();
      dialogRef.current?.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      data-testid={embedded ? undefined : 'program-drawer-overlay'}
      className={embedded ? 'w-full' : 'program-drawer-overlay fixed inset-0 z-50 flex justify-end p-3 backdrop-blur-sm'}
      role={embedded ? undefined : 'presentation'}
      onClick={(event) => {
        if (!embedded && event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role={embedded ? undefined : 'dialog'}
        aria-modal={embedded ? undefined : true}
        aria-label={program?.title ?? 'Карточка программы'}
        tabIndex={embedded ? undefined : -1}
        onKeyDown={embedded ? undefined : handleKeyDown}
        className={embedded ? 'w-full rounded-xl border border-ink/10 bg-paper p-5 shadow-sm sm:p-6' : 'h-full w-full max-w-2xl overflow-y-auto rounded-lg bg-paper p-6 shadow-panel'}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-cobalt">{program?.primarySource.source.name ?? 'Public API'}</p>
            <h2 className="mt-2 break-words text-3xl font-semibold text-ink">
              {program?.title ?? 'Карточка программы'}
            </h2>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {!embedded && program ? <FavoriteToggle itemName={program.title} isFavorite={isFavorite} onToggle={onToggleFavorite} /> : null}
            {!embedded ? (
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="Закрыть детали"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-ink text-white"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
            ) : null}
          </div>
        </div>

        {loading ? <p role="status" className="mt-8 text-sm text-graphite">Загружаем карточку программы…</p> : null}
        {error ? (
          <div className="mt-8">
            <EmptyState title="Карточка временно недоступна" description={error}>
              <button type="button" onClick={onRetry} className="button-secondary">Повторить</button>
            </EmptyState>
          </div>
        ) : null}
        {program && !loading && !error ? (
          <>
            <div className="mt-5 flex flex-wrap gap-2">
              <ApplicationStatusTag program={program} />
              {program.deadline ? <Tag>Приём до {formatDeadline(program.deadline)}</Tag> : null}
              <Tag>{program.funding ? `Финансирование: ${program.funding.label}` : 'Сумма не указана'}</Tag>
            </div>

            {program.applicationUrl && isValidExternalUrl(program.applicationUrl) ? (
              <a
                href={program.applicationUrl}
                target="_blank"
                rel="noreferrer"
                className="button-primary mt-4 inline-flex items-center"
              >
                Подать заявку <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
              </a>
            ) : null}

            <p className="mt-6 text-base leading-7 text-graphite">
              {program.summary ?? 'Краткое описание не извлечено; подробные условия доступны на первоисточнике.'}
            </p>

            <section aria-labelledby="public-program-overview" className="mt-8 grid gap-4 sm:grid-cols-2">
              <h3 id="public-program-overview" className="sr-only">Основные параметры</h3>
              <PublicDetail label="Дата публикации на источнике" value={formatOptionalDate(program.sourcePublishedOn)} />
              <PublicDetail
                label="Добавлено в Siderfold"
                value={preview ? 'Появится после публикации' : formatOptionalDate(program.publishedAt.slice(0, 10))}
              />
              <PublicDetail
                label="Статус конкурса"
                value={status?.label ?? 'Статус конкурса не указан'}
              />
              {program.accessMode !== 'unknown' ? (
                <PublicDetail label="Условия подачи" value={applicationAccessLabel(program.accessMode)} />
              ) : null}
              <PublicDetail
                label="Приём заявок"
                value={formatDateRange(program.applicationStart, program.applicationEnd ?? program.deadline)}
              />
              <PublicDetail label="Регионы" value={program.regions.length > 0 ? program.regions.join(', ') : 'Не указаны'} />
              <PublicDetail label="Тематики" value={program.themes.length > 0 ? program.themes.join(', ') : 'Не указаны'} />
            </section>

            <section className="mt-8">
              <h3 className="text-lg font-semibold">Финансирование</h3>
              {program.fundingAmounts.length > 0 ? (
                <ul className="mt-3 space-y-2 text-sm text-graphite">
                  {program.fundingAmounts.map((amount, index) => (
                    <li key={`${amount.scope}:${amount.sourceLabel}:${index}`}>
                      <span className="font-semibold text-ink">{fundingScopeLabel(amount.scope)}:</span>{' '}
                      {fundingDetailLabel(amount)}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-graphite">{program.funding?.label ?? 'Сумма не указана'}</p>
              )}
            </section>

            {program.eligibilitySummary ? (
              <section className="mt-8">
                <h3 className="text-lg font-semibold">Условия участия</h3>
                <p className="mt-3 text-sm leading-6 text-graphite">{program.eligibilitySummary}</p>
              </section>
            ) : null}

            {program.timeline.length > 0 ? (
              <section className="mt-8">
                <h3 className="text-lg font-semibold">График</h3>
                <ul className="mt-3 space-y-3 text-sm text-graphite">
                  {program.timeline.map((event, index) => (
                    <li key={`${event.kind}:${event.label}:${index}`} className="rounded-lg border border-ink/10 bg-white/70 p-4">
                      <p className="font-semibold text-ink">{event.label}</p>
                      <p className="mt-1">{formatDateRange(event.start, event.end)}</p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {winnerResources.length > 0 || winnerSections.length > 0 ? (
              <section className="mt-8">
                <h3 className="text-lg font-semibold">Победители</h3>
                {winnerResources.length > 0 ? (
                  <div className="mt-3 space-y-6">
                    {winnerResourceGroups.map((group, index) => (
                      <div key={`${group.year ?? 'without-year'}:${index}`}>
                        {group.year ? <h4 className="font-semibold text-ink">{group.year}</h4> : null}
                        <div className={group.year ? 'mt-3 space-y-3' : 'space-y-3'}>
                          {group.resources.map((resource) => <ResourceCard key={resource.url} resource={resource} winner />)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 space-y-4">
                    {winnerSections.map((section) => (
                      <div key={`${section.category}:${section.heading}`} className="rounded-lg border border-ink/10 bg-white/70 p-4">
                        <h4 className="font-semibold text-ink">{section.heading}</h4>
                        <p className="mt-2 text-sm leading-6 text-graphite">{section.content}</p>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            ) : null}

            {documentResources.length > 0 || socialResources.length > 0 ? (
              <section className="mt-8">
                <h3 className="text-lg font-semibold">Документы и ссылки</h3>
                {documentResources.length > 0 ? (
                  <div className="mt-3 space-y-3">
                    {documentResources.map((resource) => <ResourceCard key={resource.url} resource={resource} />)}
                  </div>
                ) : null}
                {socialResources.length > 0 ? (
                  <div className={documentResources.length > 0 ? 'mt-6' : 'mt-3'}>
                    <h4 className="font-semibold text-ink">Официальные каналы</h4>
                    <div className="mt-3 space-y-3">
                      {socialResources.map((resource) => <ResourceCard key={resource.url} resource={resource} channel />)}
                    </div>
                  </div>
                ) : null}
              </section>
            ) : null}

            {additionalSections.length > 0 ? (
              <section className="mt-8">
                <h3 className="text-lg font-semibold">Дополнительная информация</h3>
                <div className="mt-3 space-y-4">
                  {additionalSections.map((section) => (
                    <div key={`${section.category}:${section.heading}`} className="rounded-lg border border-ink/10 bg-white/70 p-4">
                      <h4 className="font-semibold text-ink">{section.heading}</h4>
                      <p className="mt-2 text-sm leading-6 text-graphite">{section.content}</p>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="mt-8">
              <h3 className="text-lg font-semibold">Источники</h3>
              <div className="mt-3 space-y-3">
                {program.sources.map((source) => (
                  <div key={`${source.source.id}:${source.sourceUrl}`} className="rounded-lg border border-ink/10 bg-white/70 p-4">
                    <p className="font-semibold text-ink">{source.source.name}</p>
                    <p className="mt-1 text-sm text-graphite">Наблюдалось {formatDeadline(source.observedAt.slice(0, 10))}</p>
                    {isValidExternalUrl(source.sourceUrl) ? (
                      <a
                        href={source.sourceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 inline-flex items-center text-sm font-semibold text-cobalt"
                      >
                        Открыть первоисточник <ExternalLink className="ml-2 h-4 w-4" aria-hidden="true" />
                      </a>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          </>
        ) : null}
      </section>
    </div>
  );
}
