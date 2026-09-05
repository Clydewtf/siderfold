import { applicationStatus, type ApplicationStatusInput } from '../lib/applicationStatus';
import { Tag } from './ui';

const toneClassNames = {
  open: 'border-emerald-700/20 bg-emerald-50 text-emerald-900',
  closed: 'border-graphite/20 bg-graphite/10 text-graphite',
  completed: 'border-graphite/20 bg-graphite/10 text-graphite',
  upcoming: 'border-cobalt/20 bg-cobalt/10 text-cobalt',
  unknown: 'border-amber-700/20 bg-amber-50 text-amber-900'
} as const;

export function ApplicationStatusTag({ program }: { program: ApplicationStatusInput }) {
  const status = applicationStatus(program);
  return (
    <Tag className={toneClassNames[status.value]}>
      <span aria-hidden="true" className="mr-1">●</span>
      {status.label}
    </Tag>
  );
}
