import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { SourcesTab } from './SourcesTab';

describe('SourcesTab', () => {
  it('renders source cards with program counters', () => {
    render(<SourcesTab sources={sources} programs={programs} />);

    expect(screen.getByRole('heading', { name: 'Источники программ' })).toBeInTheDocument();
    expect(screen.getAllByText('Фонд Потанина').length).toBeGreaterThan(1);
    expect(screen.getAllByText('3 программы').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2 актуальные').length).toBeGreaterThan(0);
  });

  it('filters by source type and topic', async () => {
    const user = userEvent.setup();
    render(<SourcesTab sources={sources} programs={programs} />);

    await user.selectOptions(screen.getByLabelText('Тип источника'), 'Акселератор');
    expect(screen.getByRole('article', { name: /Impact Hub Moscow/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Выбрать источник Фонд Потанина/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'Impact Hub Moscow' }).length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText('Тематика источника'), 'Экология');
    expect(screen.getByRole('article', { name: /Impact Hub Moscow/i })).toBeInTheDocument();
  });

  it('opens selected source details with related programs and external link', async () => {
    const user = userEvent.setup();
    render(<SourcesTab sources={sources} programs={programs} />);

    await user.click(screen.getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));

    expect(screen.getAllByRole('heading', { name: 'Impact Hub Moscow' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Eco Impact Lab').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: 'Открыть сайт источника' })[0]).toHaveAttribute('href', 'https://impacthubmoscow.net');

    await user.click(screen.getByRole('button', { name: /Выбрать источник Фонд Потанина/i }));

    expect(screen.getAllByRole('heading', { name: 'Фонд Потанина' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Стипендиальный конкурс для магистрантов').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: 'Открыть сайт источника' })[0]).toHaveAttribute('href', 'https://fondpotanin.ru');
  });

  it('keeps desktop source details sticky inside the reserved right column', () => {
    render(<SourcesTab sources={sources} programs={programs} />);

    const desktopColumn = screen.getByTestId('desktop-source-details-column');
    const desktopDetails = screen.getByTestId('desktop-source-details');

    expect(desktopColumn).toHaveClass('hidden', 'lg:block', 'lg:w-[420px]', 'lg:self-stretch');
    expect(desktopDetails).toHaveClass('lg:sticky', 'lg:top-28', 'lg:w-[420px]');
    expect(desktopDetails.className).toContain('lg:max-h-[calc(100vh-8rem)]');
    expect(desktopDetails).toHaveClass('lg:overflow-y-auto');
  });

  it('pins source card actions to the bottom of equal-height cards', () => {
    render(<SourcesTab sources={sources} programs={programs} />);

    const impactCard = screen.getByTestId('source-card-impact-hub');
    const impactActions = screen.getByTestId('source-card-actions-impact-hub');

    expect(impactCard).toHaveClass('flex', 'h-full', 'flex-col');
    expect(impactActions).toHaveClass('mt-auto');
  });

  it('marks the selected source and separates select from external website actions', async () => {
    const user = userEvent.setup();
    render(<SourcesTab sources={sources} programs={programs} />);

    const impactCard = screen.getByRole('article', { name: /Impact Hub Moscow/i });
    await user.click(within(impactCard).getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));

    expect(within(impactCard).getByText('Выбран')).toBeInTheDocument();
    expect(within(impactCard).getByRole('link', { name: /Открыть сайт Impact Hub Moscow/i })).toHaveAttribute(
      'href',
      'https://impacthubmoscow.net'
    );
    expect(screen.getByRole('button', { name: /Смотреть программы Impact Hub Moscow/i })).toBeInTheDocument();
  });

  it('announces source detail updates', async () => {
    const user = userEvent.setup();
    render(<SourcesTab sources={sources} programs={programs} />);

    await user.click(screen.getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));

    expect(screen.getByRole('status')).toHaveTextContent('Выбран источник: Impact Hub Moscow');
  });

  it('falls back to a filtered source when filters exclude the selected source', async () => {
    const user = userEvent.setup();
    render(<SourcesTab sources={sources} programs={programs} />);

    await user.click(screen.getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }));
    await user.selectOptions(screen.getByLabelText('Тип источника'), 'Фонд');

    expect(screen.queryByRole('article', { name: /Impact Hub Moscow/i })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Выбран источник: Фонд Потанина');

    const potaninCard = screen.getByRole('article', { name: /Фонд Потанина/i });
    expect(within(potaninCard).getByText('Выбран')).toBeInTheDocument();
    expect(screen.getAllByText('Стипендиальный конкурс для магистрантов').length).toBeGreaterThan(0);
  });
});
