import { describe, expect, it } from 'vitest';
import { groupGeographies } from './geography';

describe('public geography filter groups', () => {
  it('deduplicates district aliases and separates subjects', () => {
    const groups = groupGeographies([
      { slug: 'far-eastern', name: 'Дальневосточный' },
      { slug: 'far-eastern-federal-district', name: 'Дальневосточный федеральный округ' },
      { slug: 'primorsky-krai', name: 'Приморский край' },
      { slug: 'russia', name: 'Россия' }
    ]);

    expect(groups.country).toEqual([{ slug: 'russia', name: 'Россия' }]);
    expect(groups.districts).toEqual([{ slug: 'far-eastern', name: 'Дальневосточный' }]);
    expect(groups.subjects).toEqual([{ slug: 'primorsky-krai', name: 'Приморский край' }]);
  });
});
