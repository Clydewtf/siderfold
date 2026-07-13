import type { ForecastAnalytics, SupportGap, SupportGapsAnalytics } from '../lib/analytics';
import { confidenceLabel, formatPercent, severityLabel } from '../lib/analyticsPresentation';
import { formatMoneyRub } from '../lib/format';
import { AnalyticsMetric } from './AnalyticsPrimitives';

const cardClassName = 'rounded-xl border border-ink/10 bg-white/80 p-5';

function GapList({ gaps }: { gaps: readonly SupportGap[] }) {
  if (gaps.length === 0) {
    return <p className="mt-4 text-sm text-graphite">В выбранном срезе нет данных для оценки пробелов</p>;
  }

  return (
    <ul className="mt-4 grid gap-4 text-sm">
      {gaps.map((gap) => (
        <li key={gap.id} className="min-w-0">
          <p className="break-words font-semibold">{gap.label}</p>
          <p className="mt-1 break-words text-graphite">{gap.reason}</p>
          <p className="mt-2 break-words text-graphite">
            {severityLabel(gap.severity)} · {gap.programCount} программ · {formatMoneyRub(gap.totalFundingRub)}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function AnalyticsGapsForecast({
  supportGaps,
  forecast,
  exportNotice,
  onRequestExport
}: {
  supportGaps: SupportGapsAnalytics;
  forecast: ForecastAnalytics;
  exportNotice: string | null;
  onRequestExport: () => void;
}) {
  const forecastAvailable = forecast.expectedFundingRub !== null || forecast.expectedProgramCount !== null;

  return (
    <>
      <section aria-labelledby="analytics-gaps-title" className="mt-10">
        <h2 id="analytics-gaps-title" className="text-3xl font-semibold">Пробелы поддержки</h2>
        <p className="mt-2 text-sm text-graphite">Выводы рассчитаны по текущей seed-базе и не описывают весь рынок.</p>

        <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <article data-density-card className={cardClassName}>
            <h3 className="text-xl font-semibold">Регионы с низким покрытием</h3>
            <GapList gaps={supportGaps.weakRegions} />
          </article>

          <article data-density-card className={cardClassName}>
            <h3 className="text-xl font-semibold">Тематики с низким покрытием</h3>
            <GapList gaps={supportGaps.weakTopics} />
          </article>

          <article data-density-card className={cardClassName}>
            <h3 className="text-xl font-semibold">Слабые сочетания региона и тематики</h3>
            <GapList gaps={supportGaps.weakRegionTopicPairs} />
          </article>
        </div>
      </section>

      <section aria-labelledby="analytics-forecast-title" className="mt-10">
        <h2 id="analytics-forecast-title" className="text-3xl font-semibold">Демо-прогноз по историческим seed-данным</h2>
        <p className="rounded-lg bg-cobalt/10 p-4 text-sm text-cobalt">Демо-прогноз по историческим seed-данным. После подключения backend модель будет пересчитываться по полной базе.</p>

        {forecastAvailable ? (
          <>
            <div data-density-grid className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <AnalyticsMetric
                label={`Ожидаемое финансирование на ${forecast.nextYear}`}
                value={formatMoneyRub(forecast.expectedFundingRub)}
              />
              <AnalyticsMetric
                label={`Ожидаемое число программ на ${forecast.nextYear}`}
                value={forecast.expectedProgramCount ?? 'Нет данных'}
              />
              <AnalyticsMetric
                label="Изменение числа программ"
                value={forecast.expectedProgramCountChange ?? 'Нет данных'}
              />
            </div>

            <div data-density-grid className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">Растущие тематики</h3>
                {forecast.growingTopics.length > 0 ? (
                  <ul className="mt-4 grid gap-2 text-sm">
                    {forecast.growingTopics.map((topic) => (
                      <li key={topic.topic} className="break-words">
                        {topic.topic} — рост {formatPercent(topic.growthRate)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-graphite">Растущие тематики не определены</p>
                )}
              </article>

              <article data-density-card className={cardClassName}>
                <h3 className="text-xl font-semibold">Метод расчета</h3>
                <p className="mt-4 text-sm text-graphite">Уверенность: {confidenceLabel(forecast.confidence)} ({forecast.confidenceScore}%)</p>
                <p className="mt-3 text-sm leading-6 text-graphite">{forecast.method}</p>
              </article>
            </div>
          </>
        ) : (
          <p className="mt-5 text-sm text-graphite">Недостаточно данных для demo-прогноза</p>
        )}

        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onRequestExport}
            className="inline-flex min-h-11 items-center justify-center rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-ink/85 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
          >
            Экспорт отчета
          </button>
          <button
            type="button"
            onClick={onRequestExport}
            className="inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/10 bg-white px-4 py-2 text-sm font-semibold text-graphite hover:bg-ink/5 focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2"
          >
            Экспорт CSV
          </button>
        </div>
        {exportNotice ? <p role="status" aria-live="polite" className="mt-3 rounded-lg bg-cobalt/10 p-4 text-sm text-cobalt">{exportNotice}</p> : null}
      </section>
    </>
  );
}
