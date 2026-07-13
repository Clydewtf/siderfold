import type { FinancialAnalytics, MoneyDistributionItem, RegionalAnalytics } from '../lib/analytics';
import { formatMoneyRub } from '../lib/format';
import { AnalyticsBarList, AnalyticsMetric, AnalyticsTableShell } from './AnalyticsPrimitives';

const cardClassName = 'rounded-xl border border-ink/10 bg-white/80 p-5';

function toBarItems(items: readonly MoneyDistributionItem[]) {
  return items.map((item) => ({
    id: item.id,
    label: item.label,
    value: item.totalFundingRub,
    displayValue: formatMoneyRub(item.totalFundingRub)
  }));
}

export function AnalyticsFinanceRegions({
  finance,
  regional
}: {
  finance: FinancialAnalytics;
  regional: RegionalAnalytics;
}) {
  const financialSections = [
    {
      heading: 'Финансирование по типам поддержки',
      label: 'Финансирование по типам поддержки',
      items: toBarItems(finance.bySupportType)
    },
    {
      heading: 'Финансирование по источникам',
      label: 'Финансирование по источникам',
      items: toBarItems(finance.bySource)
    },
    {
      heading: 'Финансирование по регионам',
      label: 'Финансирование по регионам',
      items: toBarItems(finance.byRegion)
    },
    {
      heading: 'Федеральные и региональные объемы',
      label: 'Федеральные и региональные объемы',
      items: toBarItems(finance.byCoverageLevel)
    }
  ];

  return (
    <section aria-labelledby="analytics-finance-title" className="mt-10">
      <h2 id="analytics-finance-title" className="text-3xl font-semibold">Финансы</h2>

      {finance.bySupportType.length > 0 ? (
        <>
          <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <AnalyticsMetric label="Общий объем" value={formatMoneyRub(finance.totalFundingRub)} />
            <AnalyticsMetric label="Средняя сумма" value={formatMoneyRub(finance.averageFundingRub)} />
            <AnalyticsMetric label="Медианная сумма" value={formatMoneyRub(finance.medianFundingRub)} />
            <AnalyticsMetric label="Максимальная сумма" value={formatMoneyRub(finance.maxFundingRub)} />
          </div>

          <div data-density-grid className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            {financialSections.map((section) => (
              <article key={section.heading} data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">{section.heading}</h3>
                <div className="mt-4">
                  <AnalyticsBarList
                    label={section.label}
                    items={section.items}
                    emptyText="В выбранном срезе нет финансовых данных"
                  />
                </div>
              </article>
            ))}
          </div>
        </>
      ) : (
        <p className="mt-5 text-sm text-graphite">В выбранном срезе нет финансовых данных</p>
      )}

      <h2 className="mt-10 text-3xl font-semibold">Регионы</h2>
      {regional.regions.length > 0 ? (
        <>
          <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <article data-density-card className={cardClassName}>
              <h3 className="text-xl font-semibold">Высокая концентрация</h3>
              <ul className="mt-4 grid grid-cols-1 gap-2 text-sm">
                {regional.highCoverageRegions.map((item) => (
                  <li key={item.region} className="break-words">
                    {item.region} — индекс покрытия {item.coverageScore}
                  </li>
                ))}
              </ul>
            </article>

            <article data-density-card className={cardClassName}>
              <h3 className="text-xl font-semibold">Низкое покрытие</h3>
              <ul className="mt-4 grid grid-cols-1 gap-2 text-sm">
                {regional.lowCoverageRegions.map((item) => (
                  <li key={item.region} className="break-words">
                    {item.region} — индекс покрытия {item.coverageScore}
                  </li>
                ))}
              </ul>
            </article>
          </div>

          <div className="mt-6">
            <AnalyticsTableShell label="Региональная аналитика">
              <table className="min-w-[760px] w-full border-collapse text-left text-sm">
                <thead>
                  <tr>
                    {['Регион', 'Программ', 'Активных', 'Объем', 'Средняя', 'Индекс покрытия'].map((label) => (
                      <th key={label} scope="col" className="border-b border-ink/10 px-3 py-3">{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {regional.regions.map((item) => (
                    <tr key={item.region}>
                      <th scope="row" className="border-b border-ink/10 px-3 py-3 font-semibold">{item.region}</th>
                      <td className="border-b border-ink/10 px-3 py-3">{item.programCount}</td>
                      <td className="border-b border-ink/10 px-3 py-3">{item.activeProgramCount}</td>
                      <td className="border-b border-ink/10 px-3 py-3">{formatMoneyRub(item.totalFundingRub)}</td>
                      <td className="border-b border-ink/10 px-3 py-3">{formatMoneyRub(item.averageFundingRub)}</td>
                      <td className="border-b border-ink/10 px-3 py-3">{item.coverageScore}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </AnalyticsTableShell>
          </div>
        </>
      ) : (
        <p className="mt-5 text-sm text-graphite">Региональные данные отсутствуют</p>
      )}
    </section>
  );
}
