import assert from 'node:assert/strict';
import test from 'node:test';
import { selectWebstorageFlag } from './select-webstorage-flag.mjs';

test('prefers the current webstorage disable flag when supported', () => {
  const flags = new Set(['--no-webstorage', '--no-experimental-webstorage']);
  assert.equal(selectWebstorageFlag(flags), '--no-webstorage');
});

test('uses the predecessor flag when the current flag is unsupported', () => {
  const flags = new Set(['--no-experimental-webstorage']);
  assert.equal(selectWebstorageFlag(flags), '--no-experimental-webstorage');
});

test('omits a webstorage flag when neither form is supported', () => {
  assert.equal(selectWebstorageFlag(new Set()), undefined);
});
