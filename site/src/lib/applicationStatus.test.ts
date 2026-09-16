import { describe, expect, it } from 'vitest';
import { applicationStatus, type ApplicationStatusInput } from './applicationStatus';

const now = new Date(2026, 8, 5, 12, 0, 0);

function program(overrides: Partial<ApplicationStatusInput> = {}): ApplicationStatusInput {
  return {
    sourceStatus: 'unknown',
    deadline: null,
    applicationStart: null,
    applicationEnd: null,
    timeline: [],
    ...overrides
  };
}

describe('applicationStatus', () => {
  it('keeps an explicit source status instead of deriving a different one', () => {
    expect(applicationStatus(program({
      sourceStatus: 'completed',
      applicationEnd: '2026-12-01'
    }), now)).toEqual({
      value: 'completed',
      label: 'Конкурс завершён',
      derived: false
    });
  });

  it('marks a contest completed after its last known date has been past for 30 days', () => {
    expect(applicationStatus(program({ deadline: '2023-10-31' }), now)).toEqual({
      value: 'completed',
      label: 'Конкурс завершён',
      derived: true
    });
  });

  it('keeps a recently closed contest distinct from a completed one', () => {
    expect(applicationStatus(program({ deadline: '2026-08-20' }), now)).toEqual({
      value: 'closed',
      label: 'Приём заявок завершён',
      derived: true
    });
  });

  it('treats a future application deadline without a stated start date as open', () => {
    expect(applicationStatus(program({ deadline: '2026-09-20' }), now)).toEqual({
      value: 'open',
      label: 'Приём заявок открыт',
      derived: true
    });
  });

  it('prefers an active application window over a past window in the timeline', () => {
    expect(applicationStatus(program({
      timeline: [
        { kind: 'application', start: '2026-01-01', end: '2026-01-31' },
        { kind: 'application', start: '2026-09-01', end: '2026-09-30' }
      ]
    }), now)).toEqual({
      value: 'open',
      label: 'Приём заявок открыт',
      derived: true
    });
  });

  it('marks a future application window as upcoming', () => {
    expect(applicationStatus(program({
      timeline: [{ kind: 'application', start: '2026-10-01', end: '2026-10-31' }]
    }), now)).toEqual({
      value: 'upcoming',
      label: 'Приём заявок ещё не начался',
      derived: true
    });
  });

  it('uses the latest timeline date instead of an earlier application deadline', () => {
    expect(applicationStatus(program({
      deadline: '2023-10-31',
      timeline: [
        { kind: 'application', start: '2023-09-13', end: '2023-10-31' },
        { kind: 'results', start: null, end: '2024-01-10' },
        { kind: 'contracting', start: '2024-01-10', end: '2024-02-10' }
      ]
    }), now)).toEqual({
      value: 'completed',
      label: 'Конкурс завершён',
      derived: true
    });
  });

  it('does not mark a recently ended later stage completed too early', () => {
    expect(applicationStatus(program({
      deadline: '2026-06-01',
      timeline: [
        { kind: 'application', start: '2026-05-01', end: '2026-06-01' },
        { kind: 'implementation', start: '2026-06-02', end: '2026-08-25' }
      ]
    }), now)).toEqual({
      value: 'closed',
      label: 'Приём заявок завершён',
      derived: true
    });
  });

  it('does not mark a new open application window completed because an earlier cycle is old', () => {
    expect(applicationStatus(program({
      timeline: [
        { kind: 'application', start: '2026-09-01', end: '2026-09-30' },
        { kind: 'results', start: null, end: '2024-01-10' }
      ]
    }), now)).toEqual({
      value: 'open',
      label: 'Приём заявок открыт',
      derived: true
    });
  });

  it('shows an active post-application lifecycle stage when the schedule gives its date range', () => {
    expect(applicationStatus(program({
      deadline: '2026-08-31',
      timeline: [
        { kind: 'application', start: '2026-08-01', end: '2026-08-31' },
        { kind: 'evaluation', start: '2026-09-01', end: '2026-09-25' }
      ]
    }), now)).toEqual({
      value: 'closed',
      label: 'Идёт экспертиза заявок',
      derived: true
    });
  });
});
