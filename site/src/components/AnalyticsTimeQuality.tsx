import type { DataQualityAnalytics, TemporalAnalytics } from '../lib/analytics';
import { formatPercent } from '../lib/analyticsPresentation';
import { formatDeadline, formatMoneyRub } from '../lib/format';
import { AnalyticsBarList, AnalyticsMetric, AnalyticsTableShell } from './AnalyticsPrimitives';

const cardClassName = 'rounded-xl border border-ink/10 bg-white/80 p-5';

function formatDaysUntilDeadline(days: number): string {
  return days === 0 ? 'Дедлайн сегодня' : `До дедлайна: ${days} дн.`;
}

export function AnalyticsTimeQuality({
  temporal,
  dataQuality,
  filteredPrograms
}: {
  temporal: TemporalAnalytics;
  dataQuality: DataQualityAnalytics;
  filteredPrograms: number;
}) {
  const seasonalBars = temporal.byDeadlineMonth.map((item) => ({
    id: String(item.month),
    label: item.label,
    value: item.deadlineCount,
    displayValue: String(item.deadlineCount)
  }));
  const qualityBars = [
    {
      id: 'funding',
      label: 'Без суммы',
      value: dataQuality.missingFundingShare,
      displayValue: formatPercent(dataQuality.missingFundingShare)
    },
    {
      id: 'deadline',
      label: 'Без дедлайна',
      value: dataQuality.missingDeadlineShare,
      displayValue: formatPercent(dataQuality.missingDeadlineShare)
    },
    {
      id: 'region',
      label: 'Без региона',
      value: dataQuality.missingRegionShare,
      displayValue: formatPercent(dataQuality.missingRegionShare)
    },
    {
      id: 'updatedAt',
      label: 'Без даты обновления',
      value: dataQuality.missingUpdatedAtShare,
      displayValue: formatPercent(dataQuality.missingUpdatedAtShare)
    }
  ];

  return (
    <>
      <section aria-labelledby="analytics-time-title" className="mt-10">
        <h2 id="analytics-time-title" className="text-3xl font-semibold">Время и дедлайны</h2>

        <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-2">
          <article data-density-card className={cardClassName}>
            <h3 className="text-xl font-semibold">Ближайшие дедлайны</h3>
            {temporal.nearestDeadlines.length > 0 ? (
              <ul className="mt-4 grid gap-3">
                {temporal.nearestDeadlines.map((deadline) => (
                  <li key={deadline.programId} className="min-w-0">
                    <p className="break-words text-sm font-semibold">{deadline.title}</p>
                    <p className="mt-1 text-sm text-graphite">
                      {formatDeadline(deadline.deadline)} · {formatDaysUntilDeadline(deadline.daysUntilDeadline)}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-sm text-graphite">Нет ближайших дедлайнов</p>
            )}
          </article>

          <article data-density-card className={cardClassName}>
            <h3 className="text-xl font-semibold">Программы без дедлайна</h3>
            <p className="mt-4 text-sm text-graphite">Всего: {temporal.withoutDeadline.length}</p>
            {temporal.withoutDeadline.length > 0 ? (
              <ul className="mt-3 grid gap-2 text-sm">
                {temporal.withoutDeadline.slice(0, 10).map((program) => (
                  <li key={program.programId} className="break-words">{program.title}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-graphite">Все программы содержат дату дедлайна</p>
            )}
          </article>
        </div>

        <div data-density-grid className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-2">
          <article data-density-card className={cardClassName}>
            <h3 className="text-xl font-semibold">Сезонность дедлайнов</h3>
            <div className="mt-4">
              <AnalyticsBarList
                label="Сезонность дедлайнов"
                items={seasonalBars}
                emptyText="Сезонность дедлайнов недоступна"
              />
            </div>
          </article>

          <article data-density-card className={cardClassName}>
            <h3 className="text-xl font-semibold">Окна высокой активности</h3>
            {temporal.peakDeadlineMonths.length > 0 ? (
              <ul aria-label="Окна высокой активности" className="mt-4 flex flex-wrap gap-2">
                {temporal.peakDeadlineMonths.map((month) => (
                  <li key={month.month} className="rounded-full bg-cobalt/10 px-3 py-1 text-sm text-ink">
                    <span>{month.label}</span>
                    <span className="ml-2 font-semibold">{month.deadlineCount}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-sm text-graphite">Окна высокой активности не определены</p>
            )}
          </article>
        </div>

        <article data-density-card className={`${cardClassName} mt-6`}>
          <h3 className="text-xl font-semibold">Динамика по годам</h3>
          {temporal.byYear.length > 0 ? (
            <div className="mt-4">
              <AnalyticsTableShell label="Динамика по годам">
                <table className="min-w-[680px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr>
                      {['Год', 'Запущено', 'Активных', 'Объем поддержки'].map((label) => (
                        <th key={label} scope="col" className="border-b border-ink/10 px-3 py-3">{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {temporal.byYear.map((item) => (
                      <tr key={item.year}>
                        <th scope="row" className="border-b border-ink/10 px-3 py-3 font-semibold">{item.year}</th>
                        <td className="border-b border-ink/10 px-3 py-3">{item.launchedPrograms}</td>
                        <td className="border-b border-ink/10 px-3 py-3">{item.activePrograms}</td>
                        <td className="border-b border-ink/10 px-3 py-3">{formatMoneyRub(item.totalFundingRub)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </AnalyticsTableShell>
            </div>
          ) : (
            <p className="mt-4 text-sm text-graphite">Историческая динамика недоступна</p>
          )}
        </article>
      </section>

      <section aria-labelledby="analytics-quality-title" className="mt-10">
        <h2 id="analytics-quality-title" className="text-3xl font-semibold">Качество данных</h2>

        {filteredPrograms === 0 ? (
          <p className="mt-5 text-sm text-graphite">Нет записей для оценки качества</p>
        ) : (
          <>
            <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-2">
              <div>
                <h3 className="text-xl font-semibold">Полнота базы</h3>
                <div className="mt-4">
                  <AnalyticsMetric label="Индекс полноты" value={`${Math.round(dataQuality.completenessIndex)}%`} />
                </div>
              </div>

              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">Пробелы в полях</h3>
                <div className="mt-4">
                  <AnalyticsBarList label="Пробелы в полях" items={qualityBars} emptyText="Пробелы в полях не обнаружены" />
                </div>
              </article>
            </div>

            <article data-density-card className={`${cardClassName} mt-6`}>
              <h3 className="text-xl font-semibold">Качество по источникам</h3>
              <div className="mt-4">
                <AnalyticsTableShell label="Качество по источникам">
                  <table className="min-w-[620px] w-full border-collapse text-left text-sm">
                    <thead>
                      <tr>
                        {['Источник', 'Полнота данных', 'Неполных записей'].map((label) => (
                          <th key={label} scope="col" className="border-b border-ink/10 px-3 py-3">{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {dataQuality.bySource.map((source) => (
                        <tr key={source.sourceId}>
                          <th scope="row" className="border-b border-ink/10 px-3 py-3 font-semibold break-words">
                            {source.sourceName}
                          </th>
                          <td className="border-b border-ink/10 px-3 py-3">
                            {source.completenessIndex === null ? 'Нет наблюдений' : `${Math.round(source.completenessIndex)}%`}
                          </td>
                          <td className="border-b border-ink/10 px-3 py-3">{source.incompleteProgramCount}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </AnalyticsTableShell>
              </div>
            </article>
          </>
        )}
      </section>
    </>
  );
}
