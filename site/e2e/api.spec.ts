import { expect, test, type Page, type Route } from '@playwright/test';

const source = {
  id: 'source-1',
  name: 'Фонд развития проектов',
  canonical_url: 'https://example.org'
};

const sourceLink = {
  source,
  source_url: 'https://example.org/programs/green-project',
  observed_at: '2025-02-14T10:30:00Z'
};

const listItem = {
  id: 'program-1',
  title: 'Зелёный проект',
  publication_status: 'published',
  published_at: '2025-02-10T09:00:00Z',
  updated_at: '2025-02-14T10:30:00Z',
  deadline_on: '2025-06-30',
  funding: {
    value_kind: 'range',
    currency_code: 'RUB',
    exact_amount: null,
    min_amount: '100000',
    max_amount: '500000'
  },
  primary_source: sourceLink
};

const detail = {
  ...listItem,
  sources: [sourceLink],
  geographies: [{ slug: 'russia', name: 'Россия' }],
  themes: [{ slug: 'ecology', name: 'Экология' }]
};

function page<T>(items: T[], total = items.length) {
  return { items, page: 1, page_size: 20, total };
}

async function mockPublicApi(pageView: Page, mode: 'normal' | 'empty' | 'error' = 'normal') {
  const requests: string[] = [];
  await pageView.route('**/api/v1/**', async (route: Route) => {
    const url = new URL(route.request().url());
    requests.push(url.toString());

    if (url.pathname === '/api/v1/programs') {
      if (mode === 'error') {
        await route.fulfill({ status: 503, contentType: 'application/json', json: { code: 'database_unavailable', message: 'database is offline' } });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: mode === 'empty' ? page([]) : page([listItem])
      });
      return;
    }

    if (url.pathname === '/api/v1/programs/program-1') {
      await route.fulfill({ status: 200, contentType: 'application/json', json: detail });
      return;
    }

    if (url.pathname === '/api/v1/sources') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: mode === 'empty' ? page([]) : page([{ ...source, published_program_count: 1 }])
      });
      return;
    }

    if (url.pathname === '/api/v1/filters') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: mode === 'empty'
          ? { sources: [], geographies: [], themes: [], funding_kinds: [], deadline: { min_deadline: null, max_deadline: null } }
          : {
              sources: [source],
              geographies: [{ slug: 'russia', name: 'Россия' }],
              themes: [{ slug: 'ecology', name: 'Экология' }],
              funding_kinds: ['range', 'unknown'],
              deadline: { min_deadline: '2025-06-30', max_deadline: '2025-06-30' }
            }
      });
      return;
    }

    await route.fulfill({ status: 404, contentType: 'application/json', json: { code: 'not_found' } });
  });

  return requests;
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
});

test('API mode loads a published catalog item, filters it, and opens its public detail', async ({ page }) => {
  const requests = await mockPublicApi(page);
  await page.goto('/');

  await expect(page.getByText('API-режим')).toBeVisible();
  await page.getByRole('tab', { name: 'Каталог' }).click();
  await expect(page.getByRole('heading', { name: 'Зелёный проект' })).toBeVisible();
  await expect(page.locator('article[aria-label="Зелёный проект"]').getByText('Фонд развития проектов')).toBeVisible();

  await page.getByRole('combobox', { name: 'Источник', exact: true }).selectOption('source-1');
  await expect.poll(() => requests.some((request) => request.includes('source_id=source-1'))).toBe(true);

  await page.getByRole('button', { name: 'Подробнее о программе Зелёный проект' }).click();
  const dialog = page.getByRole('dialog', { name: 'Зелёный проект' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Экология');
  await expect(dialog).toContainText('Россия');
  await expect(dialog.getByRole('link', { name: 'Открыть первоисточник' })).toHaveAttribute(
    'href',
    'https://example.org/programs/green-project'
  );
  await expect(dialog).not.toContainText('RawCapture');
  await expect(dialog).not.toContainText('ReviewDecision');
});

test('API mode shows an explicit empty state for an empty database', async ({ page }) => {
  await mockPublicApi(page, 'empty');
  await page.goto('/');
  await page.getByRole('tab', { name: 'Каталог' }).click();

  await expect(page.getByText('Каталог пока пуст', { exact: true })).toBeVisible();
  await expect(page.getByText('Зелёный проект')).not.toBeVisible();
  await expect(page.getByText('Демо-режим')).not.toBeVisible();
});

test('API mode shows a safe error and never falls back to seed data', async ({ page }) => {
  await mockPublicApi(page, 'error');
  await page.goto('/');
  await page.getByRole('tab', { name: 'Каталог' }).click();

  await expect(page.getByText('Каталог временно недоступен', { exact: true })).toBeVisible();
  await expect(page.getByText('Не удалось загрузить каталог. Попробуйте ещё раз.')).toBeVisible();
  await expect(page.getByText('database_unavailable')).not.toBeVisible();
  await expect(page.getByText('Старт-ИИ')).not.toBeVisible();
});
