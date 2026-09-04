import { readFileSync } from 'node:fs';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ComponentProps } from 'react';
import { programs, sources } from '../data/seed';
import { ProgramDrawer } from './ProgramDrawer';

const program = programs.find((item) => item.id === 'fasie-start-ai')!;
const source = sources.find((item) => item.id === program.sourceId)!;

function renderDrawer(overrides: Partial<ComponentProps<typeof ProgramDrawer>> = {}) {
  const props: ComponentProps<typeof ProgramDrawer> = {
    program,
    source,
    isFavorite: false,
    onToggleFavorite: vi.fn(),
    onClose: vi.fn(),
    ...overrides
  };
  return { ...render(<ProgramDrawer {...props} />), props };
}

describe('ProgramDrawer', () => {
  it('shows the complete decision-making context for a program', () => {
    renderDrawer();
    const dialog = screen.getByRole('dialog', { name: 'Старт-ИИ' });

    expect(within(dialog).getByText('Федеральная')).toBeInTheDocument();
    expect(within(dialog).getByText('Россия')).toBeInTheDocument();
    expect(within(dialog).getByText('1 июня 2026 — 28 февраля 2027')).toBeInTheDocument();
    expect(within(dialog).getByText('до 4 млн ₽')).toBeInTheDocument();
    expect(within(dialog).getByText('2024')).toBeInTheDocument();
    expect(within(dialog).getByText(/Полнота данных:/)).toHaveTextContent(`${program.dataQuality.score}%`);
    expect(within(dialog).getByText(source.trustNote)).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Открыть первоисточник' })).toHaveAttribute('href', program.sourceUrl);
  });

  it('renders calm missing-data and missing-source states', () => {
    renderDrawer({
      program: { ...program, deadline: null, fundingLabel: '', fundingAmountRub: null, fundingMinRub: null, fundingMaxRub: null },
      source: null
    });

    expect(screen.getByText('Источник не найден')).toBeInTheDocument();
    expect(screen.getByText('Срок не указан')).toBeInTheDocument();
    expect(screen.getByText('Сумма не указана')).toBeInTheDocument();
    expect(screen.getByText('Данные источника недоступны в текущей базе.')).toBeInTheDocument();
  });

  it('keeps favorite, Escape, focus trap, and opener restoration behavior', async () => {
    const user = userEvent.setup();
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    const onToggleFavorite = vi.fn();
    const onClose = vi.fn();
    const view = renderDrawer({ onToggleFavorite, onClose });

    const close = screen.getByRole('button', { name: 'Закрыть детали' });
    expect(close).toHaveFocus();
    const finalFocusableElement = screen.getByRole('link', { name: 'Документ 1' });
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(finalFocusableElement).toHaveFocus();
    await user.keyboard('{Tab}');
    expect(close).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Добавить Старт-ИИ в избранное' }));
    expect(onToggleFavorite).toHaveBeenCalledOnce();
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
    view.unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it('keeps fixed drawer actions for a long title and closes from its backdrop', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderDrawer({ program: { ...program, title: 'Очень длинное название программы, которое переносится на несколько строк' }, onClose });

    expect(screen.getByTestId('program-drawer-header')).toHaveClass('grid');
    expect(screen.getByTestId('program-drawer-overlay')).toHaveClass('program-drawer-overlay');
    expect(screen.getByRole('button', { name: 'Закрыть детали' })).toHaveClass('h-11', 'w-11');
    await user.click(screen.getByTestId('program-drawer-overlay'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('uses a translucent dedicated overlay class in dark theme', () => {
    expect(readFileSync('src/styles.css', 'utf8')).toContain(
      ":root[data-theme='dark'] .program-drawer-overlay { background-color: rgb(3 5 8 / .58); }"
    );
  });
});
