import { describe, expect, it } from 'vitest';
import { programs, sources } from '../data/seed';
import { DEFAULT_PERSISTED_APP_STATE } from './storage';
import { buildProfileViewModel } from './profile';

describe('buildProfileViewModel', () => {
  it('preserves stored entity order and ignores stale ids', () => {
    const result = buildProfileViewModel({
      ...DEFAULT_PERSISTED_APP_STATE,
      favoriteProgramIds: ['fasie-start-ai', 'missing-program'],
      favoriteSourceIds: ['fasie', 'missing-source'],
      recentProgramIds: ['impact-hub-eco-impact', 'fasie-start-ai', 'impact-hub-eco-impact']
    }, programs, sources);

    expect(result.favoritePrograms.map((item) => item.id)).toEqual(['fasie-start-ai']);
    expect(result.favoriteSources.map((item) => item.id)).toEqual(['fasie']);
    expect(result.recentPrograms.map((item) => item.id)).toEqual([
      'impact-hub-eco-impact',
      'fasie-start-ai'
    ]);
  });

  it('builds sorted real region and topic preference options', () => {
    const result = buildProfileViewModel(DEFAULT_PERSISTED_APP_STATE, programs, sources);
    expect(result.regionOptions).not.toContain('Россия');
    expect(result.regionOptions).not.toContain('Онлайн');
    expect(result.regionOptions).toEqual(
      [...result.regionOptions].sort((a, b) => a.localeCompare(b, 'ru'))
    );
    expect(result.topicOptions).toEqual(
      [...result.topicOptions].sort((a, b) => a.localeCompare(b, 'ru'))
    );
  });
});
