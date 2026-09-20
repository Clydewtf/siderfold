import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { OperatorApp } from './OperatorApp';
import type { OperatorApiClient, ReviewCaseDetail, ReviewQueueItem } from './api';

const reviewCase: ReviewQueueItem = {
  review_case_id: 'case-1',
  staged_record_id: 'staged-1',
  status: 'open',
  opened_at: '2026-09-11T10:00:00Z',
  reason_codes: ['candidate_ready'],
  title: 'Проверяемая программа',
  source_url: 'https://source.example.test/programs/one'
};

const reviewDetail: ReviewCaseDetail = {
  ...reviewCase,
  opened_snapshot: {
    candidate_payload: {
      record: {
        title: 'Проверяемая программа',
        record_url: 'https://source.example.test/programs/one',
        application_end_on: '2026-11-30',
        funding: { value_kind: 'maximum', currency_code: 'RUB', max_amount: '1000000' }
      }
    },
    reason_codes: ['candidate_ready'],
    matches: []
  },
  source_record: {
    title: 'Проверяемая программа',
    record_url: 'https://source.example.test/programs/one',
    deadline_on: '2026-11-30',
    funding: { value_kind: 'maximum', currency_code: 'RUB', max_amount: '1000000' },
    payload: { summary: 'Исходное описание программы.' }
  },
  effective_record: {
    title: 'Проверяемая программа',
    record_url: 'https://source.example.test/programs/one',
    deadline_on: '2026-11-30',
    funding: { value_kind: 'maximum', currency_code: 'RUB', max_amount: '1000000' },
    payload: {
      summary: 'Исходное описание программы.',
      artifacts: [
        {
          kind: 'document',
          url: 'https://source.example.test/files/rules.pdf',
          label: 'Старое название документа',
          section_title: 'Документы конкурса',
          section_category: 'documents',
          capture: { content_format: 'application/pdf' }
        }
      ]
    }
  },
  provenance: {
    source_id: 'source-1',
    source_name: 'Тестовый источник',
    source_canonical_url: 'https://source.example.test',
    source_url: 'https://source.example.test/programs/one',
    raw_capture_id: 'raw-1',
    ingestion_run_id: 'run-1',
    received_at: '2026-09-11T10:00:00Z',
    content_sha256: 'a'.repeat(64),
    content_format: 'text/html',
    adapter_name: 'fixture',
    adapter_version: '1.0.0'
  },
  quality_issues: [],
  actions: [],
  revisions: [],
  public_preview: {
    title: 'Проверяемая программа',
    source: { id: 'source-1', name: 'Тестовый источник', canonical_url: 'https://source.example.test' },
    source_url: 'https://source.example.test/programs/one',
    observed_at: '2026-09-11T10:00:00Z',
    source_published_on: null,
    summary: 'Исходное описание программы.',
    source_status: 'unknown',
    deadline_on: '2026-11-30',
    funding: { value_kind: 'maximum', currency_code: 'RUB', exact_amount: null, min_amount: null, max_amount: '1000000' },
    geographies: [],
    themes: [],
    eligibility_summary: null,
    eligibility_geography_note: null,
    access_mode: 'unknown',
    application_url: null,
    application_start_on: null,
    application_end_on: '2026-11-30',
    funding_amounts: [],
    timeline: [],
    resources: [
      {
        kind: 'competition_document',
        title: 'Старое название документа',
        url: 'https://source.example.test/files/rules.pdf',
        source_section: 'Документы конкурса'
      }
    ],
    content_sections: []
  }
};

