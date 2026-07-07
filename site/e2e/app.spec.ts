import { expect, test } from '@playwright/test';

test('tabs, search, filters, and drawer work on desktop', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Desktop workflow coverage runs only in the desktop project.');

  await page.goto('/');

  await expect(page.getByRole('heading', { name: /Единая база программ поддержки/i })).toBeVisible();

  await page.getByRole('tab', { name: 'Источники' }).click();
  await expect(page.getByRole('heading', { name: 'Источники программ' })).toBeVisible();
  await page.getByLabel('Тип источника').selectOption('Акселератор');
  await expect(page.getByRole('article', { name: 'Impact Hub Moscow' })).toBeVisible();

  await page.getByRole('tab', { name: 'Каталог' }).click();
  await page.getByLabel('Поиск').fill('ИИ');
  await expect(page.getByRole('heading', { name: 'Старт-ИИ' })).toBeVisible();
  await page.getByLabel('Тип поддержки').selectOption('Акселерация');
  await expect(page.getByRole('heading', { name: 'Индустриальный ИИ акселератор' })).toBeVisible();

  await page.getByRole('button', { name: /Подробнее о программе Индустриальный ИИ акселератор/i }).click();
  await expect(page.getByRole('dialog', { name: 'Индустриальный ИИ акселератор' })).toBeVisible();
  await page.getByRole('button', { name: 'Закрыть детали' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('mobile layout has no horizontal scroll', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'Responsive overflow coverage runs only in the mobile project.');

  await page.goto('/');

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  await page.getByRole('tab', { name: 'Каталог' }).click();
  const overflowAfterCatalog = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflowAfterCatalog).toBeLessThanOrEqual(1);
});

test('mobile catalog keeps search and active filters visible while filters are collapsed', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'Mobile workflow coverage runs only in the mobile project.');

  await page.goto('/');
  await page.getByRole('tab', { name: 'Каталог' }).click();
  await page.getByLabel('Поиск').fill('ИИ');

  await expect(page.getByText('Поиск: ИИ')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сбросить фильтры' })).toBeVisible();
  await expect(page.getByText('Фильтры', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Тип поддержки')).not.toBeVisible();
});

test('desktop source detail remains available after selecting a source', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Desktop workflow coverage runs only in the desktop project.');

  await page.goto('/');
  await page.getByRole('tab', { name: 'Источники' }).click();
  const impactHubCard = page.locator('article[aria-label="Impact Hub Moscow"]');
  await impactHubCard.scrollIntoViewIfNeeded();
  await impactHubCard.getByRole('button', { name: /Выбрать источник Impact Hub Moscow/i }).click();

  await expect(page.getByText('Выбран источник: Impact Hub Moscow')).toBeAttached();
  await expect(page.getByRole('heading', { name: 'Impact Hub Moscow' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Открыть сайт источника' })).toBeVisible();
});
