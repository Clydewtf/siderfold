import { spawnSync } from 'node:child_process';
import { selectWebstorageFlag } from './select-webstorage-flag.mjs';

const nodeOptions = [process.env.NODE_OPTIONS, selectWebstorageFlag()].filter(Boolean).join(' ');
const result = spawnSync(
  process.execPath,
  ['./node_modules/vitest/vitest.mjs', 'run', ...process.argv.slice(2)],
  {
    env: { ...process.env, NODE_OPTIONS: nodeOptions },
    stdio: 'inherit'
  }
);

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
