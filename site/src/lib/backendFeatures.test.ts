import { describe, expect, it } from 'vitest';
import type { BackendFeature } from '../types';
import { BACKEND_CAPABILITIES, getBackendCapability } from './backendFeatures';

const expected: readonly BackendFeature[] = [
  'signIn', 'registration', 'accountData', 'notifications',
  'documents', 'applications', 'reportExport', 'profileSync'
];

describe('backend capability registry', () => {
  it('defines one calm, actionable entry for every backend feature', () => {
    expect(BACKEND_CAPABILITIES.map((item) => item.feature)).toEqual(expected);
    for (const feature of expected) {
      const item = getBackendCapability(feature);
      expect(item.title).not.toHaveLength(0);
      expect(item.description).toMatch(/Демо-режим|аккаунт|backend/i);
      expect(item.notice).toMatch(/будет доступ|появится|после подключения/i);
      expect(item.notice).not.toMatch(/ошиб|сбой|не удалось/i);
    }
  });

  it('keeps report export on analytics and account capabilities on profile', () => {
    expect(getBackendCapability('reportExport').surface).toBe('analytics');
    expect(BACKEND_CAPABILITIES.filter((item) => item.surface === 'profile')).toHaveLength(7);
  });
});
