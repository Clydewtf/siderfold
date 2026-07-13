import type { SourceAnalytics, TopicAnalytics } from '../lib/analytics';
import { formatPercent } from '../lib/analyticsPresentation';
import { formatCoverageLevel, formatMoneyRub } from '../lib/format';
import { AnalyticsBarList, AnalyticsTableShell } from './AnalyticsPrimitives';

const cardClassName = 'rounded-xl border border-ink/10 bg-white/80 p-5';

export function AnalyticsSourcesTopics({
  sources,
  topics,
  totalPrograms
}: {
  sources: SourceAnalytics;
  topics: TopicAnalytics;
  totalPrograms: number;
}) {
  const programRanking = sources.byProgramCount.map((item) => ({
    id: item.sourceId,
    label: item.sourceName,
    value: item.programCount,
    displayValue: String(item.programCount)
  }));
  const activeRanking = sources.byActiveProgramCount.map((item) => ({
    id: item.sourceId,
    label: item.sourceName,
    value: item.activeProgramCount,
    displayValue: String(item.activeProgramCount)
  }));
  const fundingRanking = sources.byFunding.map((item) => ({
    id: item.sourceId,
    label: item.sourceName,
    value: item.totalFundingRub,
    displayValue: formatMoneyRub(item.totalFundingRub)
  }));
  const topicCounts = topics.topics.map((item) => ({
    id: item.topic,
    label: item.topic,
    value: item.programCount,
    displayValue: String(item.programCount)
  }));
  const topicFunding = topics.topics.map((item) => ({
    id: item.topic,
    label: item.topic,
    value: item.totalFundingRub,
    displayValue: formatMoneyRub(item.totalFundingRub)
  }));
  const sourceContribution = (programCount: number) =>
    formatPercent(totalPrograms === 0 ? 0 : programCount / totalPrograms);

  return (
    <>
      <section aria-labelledby="analytics-sources-title" className="mt-10">
        <h2 id="analytics-sources-title" className="text-3xl font-semibold">Источники</h2>

        {totalPrograms === 0 ? (
          <p className="mt-5 text-sm text-graphite">Источники в выбранном срезе отсутствуют</p>
        ) : (
          <>
            <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-3">
              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">По числу программ</h3>
                <div className="mt-4">
                  <AnalyticsBarList
                    label="По числу программ"
                    items={programRanking}
                    emptyText="Источники в выбранном срезе отсутствуют"
                  />
                </div>
              </article>

              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">По активным программам</h3>
                <div className="mt-4">
                  <AnalyticsBarList
                    label="По активным программам"
                    items={activeRanking}
                    emptyText="Источники в выбранном срезе отсутствуют"
                  />
                </div>
              </article>

              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">По объему поддержки</h3>
                <div className="mt-4">
                  <AnalyticsBarList
                    label="По объему поддержки"
                    items={fundingRanking}
                    emptyText="Источники в выбранном срезе отсутствуют"
                  />
                </div>
              </article>
            </div>

            <article data-density-card className={`${cardClassName} mt-6`}>
              <h3 className="text-xl font-semibold">Качество данных источников</h3>
              <div className="mt-4">
                <AnalyticsTableShell label="Качество данных источников">
                  <table className="min-w-[960px] w-full border-collapse text-left text-sm">
                    <thead>
                      <tr>
                        {[
                          'Источник',
                          'Тип',
                          'Уровень',
                          'Программ',
                          'Вклад в базу',
                          'Активных',
                          'Полнота данных',
                          'Неполных записей'
                        ].map((label) => (
                          <th key={label} scope="col" className="border-b border-ink/10 px-3 py-3">{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sources.byDataQuality.map((item) => (
                        <tr key={item.sourceId}>
                          <th scope="row" className="border-b border-ink/10 px-3 py-3 font-semibold break-words">
                            {item.sourceName}
                          </th>
                          <td className="border-b border-ink/10 px-3 py-3 break-words">{item.sourceType}</td>
                          <td className="border-b border-ink/10 px-3 py-3 break-words">{formatCoverageLevel(item.coverageLevel)}</td>
                          <td className="border-b border-ink/10 px-3 py-3">{item.programCount}</td>
                          <td className="border-b border-ink/10 px-3 py-3">{sourceContribution(item.programCount)}</td>
                          <td className="border-b border-ink/10 px-3 py-3">{item.activeProgramCount}</td>
                          <td className="border-b border-ink/10 px-3 py-3">
                            {item.dataCompletenessScore === null ? 'Нет наблюдений' : `${Math.round(item.dataCompletenessScore)}%`}
                          </td>
                          <td className="border-b border-ink/10 px-3 py-3">{item.incompleteProgramCount}</td>
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

      <section aria-labelledby="analytics-topics-title" className="mt-10">
        <h2 id="analytics-topics-title" className="text-3xl font-semibold">Тематики</h2>

        {totalPrograms === 0 ? (
          <p className="mt-5 text-sm text-graphite">Тематики в выбранном срезе отсутствуют</p>
        ) : (
          <>
            <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">Распределение программ</h3>
                <div className="mt-4">
                  <AnalyticsBarList
                    label="Распределение программ"
                    items={topicCounts}
                    emptyText="Тематики в выбранном срезе отсутствуют"
                  />
                </div>
              </article>

              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">Объем поддержки по тематикам</h3>
                <div className="mt-4">
                  <AnalyticsBarList
                    label="Объем поддержки по тематикам"
                    items={topicFunding}
                    emptyText="Тематики в выбранном срезе отсутствуют"
                  />
                </div>
              </article>
            </div>

            <div data-density-grid className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">Сильные тематики</h3>
                <ul className="mt-4 grid grid-cols-1 gap-2 text-sm">
                  {topics.strongTopics.map((item) => (
                    <li key={item.topic} className="break-words">
                      {item.topic} — {item.programCount} программ, {formatMoneyRub(item.totalFundingRub)}
                    </li>
                  ))}
                </ul>
              </article>

              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">Слабое покрытие тематик</h3>
                <ul className="mt-4 grid grid-cols-1 gap-2 text-sm">
                  {topics.weakTopics.map((item) => (
                    <li key={item.topic} className="break-words">
                      {item.topic} — {item.programCount} программ, {formatMoneyRub(item.totalFundingRub)}
                    </li>
                  ))}
                </ul>
              </article>
            </div>

            <article data-density-card className={`${cardClassName} mt-6`}>
              <h3 className="text-xl font-semibold">Пересечения тематики и региона</h3>
              <div className="mt-4">
                <AnalyticsTableShell label="Пересечения тематики и региона">
                  <table className="min-w-[640px] w-full border-collapse text-left text-sm">
                    <thead>
                      <tr>
                        {['Тематика', 'Регион', 'Программ', 'Объем'].map((label) => (
                          <th key={label} scope="col" className="border-b border-ink/10 px-3 py-3">{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {topics.intersections.slice(0, 12).map((item) => (
                        <tr key={`${item.topic}:${item.region}`}>
                          <th scope="row" className="border-b border-ink/10 px-3 py-3 font-semibold break-words">
                            {item.topic}
                          </th>
                          <td className="border-b border-ink/10 px-3 py-3 break-words">{item.region}</td>
                          <td className="border-b border-ink/10 px-3 py-3">{item.programCount}</td>
                          <td className="border-b border-ink/10 px-3 py-3">{formatMoneyRub(item.totalFundingRub)}</td>
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