function createClient(): OperatorApiClient {
  return {
    listReviewCases: vi.fn().mockResolvedValue([reviewCase]),
    getReviewCase: vi.fn().mockResolvedValue(reviewDetail),
    getDeduplicationMatchTarget: vi.fn(),
    listQualityIssues: vi.fn().mockResolvedValue([]),
    listDiscoveryCases: vi.fn().mockResolvedValue([]),
    listSourceDefinitions: vi.fn().mockResolvedValue([]),
    listExecutionRuns: vi.fn().mockResolvedValue([]),
    listIngestionRuns: vi.fn().mockResolvedValue([]),
    applyReviewAction: vi.fn().mockResolvedValue({
      operation_id: 'operation-1',
      replayed: false,
      review_case_id: 'case-1',
      staged_record_id: 'staged-1',
      review_action_id: 'action-1',
      program_id: 'program-1',
      review_decision_id: 'decision-1'
    }),
    saveReviewRevision: vi.fn().mockResolvedValue({
      operation_id: 'operation-revision-1',
      replayed: false,
      review_case_id: 'case-1',
      staged_record_id: 'staged-1',
      review_revision_id: 'revision-1',
      revision_number: 1,
      changed_fields: ['title'],
      resolved_issue_ids: []
    }),
    applyDiscoveryAction: vi.fn(),
    archiveProgram: vi.fn(),
    republishProgram: vi.fn()
  };
}

