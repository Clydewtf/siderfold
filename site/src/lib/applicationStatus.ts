import type { SourceStatus, TimelineEventKind } from '../data-access/catalogApi';

export type ApplicationStatusInput = {
  sourceStatus: SourceStatus;
  deadline: string | null;
  applicationStart: string | null;
  applicationEnd: string | null;
  timeline: readonly {
    kind: TimelineEventKind;
    start: string | null;
    end: string | null;
  }[];
};

export type ApplicationStatus = {
  value: SourceStatus;
  label: string;
  derived: boolean;
};

const sourceLabels: Record<SourceStatus, string> = {
  unknown: 'Статус приёма не указан',
  open: 'Приём заявок открыт',
  closed: 'Приём заявок завершён',
  completed: 'Конкурс завершён',
  upcoming: 'Приём заявок ещё не начался'
};

function localDateKey(now: Date): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function dateStatus(start: string | null, end: string | null, today: string): SourceStatus | null {
  if (start && start > today) return 'upcoming';
  if (end && end < today) return 'closed';
  if (end && end >= today && (!start || start <= today)) return 'open';
  if (start && start <= today) return 'open';
  return null;
}

function dateKeyDaysBefore(now: Date, days: number): string {
  const value = new Date(now);
  value.setDate(value.getDate() - days);
  return localDateKey(value);
}

function latestKnownLifecycleDate(program: ApplicationStatusInput): string | null {
  const dates = [program.deadline, program.applicationEnd, ...program.timeline.flatMap((event) => [event.start, event.end])]
    .filter((value): value is string => value !== null);
  return dates.length > 0 ? dates.reduce((latest, value) => value > latest ? value : latest) : null;
}

function activeLifecycleLabel(program: ApplicationStatusInput, today: string): string | null {
  const activeEvent = program.timeline.find((event) =>
    event.kind !== 'application'
    && event.start !== null
    && event.start <= today
    && (event.end === null || event.end >= today)
  );
  if (!activeEvent) return null;

  const labels: Partial<Record<TimelineEventKind, string>> = {
    evaluation: 'Идёт экспертиза заявок',
    results: 'Подводятся итоги конкурса',
    contracting: 'Идёт заключение договоров',
    implementation: 'Идёт реализация проектов'
  };
  return labels[activeEvent.kind] ?? null;
}

export function applicationStatus(
  program: ApplicationStatusInput,
  now: Date = new Date()
): ApplicationStatus {
  if (program.sourceStatus === 'open' || program.sourceStatus === 'upcoming' || program.sourceStatus === 'completed') {
    return {
      value: program.sourceStatus,
      label: sourceLabels[program.sourceStatus],
      derived: false
    };
  }

  const today = localDateKey(now);
  const applicationWindows = program.timeline.filter((event) => event.kind === 'application');
  const windowStatuses = applicationWindows
    .map((event) => dateStatus(event.start, event.end, today))
    .filter((value): value is SourceStatus => value !== null);
  const applicationState = windowStatuses.includes('open')
    ? 'open'
    : windowStatuses.includes('upcoming')
      ? 'upcoming'
      : windowStatuses.includes('closed')
        ? 'closed'
        : dateStatus(program.applicationStart, program.applicationEnd ?? program.deadline, today);
  const latestLifecycleDate = latestKnownLifecycleDate(program);
  const completionCutoff = dateKeyDaysBefore(now, 30);
  const derived = applicationState === 'open' || applicationState === 'upcoming'
    ? applicationState
    : latestLifecycleDate !== null && latestLifecycleDate <= completionCutoff
      ? 'completed'
      : program.sourceStatus === 'closed'
        ? 'closed'
        : applicationState;

  if (derived !== null) {
    return {
      value: derived,
      label: derived === 'closed'
        ? activeLifecycleLabel(program, today) ?? sourceLabels.closed
        : sourceLabels[derived],
      derived: true
    };
  }
  return {
    value: 'unknown',
    label: sourceLabels.unknown,
    derived: false
  };
}
