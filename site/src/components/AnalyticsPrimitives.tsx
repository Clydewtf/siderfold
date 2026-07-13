import type { ReactNode } from 'react';

export function AnalyticsMetric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <article data-density-card className="min-w-0 rounded-xl border border-ink/10 bg-white/80 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-graphite">{label}</p>
      <p className="mt-2 break-words text-2xl font-semibold text-ink">{value}</p>
      {hint ? <p className="mt-2 text-xs leading-5 text-graphite">{hint}</p> : null}
    </article>
  );
}

export type AnalyticsBarItem = { id: string; label: string; value: number; displayValue: string };

export function AnalyticsBarList({ label, items, emptyText }: { label: string; items: readonly AnalyticsBarItem[]; emptyText: string }) {
  const maximum = Math.max(...items.map((item) => item.value), 1);
  if (items.length === 0) return <p className="text-sm text-graphite">{emptyText}</p>;

  return (
    <ul aria-label={label} className="grid gap-3">
      {items.map((item) => (
        <li key={item.id} className="min-w-0">
          <div className="flex min-w-0 items-start justify-between gap-3 text-sm">
            <span className="min-w-0 break-words">{item.label}</span>
            <span className="shrink-0 font-semibold">{item.displayValue}</span>
          </div>
          <div aria-hidden="true" className="mt-1 h-2 overflow-hidden rounded-full bg-ink/10">
            <div className="h-full rounded-full bg-cobalt" style={{ width: `${(item.value / maximum) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function AnalyticsTableShell({ label, children }: { label: string; children: ReactNode }) {
  return <div className="max-w-full overflow-x-auto" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}