describe('operator panel', () => {
  it('reveals a deduplication target and opens its review card from the match', async () => {
    const user = userEvent.setup();
    const targetCase: ReviewQueueItem = {
      ...reviewCase,
      review_case_id: 'case-target',
      staged_record_id: 'staged-target',
      title: 'Новые искатели 2025'
    };
    const detailWithMatch: ReviewCaseDetail = {
      ...reviewDetail,
      opened_snapshot: {
        ...reviewDetail.opened_snapshot,
        matches: [{
          id: 'match-1',
          target_staged_record_id: 'staged-target',
          target_program_id: null,
          evidence: {
            match_level: 'normalized_fields',
            target: { title: 'новые искатели 2025' }
          }
        }]
      }
    };
    const client = createClient();
    client.listReviewCases = vi.fn().mockResolvedValue([reviewCase, targetCase]);
    client.getReviewCase = vi.fn().mockImplementation((reviewCaseId: string) => Promise.resolve(
      reviewCaseId === 'case-target' ? { ...reviewDetail, ...targetCase } : detailWithMatch
    ));
    client.getDeduplicationMatchTarget = vi.fn().mockResolvedValue({
      kind: 'staged_record',
      id: 'staged-target',
      title: 'Новые искатели 2025',
      source_name: 'Фонд Тимченко',
      source_url: 'https://fondtimchenko.ru/contests/archive/novye-iskateli-2025/',
      deadline_on: '2025-10-19',
      staged_state: 'review',
      review_case_id: 'case-target',
      review_case_status: 'open',
      publication_status: null
    });

    render(<OperatorApp clientFactory={() => client} />);

    await user.type(screen.getByLabelText('Токен внутреннего доступа'), 'local-token');
    await user.click(screen.getByRole('button', { name: 'Открыть операторскую панель' }));
    await user.click(await screen.findByRole('button', { name: 'Показать карточку совпадения' }));

    expect((await screen.findAllByText('Новые искатели 2025')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Открыть карточку кандидата' }));
    await waitFor(() => expect(client.getReviewCase).toHaveBeenCalledWith('case-target'));
  });

  it('keeps the token in the current UI session and submits a reviewed decision through the internal client', async () => {
    const user = userEvent.setup();
    const client = createClient();
    const clientFactory = vi.fn(() => client);

    render(<OperatorApp clientFactory={clientFactory} />);

    await user.type(screen.getByLabelText('Токен внутреннего доступа'), 'local-token');
    await user.click(screen.getByRole('button', { name: 'Открыть операторскую панель' }));

    await screen.findByRole('button', { name: 'Принять и опубликовать' });
    expect(clientFactory).toHaveBeenCalledWith({ token: 'local-token' });
    expect(window.sessionStorage.length).toBe(0);

    await user.click(screen.getByRole('button', { name: 'Принять и опубликовать' }));
    await user.type(screen.getByLabelText('Причина решения'), 'Поля сверены с первоисточником.');
    await user.click(screen.getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => {
      expect(client.applyReviewAction).toHaveBeenCalledWith(
        'case-1',
        { action: 'accept', reason: 'Поля сверены с первоисточником.' },
        expect.stringMatching(/^operator-ui:accept:/)
      );
    });
  });

  it('requires an explicit confirmation before accepting selected clean candidates in bulk', async () => {
    const user = userEvent.setup();
    const client = createClient();

    render(<OperatorApp clientFactory={() => client} />);

    await user.type(screen.getByLabelText('Токен внутреннего доступа'), 'local-token');
    await user.click(screen.getByRole('button', { name: 'Открыть операторскую панель' }));
    await screen.findByLabelText('Выбрать Проверяемая программа для массового действия');

    await user.click(screen.getByLabelText('Выбрать Проверяемая программа для массового действия'));
    await user.type(screen.getByLabelText('Общая причина'), 'Проверено для массовой публикации.');
    const submit = screen.getByRole('button', { name: 'Принять чистые (1)' });
    expect(submit).toBeDisabled();
    await user.click(screen.getByLabelText('Я проверил выбранные записи и подтверждаю это массовое действие.'));
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => {
      expect(client.applyReviewAction).toHaveBeenCalledWith(
        'case-1',
        { action: 'accept', reason: 'Проверено для массовой публикации.' },
        expect.stringMatching(/^operator-ui:accept:/)
      );
    });
  });

  it('shows source data, a public-card preview, and saves an audited correction separately from review actions', async () => {
    const user = userEvent.setup();
    const client = createClient();

    render(<OperatorApp clientFactory={() => client} />);

    await user.type(screen.getByLabelText('Токен внутреннего доступа'), 'local-token');
    await user.click(screen.getByRole('button', { name: 'Открыть операторскую панель' }));

    await screen.findByText('Все собранные данные источника');
    expect(screen.getByText('Происхождение записи')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Предпросмотр карточки' }));
    expect(await screen.findByText('Появится после публикации')).toBeInTheDocument();
    expect(screen.getByText('Исходное описание программы.')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Правки оператора' }));
    await user.clear(screen.getByLabelText('Краткое описание'));
    await user.type(
      screen.getByLabelText('Краткое описание'),
      'Первый абзац после ручной сверки.\n\nВторой абзац после ручной сверки.'
    );
    await user.type(screen.getByLabelText('Причина правки'), 'Данные сверены с официальной страницей.');
    await user.click(screen.getByRole('button', { name: 'Сохранить версию правок' }));

    await waitFor(() => {
      expect(client.saveReviewRevision).toHaveBeenCalledWith(
        'case-1',
        expect.objectContaining({
          reason: 'Данные сверены с официальной страницей.',
          patch: { summary: 'Первый абзац после ручной сверки.\n\nВторой абзац после ручной сверки.' },
          resolve_issue_ids: []
        }),
        expect.stringMatching(/^operator-ui:save-revision:/)
      );
    });
  });

  it('lets an operator correct the public documents, winner links, and official channels', async () => {
    const user = userEvent.setup();
    const client = createClient();

    render(<OperatorApp clientFactory={() => client} />);

    await user.type(screen.getByLabelText('Токен внутреннего доступа'), 'local-token');
    await user.click(screen.getByRole('button', { name: 'Открыть операторскую панель' }));
    await screen.findByText('Все собранные данные источника');
    await user.click(screen.getByRole('tab', { name: 'Правки оператора' }));

    await user.clear(screen.getByLabelText('Название материала'));
    await user.type(screen.getByLabelText('Название материала'), 'Положение о конкурсе');
    await user.type(screen.getByLabelText('Причина правки'), 'Сверил название с официальным документом.');
    await user.click(screen.getByRole('button', { name: 'Сохранить версию правок' }));

    await waitFor(() => {
      expect(client.saveReviewRevision).toHaveBeenCalledWith(
        'case-1',
        expect.objectContaining({
          patch: {
            resources: [
              {
                kind: 'document',
                label: 'Положение о конкурсе',
                url: 'https://source.example.test/files/rules.pdf',
                section_title: 'Документы конкурса',
                section_category: 'documents',
                content_format: 'application/pdf'
              }
            ]
          },
          reason: 'Сверил название с официальным документом.'
        }),
        expect.stringMatching(/^operator-ui:save-revision:/)
      );
    });
  });
});
