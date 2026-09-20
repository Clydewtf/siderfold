import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { type PublicProgram } from '../data-access/catalogMapper';
import { ApiProgramDrawer } from './ApiProgramDrawer';

const program: PublicProgram = {
  id: 'program-1',
  title: 'Конкурс с опубликованными результатами',
  publicationStatus: 'published',
  publishedAt: '2026-09-12T08:00:00Z',
  updatedAt: '2026-09-12T08:00:00Z',
  sourcePublishedOn: null,
  deadline: null,
  funding: null,
  primarySource: {
    source: {
      id: 'source-1',
      name: 'Официальный источник',
      canonicalUrl: 'https://example.org',
      publishedProgramCount: null
    },
    sourceUrl: 'https://example.org/competition',
    observedAt: '2026-09-12T08:00:00Z'
  },
  sources: [],
  regions: [],
  themes: [],
  summary: null,
  eligibilitySummary: null,
  eligibilityGeographyNote: null,
  sourceStatus: 'unknown',
  accessMode: 'unknown',
  applicationUrl: null,
  applicationStart: null,
  applicationEnd: null,
  fundingAmounts: [],
  timeline: [],
  resources: [
    {
      kind: 'result',
      title: '2026 год',
      url: 'https://example.org/winners-2026.pdf',
      sourceSection: 'Победители'
    },
    {
      kind: 'competition_document',
      title: 'Список победителей 2025',
      url: 'https://example.org/winners-2025.pdf',
      sourceSection: 'Документы конкурса'
    },
    {
      kind: 'result',
      title: 'Телеграм-канал конкурса',
      url: 'https://t.me/example_competition',
      sourceSection: 'Победители'
    },
    {
      kind: 'competition_document',
      title: 'Положение о конкурсе',
      url: 'https://example.org/rules.pdf',
      sourceSection: 'Документы конкурса'
    }
  ],
  contentSections: [
    {
      heading: 'Победители',
      category: 'results',
      content: '2026 год 2025 год Телеграм-канал конкурса'
    },
    {
      heading: 'Критерии оценки',
      category: 'criteria',
      content: 'Заявки оцениваются независимыми экспертами.'
    }
  ]
};

