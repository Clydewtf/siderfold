import { expect, test, type Page } from '@playwright/test';

async function expectNoDocumentOverflow(page: Page) {
  await expect.poll(async () => page.evaluate(() => {
    return document.documentElement.scrollWidth - document.documentElement.clientWidth;
  })).toBeLessThanOrEqual(1);
}

test('catalog and source workflow persists favorites and recent views on desktop', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Desktop workflow coverage runs only in the desktop project.');
  await page.goto('/');

  await page.getByRole('tab', { name: 'Каталог' }).click();
  await page.getByLabel('Поиск').fill('ИИ');
  await expect(page.getByLabel('Сортировка')).toHaveValue('relevance');
  await page.getByLabel('Уровень программы').selectOption('federal');
  await page.getByLabel('Наличие суммы').selectOption('withFunding');
  await page.locator('article[aria-label="Старт-ИИ"]').scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: 'Добавить Старт-ИИ в избранное' }).click();
  await page.getByRole('button', { name: 'Подробнее о программе Старт-ИИ' }).click();
  await expect(page.getByRole('dialog', { name: 'Старт-ИИ' })).toContainText('Полнота данных');
  await page.getByRole('button', { name: 'Закрыть детали' }).click();

  await page.getByRole('tab', { name: 'Источники' }).click();
  await page.getByLabel('Уровень источника').selectOption('regional');
  await page.getByRole('button', { name: /(?:Выбрать источник|Смотреть программы) Impact Hub Moscow/ }).click();
  await page.getByRole('button', { name: 'Открыть программу Eco Impact Lab' }).first().click();
  await expect(page.getByRole('dialog', { name: 'Eco Impact Lab' })).toBeVisible();
  await page.getByRole('button', { name: 'Закрыть детали' }).click();

  await page.getByRole('tab', { name: 'Профиль' }).click();
  const favoriteProgramsSection = page
    .getByRole('heading', { name: 'Избранные программы' })
    .locator('xpath=ancestor::section[1]');
  const recentProgramsSection = page
    .getByRole('heading', { name: 'Недавно просмотренные' })
    .locator('xpath=ancestor::section[1]');
  await expect(favoriteProgramsSection.getByText('Старт-ИИ')).toBeVisible();
  await expect(recentProgramsSection.getByText('Eco Impact Lab')).toBeVisible();

  await page.reload();
  await page.getByRole('tab', { name: 'Профиль' }).click();
  await expect(favoriteProgramsSection.getByText('Старт-ИИ')).toBeVisible();
  await expect(recentProgramsSection.getByText('Eco Impact Lab')).toBeVisible();
});

test('five-section shell and local theme work on desktop', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop');
  await page.goto('/');
  await expect(page.getByRole('tab')).toHaveCount(5);
  await page.getByRole('tab', { name: 'Аналитика' }).click();
  await expect(page.getByRole('heading', { name: 'Аналитика мер поддержки' })).toBeVisible();
  await page.getByRole('tab', { name: 'Профиль' }).click();
  await page.getByLabel('Тема интерфейса').selectOption('dark');
  await page.reload();
  await page.getByRole('tab', { name: 'Профиль' }).click();
  await expect(page.getByLabel('Тема интерфейса')).toHaveValue('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('compact density visibly tightens cards across principal views', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Display preference coverage runs only on desktop.');
  await page.goto('/');

  const homeCard = page.getByText('Что внутри', { exact: true }).locator('..');
  await expect(homeCard).toHaveCSS('padding-top', '24px');

  await page.getByRole('tab', { name: 'Источники' }).click();
  await page.getByRole('button', {
    name: 'Добавить Фонд содействия инновациям в избранное'
  }).click();

  await page.getByRole('tab', { name: 'Профиль' }).click();
  await page.getByLabel('Плотность карточек').selectOption('compact');
  await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');

  const favoriteSourcesSection = page
    .getByRole('heading', { name: 'Избранные источники' })
    .locator('xpath=ancestor::section[1]');
  const profileCard = favoriteSourcesSection.getByRole('listitem');
  await expect(profileCard).toHaveCSS('padding-top', '12px');
  await expect(profileCard.locator('..')).toHaveCSS('row-gap', '12px');

  await page.getByRole('tab', { name: 'Главная' }).click();
  await expect(homeCard).toHaveCSS('padding-top', '12px');
  await expect(homeCard.locator('..')).toHaveCSS('row-gap', '12px');

  await page.getByRole('tab', { name: 'Каталог' }).click();
  const catalogCard = page.locator('article[aria-label="Старт-ИИ"]');
  await expect(catalogCard).toHaveCSS('padding-top', '12px');
  await expect(catalogCard.locator('..')).toHaveCSS('row-gap', '12px');

  await page.getByRole('tab', { name: 'Источники' }).click();
  const sourceCard = page.locator('article[aria-label="Impact Hub Moscow"]');
  await expect(sourceCard).toHaveCSS('padding-top', '12px');
  await expect(sourceCard.locator('..')).toHaveCSS('row-gap', '12px');
});

