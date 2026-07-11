import type { ButtonHTMLAttributes, ReactNode } from 'react';

type VisibleButtonChildren = Exclude<ReactNode, boolean | null | undefined>;

export function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-ink/10 bg-white/55 px-3 py-1 text-xs font-medium text-graphite">
      {children}
    </span>
  );
}

export function MetricTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div data-density-card className="rounded-lg border border-ink/10 bg-white/70 p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-[0.12em] text-graphite/65">{label}</p>
      <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
      {hint ? <p className="mt-1 text-sm text-graphite/70">{hint}</p> : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  children
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-ink/20 bg-white/45 p-8 text-center">
      <p className="text-lg font-semibold text-ink">{title}</p>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-graphite/75">{description}</p>
      {children ? <div className="mt-5 flex flex-wrap justify-center gap-3">{children}</div> : null}
    </div>
  );
}

type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'aria-label'> &
  (
    | {
        children: VisibleButtonChildren;
        'aria-label'?: string;
      }
    | {
        children?: never;
        'aria-label': string;
      }
  );

export function IconButton({
  children,
  className = '',
  ...props
}: IconButtonProps) {
  return (
    <button
      className={`inline-flex min-h-11 items-center justify-center rounded-lg border border-ink/10 bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-graphite focus:outline-none focus:ring-2 focus:ring-cobalt focus:ring-offset-2 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