describe('API program drawer', () => {
  it('keeps paragraph breaks and displays the publisher date label for a milestone', () => {
    const detailedProgram: PublicProgram = {
      ...program,
      summary: 'Первый абзац описания.\n\nВторой абзац описания.',
      timeline: [
        {
          kind: 'other',
          label: 'Вебинары для заявителей',
          start: null,
          end: null,
          dateLabel: 'Сентябрь 2026'
        }
      ]
    };

    render(
      <ApiProgramDrawer
        program={detailedProgram}
        loading={false}
        error={null}
        isFavorite={false}
        onToggleFavorite={() => undefined}
        onRetry={() => undefined}
        onClose={() => undefined}
        embedded
      />
    );

    const summary = screen.getByText(
      (_content, element) => element?.textContent === 'Первый абзац описания.\n\nВторой абзац описания.'
    );
    expect(summary).toHaveClass('whitespace-pre-line');
    expect(screen.getByText('Вебинары для заявителей')).toBeInTheDocument();
    expect(screen.getByText('Сентябрь 2026')).toBeInTheDocument();
  });

  it('shows winner materials once with links and keeps them out of general documents', () => {
    render(
      <ApiProgramDrawer
        program={program}
        loading={false}
        error={null}
        isFavorite={false}
        onToggleFavorite={() => undefined}
        onRetry={() => undefined}
        onClose={() => undefined}
        embedded
      />
    );

    const winners = screen.getByRole('heading', { name: 'Победители' }).closest('section');
    const documents = screen.getByRole('heading', { name: 'Документы и ссылки' }).closest('section');
    expect(winners).not.toBeNull();
    expect(documents).not.toBeNull();

    const winnerLinks = within(winners!).getAllByRole('link', { name: 'Открыть список победителей' });
    expect(winnerLinks).toHaveLength(2);
    expect(winnerLinks[0]).toHaveAttribute(
      'href',
      'https://example.org/winners-2026.pdf'
    );
    expect(within(winners!).queryByText('Телеграм-канал конкурса')).not.toBeInTheDocument();
    expect(within(documents!).getByText('Положение о конкурсе')).toBeInTheDocument();
    expect(within(documents!).getByRole('heading', { name: 'Официальные каналы' })).toBeInTheDocument();
    expect(within(documents!).getByText('Telegram')).toBeInTheDocument();
    expect(within(documents!).getByRole('link', { name: 'Открыть канал' })).toHaveAttribute(
      'href',
      'https://t.me/example_competition'
    );
    expect(within(documents!).queryByText('2026 год')).not.toBeInTheDocument();
    expect(within(documents!).queryByText('Список победителей 2025')).not.toBeInTheDocument();
  });

  it('uses winner evidence in a legacy URL and never shows schedule milestones as winners', () => {
    const legacyProgram: PublicProgram = {
      ...program,
      resources: [
        {
          kind: 'competition_document',
          title: '2025/2026',
          url: 'https://example.org/upload/%D0%BF%D0%BE%D0%B1%D0%B5%D0%B4%D0%B8%D1%82%D0%B5%D0%BB%D0%B8-2026.pdf',
          sourceSection: 'Консультации'
        }
      ],
      contentSections: [
        {
          heading: 'Объявление результатов конкурса',
          category: 'results',
          content: 'Не позднее 27 февраля 2026 года.'
        },
        {
          heading: 'Вводный семинар для победителей',
          category: 'results',
          content: 'Не позднее 6 марта 2026 года.'
        }
      ]
    };

    render(
      <ApiProgramDrawer
        program={legacyProgram}
        loading={false}
        error={null}
        isFavorite={false}
        onToggleFavorite={() => undefined}
        onRetry={() => undefined}
        onClose={() => undefined}
        embedded
      />
    );

    const winners = screen.getByRole('heading', { name: 'Победители' }).closest('section');
    expect(winners).not.toBeNull();
    expect(within(winners!).getByText('2025/2026')).toBeInTheDocument();
    expect(within(winners!).getByRole('link', { name: 'Открыть список победителей' })).toHaveAttribute(
      'href',
      'https://example.org/upload/%D0%BF%D0%BE%D0%B1%D0%B5%D0%B4%D0%B8%D1%82%D0%B5%D0%BB%D0%B8-2026.pdf'
    );
    expect(screen.queryByText('Объявление результатов конкурса')).not.toBeInTheDocument();
    expect(screen.queryByText('Вводный семинар для победителей')).not.toBeInTheDocument();
  });

  it('groups winner materials by the source year when that context is available', () => {
    const groupedProgram: PublicProgram = {
      ...program,
      resources: [
        {
          kind: 'result',
          title: 'I цикл',
          url: 'https://example.org/winners-2026-first.pdf',
          sourceSection: 'Победители конкурса · 2026 год'
        },
        {
          kind: 'result',
          title: 'II цикл',
          url: 'https://example.org/winners-2026-second.pdf',
          sourceSection: 'Победители конкурса · 2026 год'
        },
        {
          kind: 'result',
          title: 'I цикл',
          url: 'https://example.org/winners-2025-first.pdf',
          sourceSection: 'Победители конкурса · 2025 год'
        }
      ],
      contentSections: []
    };

    render(
      <ApiProgramDrawer
        program={groupedProgram}
        loading={false}
        error={null}
        isFavorite={false}
        onToggleFavorite={() => undefined}
        onRetry={() => undefined}
        onClose={() => undefined}
        embedded
      />
    );

    const winners = screen.getByRole('heading', { name: 'Победители' }).closest('section');
    expect(winners).not.toBeNull();
    expect(within(winners!).getByRole('heading', { name: '2026 год' })).toBeInTheDocument();
    expect(within(winners!).getByRole('heading', { name: '2025 год' })).toBeInTheDocument();
    expect(within(winners!).getAllByRole('link', { name: 'Открыть список победителей' })).toHaveLength(3);
  });

  it('keeps the application portal as a dedicated action instead of a document card', () => {
    render(
      <ApiProgramDrawer
        program={{
          ...program,
          applicationUrl: 'https://apply.example.org/creative-museum',
          resources: [
            {
              kind: 'application',
              title: 'Подать заявку',
              url: 'https://apply.example.org/creative-museum',
              sourceSection: 'Подача заявки'
            },
            {
              kind: 'competition_document',
              title: 'Положение о конкурсе',
              url: 'https://example.org/rules.pdf',
              sourceSection: 'Документы конкурса'
            }
          ],
          contentSections: []
        }}
        loading={false}
        error={null}
        isFavorite={false}
        onToggleFavorite={() => undefined}
        onRetry={() => undefined}
        onClose={() => undefined}
        embedded
      />
    );

    expect(screen.getByRole('link', { name: 'Подать заявку' })).toHaveAttribute(
      'href',
      'https://apply.example.org/creative-museum'
    );
    const documents = screen.getByRole('heading', { name: 'Документы и ссылки' }).closest('section');
    expect(documents).not.toBeNull();
    expect(within(documents!).queryByText('Подать заявку')).not.toBeInTheDocument();
    expect(within(documents!).getByText('Положение о конкурсе')).toBeInTheDocument();
  });
});