test('mobile layout has no horizontal scroll', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'Responsive overflow coverage runs only in the mobile project.');

  await page.goto('/');

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  await page.getByRole('tab', { name: 'Каталог' }).click();
  const overflowAfterCatalog = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflowAfterCatalog).toBeLessThanOrEqual(1);

  await page.getByText('Фильтры', { exact: true }).click();
  await page.getByLabel('Регион программы').selectOption('Москва');
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(1);

  await page.getByRole('button', { name: 'Подробнее о программе Eco Impact Lab' }).click();
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(1);
  await page.getByRole('button', { name: 'Закрыть детали' }).click();

  await page.getByRole('tab', { name: 'Аналитика' }).click();
  const overflowAfterAnalytics = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflowAfterAnalytics).toBeLessThanOrEqual(1);

  await page.getByText('Фильтры аналитики').click();
  await page.getByLabel('Регион аналитики').selectOption('Москва');
  for (const name of ['Регионы', 'Качество по источникам']) {
    await page.getByRole('heading', { name, exact: true }).scrollIntoViewIfNeeded();
    await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  }
  await page.getByRole('button', { name: 'Экспорт отчета' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Экспорт отчета и CSV' })).toBeVisible();
  await page.getByRole('button', { name: 'Экспорт CSV' }).click();
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);

  await page.getByRole('tab', { name: 'Источники' }).click();
  await page.getByLabel('Тип источника').selectOption('Акселератор');
  await expect(page.getByRole('heading', { name: 'Impact Hub Moscow' })).toBeVisible();
  await expect(page.getByText('Eco Impact Lab').first()).toBeVisible();
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
    .toBeLessThanOrEqual(1);

  await page.getByRole('tab', { name: 'Профиль' }).click();
  const overflowAfterProfile = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflowAfterProfile).toBeLessThanOrEqual(1);
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

test('analytics BI filter rebuilds monitoring and reset restores the database', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Analytics BI workflow runs only on desktop.');
  await page.goto('/');
  await page.getByRole('tab', { name: 'Аналитика' }).click();

  const status = page.getByRole('status').filter({ hasText: 'Найдено программ:' });
  await expect(status).toContainText('Найдено программ: 30');
  const initialFinance = await page.getByText('Общий объем', { exact: true }).locator('..').textContent();

  await page.getByLabel('Регион аналитики').selectOption('Москва');
  await expect(status).not.toContainText('Найдено программ: 30');
  await expect(page.getByText('Регион: Москва')).toBeVisible();
  const filteredFinance = await page.getByText('Общий объем', { exact: true }).locator('..').textContent();
  expect(filteredFinance).not.toBe(initialFinance);

  await page.getByRole('button', { name: 'Сбросить BI-фильтры' }).click();
  await expect(status).toContainText('Найдено программ: 30');
  await expect(page.getByText('Регион: Москва')).not.toBeVisible();
});

test('every primary screen and program drawer stays inside the viewport', async ({ page }) => {
  await page.goto('/');
  for (const tab of ['Главная', 'Каталог', 'Аналитика', 'Источники', 'Профиль']) {
    await page.getByRole('tab', { name: tab }).click();
    await expectNoDocumentOverflow(page);
  }

  await page.getByRole('tab', { name: 'Каталог' }).click();
  await page.locator('article[aria-label="Старт-ИИ"]').scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: 'Подробнее о программе Старт-ИИ' }).click();
  await expect(page.getByRole('dialog', { name: 'Старт-ИИ' })).toBeVisible();
  await expectNoDocumentOverflow(page);
  await page.getByRole('button', { name: 'Закрыть детали' }).click();

  await page.getByRole('tab', { name: 'Профиль' }).click();
  await page.getByRole('button', { name: 'Предпочитать регион Москва' }).scrollIntoViewIfNeeded();
  await expectNoDocumentOverflow(page);
});

test('primary Siderfold journey connects catalog profile theme analytics and sources', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The complete product journey runs once on desktop.');
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Программы поддержки');

  await page.getByRole('tab', { name: 'Каталог' }).click();
  await page.getByLabel('Поиск').fill('Старт-ИИ');
  await page.locator('article[aria-label="Старт-ИИ"]').scrollIntoViewIfNeeded();
  await expect(page.getByRole('heading', { name: 'Старт-ИИ' })).toBeVisible();
  await page.getByRole('button', { name: 'Добавить Старт-ИИ в избранное' }).click();
  await page.getByRole('button', { name: 'Подробнее о программе Старт-ИИ' }).click();
  await expect(page.getByRole('dialog', { name: 'Старт-ИИ' })).toContainText('Фонд содействия инновациям');
  await page.getByRole('button', { name: 'Закрыть детали' }).click();

  await page.getByRole('tab', { name: 'Профиль' }).click();
  const favorites = page.getByRole('heading', { name: 'Избранные программы' }).locator('xpath=ancestor::section[1]');
  await expect(favorites.getByText('Старт-ИИ')).toBeVisible();
  await page.getByLabel('Тема интерфейса').selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  await page.reload();
  await page.getByRole('tab', { name: 'Профиль' }).click();
  await expect(favorites.getByText('Старт-ИИ')).toBeVisible();
  await expect(page.getByLabel('Тема интерфейса')).toHaveValue('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  await page.getByRole('tab', { name: 'Аналитика' }).click();
  const resultStatus = page.getByRole('status').filter({ hasText: 'Найдено программ:' });
  await expect(resultStatus).toContainText('Найдено программ: 30');
  await page.getByLabel('Регион аналитики').selectOption('Москва');
  await expect(resultStatus).not.toContainText('Найдено программ: 30');
  await expect(page.getByText('Регион: Москва')).toBeVisible();

  await page.getByRole('tab', { name: 'Источники' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Источники программ' })).toBeVisible();
  await expectNoDocumentOverflow(page);
});

test('keyboard users can skip to content navigate tabs close the drawer and hear demo status', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Keyboard smoke runs once on desktop.');
  await page.goto('/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Перейти к содержимому' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('main')).toBeFocused();

  await page.getByRole('tab', { name: 'Главная' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Каталог' })).toHaveAttribute('aria-selected', 'true');
  await page.locator('article[aria-label="Старт-ИИ"]').scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: 'Подробнее о программе Старт-ИИ' }).click();
  await expect(page.getByRole('button', { name: 'Закрыть детали' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Старт-ИИ' })).toHaveCount(0);

  await page.getByRole('tab', { name: 'Профиль' }).click();
  await page.getByRole('button', { name: 'Открыть данные профиля' }).click();
  await expect(page.getByRole('status')).toContainText('после подключения аккаунта');
});
